from __future__ import annotations

import json
import hashlib
from typing import Any

from app.database import Database, new_id, utc_now
from app.services.world import WorldEngine, WorldValidationError


PLANNING_STAGES = (
    (1, "foundation", "Premise, genre, tone, themes, default POV, and narration style"),
    (2, "systems", "Lore, technology, magic, their rules, costs, limits, and social consequences"),
    (3, "major_locations", "Major regions and locations with hierarchical coordinates"),
    (4, "secondary_locations", "Secondary locations and realistic travel routes between locations"),
    (5, "cast", "Characters, factions, relationships, starting positions, and initial knowledge"),
    (6, "plot", "Flexible plot beats, secrets, constraints, unresolved threads, and possible endings"),
)


def _short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)].rstrip() + "... [trimmed]"


def _bounded_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep complete JSON records; never cut serialized JSON in the middle."""
    kept: list[dict[str, Any]] = []
    for item in items:
        candidate = [*kept, item]
        if len(json.dumps(candidate, separators=(",", ":"), ensure_ascii=False)) > limit:
            break
        kept.append(item)
    return kept


def stage_prompt(
    stage: dict[str, Any],
    session: dict[str, Any],
    approved: list[dict[str, Any]],
    world_inventory: list[dict[str, Any]] | None = None,
    *,
    character_budget: int = 13_000,
    repair_text: str = "",
) -> list[dict[str, str]]:
    """Build a compact prompt that fits small local-model context windows.

    Approved stages are projections, not full drafts. The character budget is a
    second guard around llama.cpp's token counter because /tokenize does not
    include the server-side chat template on every llama.cpp version.
    """
    settings = json.loads(session["settings_json"])
    compact_prior = []
    for item in approved:
        if not item.get("approved_json"):
            continue
        data = json.loads(item["approved_json"])
        compact_prior.append({
            "stage": item["stage_number"], "kind": item["kind"], "summary": _short_text(data.get("summary", ""), 900),
            "entities": [{key: entity.get(key) for key in ("key", "kind", "name")} for entity in data.get("entities", [])[:80]],
            "relations": [
                {key: relation.get(key) for key in ("source_key", "target_key", "relation", "travel_minutes", "bidirectional") if relation.get(key) is not None}
                for relation in data.get("relations", [])[:60]
            ],
        })
    # Allocate the finite prompt budget to instructions first, then prior plan
    # and the canonical-name inventory. Complete entries are retained in order.
    prior_limit = max(1_500, min(5_500, character_budget // 3))
    inventory_limit = max(1_000, min(4_000, character_budget // 4))
    compact_prior = _bounded_items(compact_prior, prior_limit)
    compact_inventory = _bounded_items([
        {
            "id": item.get("id"), "kind": item.get("kind"), "name": _short_text(item.get("name"), 100),
            "aliases": [_short_text(alias, 60) for alias in item.get("aliases", [])[:3]],
            "tags": [_short_text(tag, 40) for tag in item.get("tags", [])[:6]],
        }
        for item in (world_inventory or [])
    ], inventory_limit)
    prior = json.dumps(compact_prior, separators=(",", ":"), ensure_ascii=False)
    counts = (
        f"Target {settings.get('major_locations', 4)} major locations, "
        f"{settings.get('secondary_locations', 12)} secondary locations, and "
        f"{settings.get('characters', 8)} significant characters across the complete plan."
    )
    stage_limits = {
        1: "Keep this foundation compact; normally use notes and no more than 2 entities.",
        2: "Define at most 4 lore_system entities. Put concise rules in their state; do not invent the cast or locations yet.",
        3: f"Create at most {int(settings.get('major_locations', 4))} major location entities.",
        4: f"Create at most {int(settings.get('secondary_locations', 12))} secondary locations plus only the routes needed to connect them.",
        5: f"Create at most {int(settings.get('characters', 8))} significant characters and essential factions/relationships.",
        6: "Create concise plot_beat and fact entities only; prefer 6-10 flexible beats over exhaustive prose.",
    }
    schema = {
        "summary": "short stage overview",
        "notes": ["player-editable planning notes"],
        "entities": [{"key": "stable_key", "kind": "supported entity kind", "name": "name", "aliases": [], "tags": [], "state": {}}],
        "relations": [{"source_key": "key", "target_key": "key", "relation": "route or another relation", "travel_minutes": 0, "modes": ["walk"], "bidirectional": True}],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are a collaborative story-world architect. Produce concise, evocative material matching the player's requested genre and tone. Produce only a JSON object matching the supplied shape. "
                "Use stable snake_case keys, never duplicate approved entities, and treat plot beats as optional guidance. "
                "Location state uses parent_location_id only when an approved UUID is known; otherwise relations and keys connect them. "
                "Character state may include personality, appearance, wardrobe, equipment, abilities, current_location_key, "
                "player_controlled, visibility, and knowledge. Location state may include x, y, radius, terrain, culture, and summary."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Generate planning stage {stage['stage_number']}: {stage['kind']}. Goal: {stage['description']}.\n"
                f"{counts}\n{stage_limits.get(int(stage['stage_number']), '')}\nPlayer direction: {_short_text(settings.get('direction', '') or 'Use your best judgment.', 2200)}\n"
                f"Player notes for this stage: {_short_text(stage.get('human_prompt') or 'No additional notes.', 3200)}\n"
                f"Approved earlier stages:\n{prior or '(none)'}\n"
                f"Existing canonical world (reuse these; do not duplicate names):\n{json.dumps(compact_inventory, separators=(',', ':'), ensure_ascii=False)}\n\n"
                f"JSON shape:\n{json.dumps(schema)}"
                + (
                    "\n\nRepair the following incomplete or malformed prior response. Preserve usable content, "
                    "close unfinished strings/arrays/objects, and return one complete valid JSON object only:\n"
                    + _short_text(repair_text, max(1_500, min(6_000, character_budget // 2)))
                    if repair_text else ""
                )
            ),
        },
    ]
    # Extremely large player fields or schemas should still never evade the
    # dispatch guard. Rebuild with smaller user fields before a last-resort
    # whole-message trim that keeps valid reference JSON intact above.
    total = sum(len(message["content"]) for message in messages)
    if total > character_budget:
        excess = total - character_budget
        user = messages[1]["content"]
        marker = "\nApproved earlier stages:"
        prefix, separator, suffix = user.partition(marker)
        if separator:
            prefix = _short_text(prefix, max(900, len(prefix) - excess))
            messages[1]["content"] = prefix + separator + suffix
    return messages


class PlanningService:
    def __init__(self, db: Database, world: WorldEngine) -> None:
        self.db, self.world = db, world

    def create_session(self, project_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        active = self.db.fetch_one(
            "SELECT * FROM planning_sessions WHERE project_id = ? AND status = 'active' ORDER BY created_at DESC", (project_id,)
        )
        if active:
            return self.get_session(active["id"])
        session_id, now = new_id(), utc_now()
        normalized_settings = {
            "major_locations": int(settings.get("major_locations", 4)),
            "secondary_locations": int(settings.get("secondary_locations", 12)),
            "characters": int(settings.get("characters", 8)),
            "direction": str(settings.get("direction", ""))[:10000],
        }
        with self.db._lock, self.db.connect() as connection:
            connection.execute(
                "INSERT INTO planning_sessions(id, project_id, status, settings_json, current_stage, created_at, updated_at) "
                "VALUES (?, ?, 'active', ?, 1, ?, ?)",
                (session_id, project_id, json.dumps(normalized_settings), now, now),
            )
            for number, kind, _ in PLANNING_STAGES:
                connection.execute(
                    "INSERT INTO planning_stages(id, session_id, stage_number, kind, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                    (new_id(), session_id, number, kind, now, now),
                )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self.db.fetch_one("SELECT * FROM planning_sessions WHERE id = ?", (session_id,))
        if not session:
            raise WorldValidationError("Planning session not found")
        session["settings"] = json.loads(session.pop("settings_json"))
        session["recovery_warnings"] = json.loads(session.pop("recovery_warnings_json", "[]") or "[]")
        stages = self.db.fetch_all("SELECT * FROM planning_stages WHERE session_id = ? ORDER BY stage_number", (session_id,))
        for stage in stages:
            stage["draft"] = json.loads(stage["draft_json"]) if stage["draft_json"] else None
            stage["approved"] = json.loads(stage["approved_json"]) if stage["approved_json"] else None
            stage["conflicts"] = self.conflicts_for_stage(stage["id"])
            stage["operation"] = None
            if stage.get("active_job_id"):
                job = self.db.get_job(stage["active_job_id"])
                if job:
                    stage["operation"] = {
                        key: job.get(key) for key in (
                            "id", "status", "phase", "progress_message", "progress_current",
                            "progress_total", "error", "created_at", "updated_at",
                        )
                    }
        session["stages"] = stages
        return session

    def world_inventory(self, project_id: str) -> list[dict[str, Any]]:
        return [
            {"id": entity["id"], "kind": entity["kind"], "name": entity["name"], "aliases": entity.get("aliases", []), "tags": entity.get("tags", [])}
            for entity in self.world.projection(project_id)["entities"].values()
            if not entity.get("state", {}).get("archived")
        ]

    def conflicts_for_stage(self, stage_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all("SELECT * FROM planning_conflicts WHERE stage_id=? ORDER BY entity_key", (stage_id,))
        for row in rows:
            row["proposed"] = json.loads(row.pop("proposed_json"))
            row["candidates"] = json.loads(row.pop("candidates_json"))
            row["resolution"] = json.loads(row.pop("resolution_json")) if row.get("resolution_json") else None
        return rows

    def preflight(self, session_id: str, stage_number: int, draft: dict[str, Any]) -> list[dict[str, Any]]:
        self.validate_draft(draft)
        session = self.db.fetch_one("SELECT * FROM planning_sessions WHERE id=?", (session_id,))
        stage = self.db.fetch_one("SELECT * FROM planning_stages WHERE session_id=? AND stage_number=?", (session_id, stage_number))
        if not session or not stage:
            raise WorldValidationError("Planning stage not found")
        inventory, conflicts, now = self.world_inventory(session["project_id"]), [], utc_now()
        with self.db._lock, self.db.connect() as connection:
            connection.execute("DELETE FROM planning_conflicts WHERE stage_id=?", (stage["id"],))
            for proposed in draft.get("entities", []):
                names = {str(proposed["name"]).casefold(), *[str(alias).casefold() for alias in proposed.get("aliases", [])]}
                candidates = [item for item in inventory if item["name"].casefold() in names or names.intersection(str(alias).casefold() for alias in item.get("aliases", []))]
                if not candidates:
                    continue
                exact = [item for item in candidates if item["name"].casefold() == str(proposed["name"]).casefold() and item["kind"] == proposed["kind"]]
                recommended = {"action": "link", "entity_id": exact[0]["id"]} if len(exact) == 1 else None
                conflict = {"id": new_id(), "session_id": session_id, "stage_id": stage["id"], "entity_key": proposed["key"],
                            "proposed": proposed, "candidates": candidates, "recommended_resolution": recommended, "status": "unresolved"}
                connection.execute(
                    "INSERT INTO planning_conflicts(id,session_id,stage_id,entity_key,proposed_json,candidates_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'unresolved',?,?)",
                    (conflict["id"], session_id, stage["id"], proposed["key"], json.dumps(proposed), json.dumps(candidates), now, now),
                )
                conflicts.append(conflict)
        return conflicts

    def stage_for_generation(self, session_id: str, stage_number: int) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        session_raw = self.db.fetch_one("SELECT * FROM planning_sessions WHERE id = ?", (session_id,))
        stage = self.db.fetch_one(
            "SELECT * FROM planning_stages WHERE session_id = ? AND stage_number = ?", (session_id, stage_number)
        )
        if not session_raw or not stage:
            raise WorldValidationError("Planning stage not found")
        if session_raw["status"] != "active":
            raise WorldValidationError("Planning session is not active")
        unapproved_prior = self.db.fetch_one(
            "SELECT id FROM planning_stages WHERE session_id = ? AND stage_number < ? AND status != 'approved' LIMIT 1",
            (session_id, stage_number),
        )
        if unapproved_prior:
            raise WorldValidationError("Approve earlier planning stages first")
        description = next(item[2] for item in PLANNING_STAGES if item[0] == stage_number)
        stage["description"] = description
        approved = self.db.fetch_all(
            "SELECT * FROM planning_stages WHERE session_id = ? AND stage_number < ? AND status = 'approved' ORDER BY stage_number",
            (session_id, stage_number),
        )
        return session_raw, stage, approved

    def save_draft(self, stage_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        self.validate_draft(draft)
        self.db.execute(
            "UPDATE planning_stages SET draft_json = ?, raw_draft_text=NULL, validation_error=NULL, status = 'ready', updated_at = ? WHERE id = ?",
            (json.dumps(draft), utc_now(), stage_id),
        )
        return self.db.fetch_one("SELECT * FROM planning_stages WHERE id = ?", (stage_id,)) or {}

    def save_generated_draft(self, stage_id: str, job_id: str, draft: dict[str, Any]) -> bool:
        self.validate_draft(draft)
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE planning_stages SET draft_json=?,raw_draft_text=NULL,validation_error=NULL,status='ready',active_job_id=NULL,updated_at=? WHERE id=? AND active_job_id=?",
                (json.dumps(draft), now, stage_id, job_id),
            )
            if cursor.rowcount != 1:
                connection.execute("UPDATE planning_stage_revisions SET draft_json=?,status='superseded',updated_at=? WHERE job_id=?",
                                   (json.dumps(draft), now, job_id))
                return False
            connection.execute("UPDATE planning_stage_revisions SET draft_json=?,status='ready',updated_at=? WHERE job_id=?",
                               (json.dumps(draft), now, job_id))
        return True

    def save_invalid_generated_draft(self, stage_id: str, job_id: str, raw: str, error: str) -> bool:
        """Retain malformed model output so it can be edited or repaired."""
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            cursor = connection.execute(
                "UPDATE planning_stages SET draft_json=NULL,raw_draft_text=?,validation_error=?,status='ready',active_job_id=NULL,updated_at=? "
                "WHERE id=? AND active_job_id=?",
                (raw, error, now, stage_id, job_id),
            )
            connection.execute(
                "UPDATE planning_stage_revisions SET raw_output=?,validation_error=?,status='invalid',updated_at=? WHERE job_id=?",
                (raw, error, now, job_id),
            )
        return cursor.rowcount == 1

    @staticmethod
    def validate_draft(draft: dict[str, Any]) -> None:
        if not isinstance(draft, dict) or not isinstance(draft.get("summary", ""), str):
            raise WorldValidationError("Planning output must be an object with a summary")
        if not isinstance(draft.get("entities", []), list) or not isinstance(draft.get("relations", []), list):
            raise WorldValidationError("Planning entities and relations must be arrays")
        keys: set[str] = set()
        for entity in draft.get("entities", []):
            if not isinstance(entity, dict) or entity.get("kind") not in {
                "character", "location", "faction", "item", "lore_system", "fact", "relationship", "plot_beat"
            }:
                raise WorldValidationError("Every planning entity needs a stable key, supported kind, and name")
            key, name = str(entity.get("key", "")), str(entity.get("name", ""))
            if not key or not name or key in keys:
                raise WorldValidationError("Planning entity keys and names must be non-empty and unique within the stage")
            keys.add(key)

    def approve_stage(self, session_id: str, stage_number: int, draft: dict[str, Any], resolutions: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        self.validate_draft(draft)
        session = self.db.fetch_one("SELECT * FROM planning_sessions WHERE id = ?", (session_id,))
        stage = self.db.fetch_one("SELECT * FROM planning_stages WHERE session_id = ? AND stage_number = ?", (session_id, stage_number))
        if not session or not stage:
            raise WorldValidationError("Planning stage not found")
        digest = hashlib.sha256(json.dumps(draft, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if stage["status"] == "approved":
            if stage.get("approved_revision_hash") == digest or json.loads(stage.get("approved_json") or "null") == draft:
                transaction = self.db.fetch_one("SELECT * FROM world_transactions WHERE id=?", (stage.get("transaction_id"),)) or {"id": stage.get("transaction_id")}
                return {"transaction": transaction, "session": self.get_session(session_id), "duplicate": True}
            raise WorldValidationError("Reopen this approved stage before approving different content")

        existing_keys = {row["entity_key"]: row["entity_id"] for row in self.db.fetch_all(
            "SELECT * FROM planning_entity_keys WHERE session_id = ?", (session_id,)
        )}
        resolutions = resolutions or {}
        conflicts = {item["entity_key"]: item for item in self.preflight(session_id, stage_number, draft)}
        omitted: set[str] = set()
        creates: list[dict[str, Any]] = []
        raw: list[dict[str, Any]] = []
        for entity in draft.get("entities", []):
            conflict = conflicts.get(entity["key"])
            if entity["key"] in existing_keys and not conflict:
                raw.append({"tool": "updateEntity", "arguments": {"entity_id": existing_keys[entity["key"]], "patch": entity.get("state", {}),
                            "aliases": entity.get("aliases", []), "tags": entity.get("tags", [])}})
                continue
            if not conflict:
                creates.append(entity); continue
            resolution = resolutions.get(entity["key"]) or conflict.get("recommended_resolution")
            if not resolution:
                raise WorldValidationError(f"Planning conflict for '{entity['name']}' requires review")
            action = resolution.get("action")
            if action == "omit":
                omitted.add(entity["key"]); continue
            if action == "rename":
                name = str(resolution.get("new_name", "")).strip()
                if not name:
                    raise WorldValidationError("Create renamed requires a unique new name")
                creates.append({**entity, "name": name}); continue
            candidate = next((item for item in conflict["candidates"] if item["id"] == resolution.get("entity_id")), None)
            if action not in {"link", "merge"} or not candidate or candidate["kind"] != entity["kind"]:
                raise WorldValidationError("Link and merge require a same-kind candidate")
            existing_keys[entity["key"]] = candidate["id"]
            if action == "merge":
                current_entity = self.world.projection(session["project_id"])["entities"][candidate["id"]]
                raw.append({"tool": "updateEntity", "arguments": {"entity_id": candidate["id"], "patch": merge_planning(current_entity.get("state", {}), entity.get("state", {})),
                            "aliases": list(dict.fromkeys([*candidate.get("aliases", []), *entity.get("aliases", [])])),
                            "tags": list(dict.fromkeys([*candidate.get("tags", []), *entity.get("tags", [])]))}})
            self.db.execute("UPDATE planning_conflicts SET resolution_json=?,status='resolved',updated_at=? WHERE id=?",
                            (json.dumps(resolution), utc_now(), conflict["id"]))
        for entity in creates:
            raw.append({"tool": "createEntity", "arguments": {**entity, "state": copy_state(entity.get("state", {}), existing_keys)}})
        for relation in draft.get("relations", []):
            if relation.get("source_key") in omitted or relation.get("target_key") in omitted:
                continue
            raw.append({"tool": "setRelationship", "arguments": {**relation,
                        "source_id": existing_keys.get(relation.get("source_key"), relation.get("source_key")),
                        "target_id": existing_keys.get(relation.get("target_key"), relation.get("target_key"))}})
        normalized = self.world.normalize_mutations(session["project_id"], None, raw, provenance="planning")
        combined_keys = dict(existing_keys)
        for mutation in normalized:
            if mutation.tool == "createEntity" and mutation.arguments.get("key"):
                combined_keys[str(mutation.arguments["key"])] = mutation.arguments["entity_id"]
        for mutation in normalized:
            if mutation.tool == "createEntity":
                mutation.arguments["state"] = copy_state(mutation.arguments.get("state", {}), combined_keys)
        try:
            self.db.execute("INSERT INTO planning_approval_claims(stage_id,revision_hash,created_at) VALUES(?,?,?)", (stage["id"], digest, utc_now()))
        except Exception as exc:
            raise WorldValidationError("This planning stage is already being approved; refresh its status") from exc
        try:
            transaction = self.world.commit_root(session["project_id"], normalized, provenance="planning", summary=str(draft.get("summary", "")))
        except Exception:
            self.db.execute("DELETE FROM planning_approval_claims WHERE stage_id=?", (stage["id"],))
            raise
        with self.db._lock, self.db.connect() as connection:
            for key, entity_id in combined_keys.items():
                connection.execute("INSERT OR REPLACE INTO planning_entity_keys(session_id,entity_key,entity_id,stage_number) VALUES(?,?,?,?)", (session_id, key, entity_id, stage_number))
            connection.execute(
                "UPDATE planning_stages SET status='approved',draft_json=?,raw_draft_text=NULL,validation_error=NULL,approved_json=?,transaction_id=?,approved_revision_hash=?,active_job_id=NULL,updated_at=? WHERE id=?",
                (json.dumps(draft), json.dumps(draft), transaction["id"], digest, utc_now(), stage["id"]),
            )
            next_stage = stage_number + 1
            connection.execute("UPDATE planning_sessions SET current_stage=?,status=?,updated_at=? WHERE id=?",
                               (min(next_stage, len(PLANNING_STAGES)), "completed" if next_stage > len(PLANNING_STAGES) else "active", utc_now(), session_id))
        return {"transaction": transaction, "session": self.get_session(session_id)}

    def reopen_stage(self, session_id: str, stage_number: int) -> dict[str, Any]:
        session = self.db.fetch_one("SELECT * FROM planning_sessions WHERE id = ?", (session_id,))
        stages = self.db.fetch_all(
            "SELECT * FROM planning_stages WHERE session_id = ? AND stage_number >= ? ORDER BY stage_number", (session_id, stage_number)
        )
        if not session or not stages:
            raise WorldValidationError("Planning stage not found")
        if any(stage["status"] in {"queued", "generating"} for stage in stages):
            raise WorldValidationError("Cancel active planning generation before reopening a stage")
        with self.db._lock, self.db.connect() as connection:
            for stage in stages:
                if stage.get("transaction_id"):
                    connection.execute("INSERT OR IGNORE INTO inactive_world_transactions(transaction_id,planning_session_id,reason,created_at) VALUES(?,?,?,?)",
                                       (stage["transaction_id"], session_id, "planning_stage_reopened", utc_now()))
                if stage["stage_number"] == stage_number:
                    connection.execute("UPDATE planning_stages SET status = 'ready', approved_json = NULL, transaction_id = NULL, updated_at = ? WHERE id = ?", (utc_now(), stage["id"]))
                else:
                    connection.execute("UPDATE planning_stages SET status = 'pending', draft_json = NULL, raw_draft_text=NULL, validation_error=NULL, approved_json = NULL, transaction_id = NULL, updated_at = ? WHERE id = ?", (utc_now(), stage["id"]))
            connection.execute("DELETE FROM planning_entity_keys WHERE session_id=? AND stage_number>=?", (session_id, stage_number))
            connection.execute("DELETE FROM planning_approval_claims WHERE stage_id IN (SELECT id FROM planning_stages WHERE session_id=? AND stage_number>=?)", (session_id, stage_number))
            connection.execute("UPDATE planning_sessions SET status = 'active', current_stage = ?, updated_at = ? WHERE id = ?", (stage_number, utc_now(), session_id))
            connection.execute("DELETE FROM world_projection_cache WHERE project_id = ?", (session["project_id"],))
        return self.get_session(session_id)


def copy_state(state: dict[str, Any], known_keys: dict[str, str]) -> dict[str, Any]:
    copied = json.loads(json.dumps(state))
    for key in list(copied):
        if key.endswith("_key") and copied[key] in known_keys:
            copied[key.removesuffix("_key") + "_id"] = known_keys[copied.pop(key)]
    return copied


def merge_planning(current: Any, proposed: Any) -> Any:
    if isinstance(current, dict) and isinstance(proposed, dict):
        return {**current, **{key: merge_planning(current.get(key), value) for key, value in proposed.items()}}
    if isinstance(current, list) and isinstance(proposed, list):
        merged = json.loads(json.dumps(current))
        for item in proposed:
            if item not in merged:
                merged.append(json.loads(json.dumps(item)))
        return merged
    return proposed
