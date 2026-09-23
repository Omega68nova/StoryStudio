from __future__ import annotations

import json
from typing import Any

from app.database import Database, new_id, utc_now
from app.data.dataProvider import DataProvider
from app.services.planning_v2 import (
    PLANNING_STAGES, STAGE_CONSUMES, apply_foundation, apply_outfits, apply_rules, apply_runtime,
    apply_weather, compact_schema, dependency_snapshot, empty_draft, normalized_settings,
    prepare_image_plans, published_domains, record_resource, resolve_resource, stable_hash,
    validate_catalog_references, validate_stage, world_payload, STAGE_GENERATION_FOCI,
)
from app.services.world import WorldEngine, WorldValidationError

STAGE_PUBLISHES = {
    1: {"foundation"}, 2: {"macro_locations", "weather"}, 3: {"detailed_locations"},
    4: {"rules", "stats_abilities"}, 5: {"cast"}, 6: {"character_details"},
    7: {"runtime_configuration"}, 8: {"visual_assets"},
}
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


def _entity_fingerprint(entity: dict[str, Any]) -> str:
    return stable_hash({key: entity.get(key) for key in ("kind", "name", "aliases", "tags", "state")})


def random_direction_messages(theme: str = "") -> list[dict[str, str]]:
    theme = " ".join(str(theme or "").split())[:200]
    theme_instruction = (
        f'Use "{theme}" as the required thematic or genre seed, interpreting it creatively while choosing all other details. '
        if theme else
        "Choose the thematic and genre seed freely. "
    )
    return [
        {
            "role": "system",
            "content": (
                "You invent original, coherent story concepts with bold combinations. Return only one ready-to-use "
                "creative-direction prompt for another story-planning AI. Do not add an introduction or commentary."
            ),
        },
        {
            "role": "user",
            "content": (
                theme_instruction +
                "Create a surprising random story direction. Randomly choose and clearly establish: the central theme; "
                "intended audience or age rating and relevant character ages; genre, historical era, setting, and scale; "
                "important world systems such as magic, technology, health, social rules, skills, or suitable minigames; "
                "a small central cast with roles and tensions; memorable major and minor locations; and the initial dramatic "
                "situation. Make the choices fit together while avoiding familiar franchise settings. Write 180 to 350 words "
                "as direct instructions that can be pasted into a story preplanning workshop."
            ),
        },
    ]


def stage_prompt(
    stage: dict[str, Any],
    session: dict[str, Any],
    approved: list[dict[str, Any]],
    world_inventory: list[dict[str, Any]] | None = None,
    *,
    character_budget: int = 13_000,
    repair_text: str = "",
    focus: str | None = None,
    existing_draft: dict[str, Any] | None = None,
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
        context: dict[str, Any] = {}
        if int(item["stage_number"]) == 1:
            foundation = data.get("foundation") or {}
            context = {key: _short_text(foundation.get(key), 700) for key in ("premise", "tone", "style", "world_description", "character_description")}
            context.update({"genres": list(foundation.get("genres") or [])[:12], "themes": list(foundation.get("themes") or [])[:12], "pov_strategy": foundation.get("pov_strategy")})
        elif int(item["stage_number"]) in {2, 3, 5, 6}:
            context = {
                field: [{"key": record.get("key"), "name": record.get("name")} for record in data.get(field, [])[:80] if isinstance(record, dict)]
                for field in ("locations", "weather", "characters", "factions", "lore_systems", "items", "facts", "plot_beats") if data.get(field)
            }
        compact_prior.append({
            "stage": item["stage_number"], "kind": item["kind"], "summary": _short_text(data.get("summary", ""), 900),
            "resource_keys": [item.get("key") for field in ("entities", "locations", "characters", "factions", "facts", "lore_systems", "items", "plot_beats") for item in data.get(field, [])[:80] if isinstance(item, dict)],
            "context": context,
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
    counts = (f"Scale {settings.get('scale_preset', 'local')}. Caps: {settings.get('major_locations', 6)} major locations, "
              f"{settings.get('minor_locations', 20)} minor locations, {settings.get('rooms', 16)} rooms, "
              f"and {settings.get('characters', 10)} characters across the complete plan.")
    stage_limits = {
        1: "Keep the foundation compact and do not create world records yet.",
        2: f"Create no more than {int(settings.get('major_locations', 6))} connected major locations. Define weather transitions explicitly.",
        3: f"Create no more than {int(settings.get('minor_locations', 20))} minor locations and {int(settings.get('rooms', 16))} rooms. Only create rooms likely to recur.",
        4: (
            "Define reusable lore systems, stat definitions, abilities, and only important system-linked items. "
            "Every lore system requires a clear state.description plus its rules, limits, costs, and secrets. "
            "Stats and abilities are separate layers: define and save stats before generating abilities. "
            "Abilities use a typed target_type, recursive requirements, a costs object, and an effects array. "
            "Effects may select actor, target, party, location, allies, enemies, faction members, all, or a resolved random target. "
            "Supported operations include bounded stat changes, move, create/remove, status, knowledge, relationship, time, and one-shot noise. "
            "Every referenced stat_key must be defined; dynamic formulas such as damage='atk' are unsupported."
        ),
        5: (
            f"Create no more than {int(settings.get('characters', 10))} characters and classify every character's cast_role. "
            "Every character must include a useful state.description and state.appearance. Also provide identity, pronouns, "
            "personality, goals, general narrator secret notes, character_secrets, secrets_to_character, control settings, "
            "and a current_location_key when known. Keep background characters concise, but do not return empty placeholder fields."
        ),
        6: (
            "Detail existing characters; prefer flexible hooks over a rigid plot. Preserve or enrich description, identity, "
            "pronouns, appearance, personality, goals, secrets, wardrobe, equipment, inventory, abilities, relationship notes, "
            "character_secrets, and secrets_to_character."
        ),
        7: "Use only catalog IDs supplied in context. Never invent files, sounds, music themes, or minigame IDs.",
        8: "This stage is deterministic and must not be generated by the language model.",
    }
    stage_number = int(stage["stage_number"])
    schema = compact_schema(stage_number, focus)
    existing = []
    if focus and existing_draft:
        for item in existing_draft.get(focus, []) if isinstance(existing_draft.get(focus), list) else []:
            if isinstance(item, dict):
                existing.append({key: item.get(key) for key in ("key", "id", "stat_key", "ability_key", "game_key", "name", "label") if item.get(key) is not None})
    current_stage_context: dict[str, Any] = {}
    if focus and existing_draft:
        for field, records in existing_draft.items():
            if not isinstance(records, list) or field in {"notes"}:
                continue
            compact_records = []
            for record in records[:100]:
                if isinstance(record, dict):
                    compact_records.append({key: record.get(key) for key in ("key", "id", "stat_key", "ability_key", "game_key", "name", "label", "source_key", "target_key") if record.get(key) is not None})
            if compact_records:
                current_stage_context[field] = compact_records
    focus_instruction = ""
    if focus:
        focus_instruction = (
            f"Generate only a new batch for the '{focus}' section. Existing accepted records in this section are listed below; "
            "fill meaningful gaps and do not repeat, rename, or rewrite them. It is valid to return a small batch.\n"
            f"Existing {focus}: {json.dumps(existing, separators=(',', ':'), ensure_ascii=False)}\n"
            f"Other accepted resources in this editable stage (reference by key where useful): {json.dumps(current_stage_context, separators=(',', ':'), ensure_ascii=False)}\n"
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a collaborative story-world architect. Produce concise, evocative material matching the player's requested genre and tone. Produce only a JSON object matching the supplied shape. "
                "Use stable snake_case keys and never duplicate approved resources. Return only the stage-specific JSON shape. "
                "Reference earlier resources by their stable keys. Keep plans compact and treat plot beats as optional guidance."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Generate planning stage {stage['stage_number']}: {stage['kind']}. Goal: {stage['description']}.\n{focus_instruction}"
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
    """Planning semantics without a second workflow/state machine."""

    def __init__(
        self,
        db: Database,
        world: WorldEngine,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.world = world
        self.data = data_provider or DataProvider(db)

    def _plan(self, plan_id: str) -> dict[str, Any]:
        plan = self.db.fetch_one(
            "SELECT * FROM generation_plans WHERE id=?",
            (plan_id,),
        )
        if not plan or plan.get("source_kind") != "planning_workspace":
            raise WorldValidationError("Planning workspace not found")
        plan = dict(plan)
        plan["settings"] = json.loads(plan.get("settings_json") or "{}")
        return plan

    def world_inventory(
        self,
        project_id: str,
        include_catalogs: bool = False,
        plan_id: str | None = None,
    ) -> list[dict[str, Any]]:
        projection = self.world.projection(project_id)
        planning_keys = {
            row["resource_id"]: row["resource_key"]
            for row in self.db.fetch_all(
                "SELECT resource_id,resource_key FROM generation_resource_keys "
                "WHERE generation_plan_id=?",
                (plan_id,),
            )
        } if plan_id else {}

        items = [
            {
                "id": planning_keys.get(entity["id"], entity["id"]),
                "canonical_id": entity["id"],
                "kind": entity["kind"],
                "name": entity["name"],
                "aliases": entity.get("aliases", []),
                "tags": entity.get("tags", []),
            }
            for entity in projection["entities"].values()
            if not entity.get("state", {}).get("archived")
        ]
        items += [
            {
                "id": planning_keys.get(relation["id"], relation["id"]),
                "canonical_id": relation["id"],
                "kind": "route",
                "name": (
                    f"{projection['entities'].get(relation.get('source_id'), {}).get('name', relation.get('source_id'))}"
                    f" -> {projection['entities'].get(relation.get('target_id'), {}).get('name', relation.get('target_id'))}"
                ),
                "aliases": [],
                "tags": list(relation.get("modes") or []),
            }
            for relation in projection["relations"].values()
            if relation.get("relation") == "route"
        ]
        items += [
            {
                "id": planning_keys.get(row["id"], row["id"]),
                "canonical_id": row["id"],
                "kind": "weather",
                "name": row["name"],
                "aliases": [],
                "tags": json.loads(row["tags_json"]),
            }
            for row in self.db.fetch_all(
                "SELECT id,name,tags_json FROM weather_definitions WHERE project_id=?",
                (project_id,),
            )
        ]
        items += [
            {
                "id": row["stat_key"],
                "canonical_id": row["id"],
                "kind": "stat",
                "name": row["label"],
                "aliases": [row["stat_key"]],
                "tags": [row["scope"]],
            }
            for row in self.db.fetch_all(
                "SELECT id,stat_key,label,scope FROM stat_definitions WHERE project_id=?",
                (project_id,),
            )
        ]
        items += [
            {
                "id": row["ability_key"],
                "canonical_id": row["id"],
                "kind": "ability",
                "name": row["name"],
                "aliases": [row["ability_key"]],
                "tags": [row["target_type"]],
            }
            for row in self.db.fetch_all(
                "SELECT id,ability_key,name,target_type FROM ability_definitions WHERE project_id=?",
                (project_id,),
            )
        ]
        if include_catalogs:
            items += [
                {
                    "id": row["game_key"],
                    "canonical_id": row["game_key"],
                    "kind": "minigame",
                    "name": row["game_key"],
                    "aliases": [],
                    "tags": [],
                }
                for row in self.db.fetch_all(
                    "SELECT game_key FROM project_minigame_configs WHERE project_id=?",
                    (project_id,),
                )
            ]
            items += [
                {
                    "id": row["id"],
                    "canonical_id": row["id"],
                    "kind": "ambient_variant",
                    "name": row["label"],
                    "aliases": [],
                    "tags": json.loads(row["tags_json"]),
                }
                for row in self.db.fetch_all(
                    "SELECT id,label,tags_json FROM ambient_variants "
                    "WHERE project_id=? AND enabled=1 AND available=1",
                    (project_id,),
                )
            ]
            items += [
                {
                    "id": row["id"],
                    "canonical_id": row["id"],
                    "kind": "music_theme",
                    "name": row["name"],
                    "aliases": [],
                    "tags": [],
                }
                for row in self.db.fetch_all("SELECT id,name FROM music_themes")
            ]
            for kind, table in (
                ("bullet_mode", "bullethell_modes"),
                ("bullet_skill", "bullethell_skills"),
                ("bullet_attack", "bullethell_attacks"),
            ):
                items += [
                    {
                        "id": row["id"],
                        "canonical_id": row["id"],
                        "kind": kind,
                        "name": row["name"],
                        "aliases": [],
                        "tags": [],
                    }
                    for row in self.db.fetch_all(f"SELECT id,name FROM {table}")
                ]
        return items

    def preflight(
        self,
        plan_id: str,
        stage_number: int,
        draft: dict[str, Any],
    ) -> list[dict[str, Any]]:
        plan = self._plan(plan_id)
        validate_stage(stage_number, draft, plan["settings"])
        proposed_entities, _ = world_payload(stage_number, draft)
        inventory = self.world_inventory(plan["project_id"], plan_id=plan_id)
        projection = self.world.projection(plan["project_id"])
        conflicts: list[dict[str, Any]] = []

        for proposed in proposed_entities:
            linked = self.db.fetch_one(
                "SELECT resource_id,fingerprint FROM generation_resource_keys "
                "WHERE generation_plan_id=? AND resource_key=? "
                "AND resource_type='entity'",
                (plan_id, proposed["key"]),
            )
            if linked:
                current = projection["entities"].get(linked["resource_id"])
                if (
                    current
                    and linked.get("fingerprint")
                    and linked["fingerprint"] != _entity_fingerprint(current)
                ):
                    conflicts.append(
                        {
                            "id": new_id(),
                            "entity_key": proposed["key"],
                            "proposed": {
                                **proposed,
                                "_planning_conflict": "manual_change",
                            },
                            "candidates": [
                                {
                                    "id": current["id"],
                                    "kind": current["kind"],
                                    "name": current["name"],
                                    "aliases": current.get("aliases", []),
                                    "tags": current.get("tags", []),
                                }
                            ],
                            "recommended_resolution": None,
                            "status": "unresolved",
                        }
                    )
                continue

            names = {
                str(proposed["name"]).casefold(),
                *[
                    str(alias).casefold()
                    for alias in proposed.get("aliases", [])
                ],
            }
            candidates = [
                item
                for item in inventory
                if item["name"].casefold() in names
                or names.intersection(
                    str(alias).casefold()
                    for alias in item.get("aliases", [])
                )
            ]
            if not candidates:
                continue
            exact = [
                item
                for item in candidates
                if item["name"].casefold()
                == str(proposed["name"]).casefold()
                and item["kind"] == proposed["kind"]
            ]
            recommended = (
                {
                    "action": "link",
                    "entity_id": exact[0].get("canonical_id", exact[0]["id"]),
                }
                if len(exact) == 1 else None
            )
            conflicts.append(
                {
                    "id": new_id(),
                    "entity_key": proposed["key"],
                    "proposed": proposed,
                    "candidates": [
                        {
                            **item,
                            "id": item.get("canonical_id", item["id"]),
                        }
                        for item in candidates
                    ],
                    "recommended_resolution": recommended,
                    "status": "unresolved",
                }
            )
        return conflicts

    @staticmethod
    def validate_draft(
        draft: dict[str, Any],
        stage_number: int = 1,
        settings: dict[str, Any] | None = None,
    ) -> None:
        validate_stage(stage_number, draft, settings)

    def publish(
        self,
        plan_id: str,
        stage_number: int,
        draft: dict[str, Any],
        resolutions: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(plan_id)
        project_id = str(plan["project_id"])
        validate_stage(stage_number, draft, plan["settings"])
        validate_catalog_references(self.db, project_id, stage_number, draft)

        proposed_entities, proposed_relations = world_payload(stage_number, draft)
        existing_keys = {
            row["resource_key"]: row["resource_id"]
            for row in self.db.fetch_all(
                "SELECT resource_key,resource_id FROM generation_resource_keys "
                "WHERE generation_plan_id=? AND resource_type='entity'",
                (plan_id,),
            )
        }
        resolutions = resolutions or {}
        conflicts = {
            item["entity_key"]: item
            for item in self.preflight(plan_id, stage_number, draft)
        }
        omitted: set[str] = set()
        preserve_manual: set[str] = set()
        creates: list[dict[str, Any]] = []
        raw: list[dict[str, Any]] = []

        for entity in proposed_entities:
            conflict = conflicts.get(entity["key"])
            if entity["key"] in existing_keys and not conflict:
                raw.append(
                    {
                        "tool": "updateEntity",
                        "arguments": {
                            "entity_id": existing_keys[entity["key"]],
                            "name": entity["name"],
                            "patch": entity.get("state", {}),
                            "aliases": entity.get("aliases", []),
                            "tags": entity.get("tags", []),
                        },
                    }
                )
                continue
            if not conflict:
                creates.append(entity)
                continue

            resolution = (
                resolutions.get(entity["key"])
                or conflict.get("recommended_resolution")
            )
            if not resolution:
                raise WorldValidationError(
                    f"Planning conflict for '{entity['name']}' requires review"
                )
            action = resolution.get("action")
            if action in {"keep_manual", "unlink"}:
                preserve_manual.add(entity["key"])
                if action == "unlink":
                    self.db.execute(
                        "DELETE FROM generation_resource_keys "
                        "WHERE generation_plan_id=? AND resource_key=?",
                        (plan_id, entity["key"]),
                    )
                continue
            if action == "overwrite" and entity["key"] in existing_keys:
                raw.append(
                    {
                        "tool": "updateEntity",
                        "arguments": {
                            "entity_id": existing_keys[entity["key"]],
                            "name": entity["name"],
                            "patch": entity.get("state", {}),
                            "aliases": entity.get("aliases", []),
                            "tags": entity.get("tags", []),
                        },
                    }
                )
                continue
            if action == "omit":
                omitted.add(entity["key"])
                continue
            if action == "rename":
                name = str(resolution.get("new_name", "")).strip()
                if not name:
                    raise WorldValidationError(
                        "Create renamed requires a unique new name"
                    )
                creates.append({**entity, "name": name})
                continue
            candidate = next(
                (
                    item
                    for item in conflict["candidates"]
                    if item["id"] == resolution.get("entity_id")
                ),
                None,
            )
            if (
                action not in {"link", "merge"}
                or not candidate
                or candidate["kind"] != entity["kind"]
            ):
                raise WorldValidationError(
                    "Link and merge require a same-kind candidate"
                )
            existing_keys[entity["key"]] = candidate["id"]
            if action == "merge":
                current_entity = self.world.projection(project_id)["entities"][
                    candidate["id"]
                ]
                raw.append(
                    {
                        "tool": "updateEntity",
                        "arguments": {
                            "entity_id": candidate["id"],
                            "patch": merge_planning(
                                current_entity.get("state", {}),
                                entity.get("state", {}),
                            ),
                            "aliases": list(
                                dict.fromkeys(
                                    [
                                        *candidate.get("aliases", []),
                                        *entity.get("aliases", []),
                                    ]
                                )
                            ),
                            "tags": list(
                                dict.fromkeys(
                                    [
                                        *candidate.get("tags", []),
                                        *entity.get("tags", []),
                                    ]
                                )
                            ),
                        },
                    }
                )

        for entity in creates:
            raw.append(
                {
                    "tool": "createEntity",
                    "arguments": {
                        **entity,
                        "state": copy_state(
                            entity.get("state", {}),
                            existing_keys,
                        ),
                    },
                }
            )

        base_projection = self.world.projection(project_id)
        for relation in proposed_relations:
            if (
                relation.get("source_key") in omitted
                or relation.get("target_key") in omitted
            ):
                continue
            relation_id = (
                resolve_resource(
                    self.db,
                    plan_id,
                    relation.get("key"),
                    "relationship",
                )
                if relation.get("key") else None
            )
            current_relation = (
                base_projection["relations"].get(relation_id)
                if relation_id else None
            )
            source_id = existing_keys.get(
                relation.get("source_key"),
                relation.get("source_key"),
            )
            target_id = existing_keys.get(
                relation.get("target_key"),
                relation.get("target_key"),
            )
            if current_relation and (
                current_relation.get("source_id"),
                current_relation.get("target_id"),
                current_relation.get("relation"),
            ) != (
                source_id,
                target_id,
                relation.get("relation"),
            ):
                raw.append(
                    {
                        "tool": "removeRelationship",
                        "arguments": {"relationship_id": relation_id},
                    }
                )
                relation_id = new_id()
            raw.append(
                {
                    "tool": "setRelationship",
                    "arguments": {
                        **relation,
                        **({"id": relation_id} if relation_id else {}),
                        "source_id": source_id,
                        "target_id": target_id,
                    },
                }
            )

        normalized = self.world.normalize_mutations(
            project_id,
            None,
            raw,
            provenance="planning",
        )
        combined_keys = dict(existing_keys)
        for mutation in normalized:
            if mutation.tool == "createEntity" and mutation.arguments.get("key"):
                combined_keys[str(mutation.arguments["key"])] = (
                    mutation.arguments["entity_id"]
                )
        for mutation in normalized:
            if mutation.tool == "createEntity":
                mutation.arguments["state"] = copy_state(
                    mutation.arguments.get("state", {}),
                    combined_keys,
                )
            elif mutation.tool == "updateEntity":
                mutation.arguments["patch"] = copy_state(
                    mutation.arguments.get("patch", {}),
                    combined_keys,
                )

        self.db.begin_transaction()
        try:
            transaction = self.world.commit_root(
                project_id,
                normalized,
                provenance="planning",
                summary=str(draft.get("summary", "")),
            )
            if stage_number == 1:
                apply_foundation(self.db, project_id, draft)
            elif stage_number == 2:
                apply_weather(
                    self.db, project_id, plan_id, stage_number, draft
                )
            elif stage_number == 4:
                apply_rules(
                    self.db, project_id, plan_id, stage_number, draft
                )
            elif stage_number == 5:
                pov_key = str(
                    draft.get("default_pov_character_key") or ""
                )
                pov_id = combined_keys.get(pov_key) if pov_key else None
                if pov_id:
                    character = self.world.projection(
                        project_id,
                        use_cache=False,
                    )["entities"].get(pov_id)
                    if not character or not character.get(
                        "state", {}
                    ).get("player_controlled"):
                        raise WorldValidationError(
                            "Default POV must be a playable character"
                        )
                    self.db.execute(
                        "UPDATE project_story_defaults "
                        "SET pov_character_id=?,updated_at=? "
                        "WHERE project_id=?",
                        (pov_id, utc_now(), project_id),
                    )
            elif stage_number == 6:
                apply_outfits(
                    self.db, project_id, plan_id, stage_number, draft
                )
            elif stage_number == 7:
                apply_runtime(self.db, project_id, plan_id, draft)
            self.db.finish_transaction(commit=True)
        except Exception:
            self.db.finish_transaction(commit=False)
            raise

        projection = self.world.projection(project_id, use_cache=False)
        for entity in proposed_entities:
            if entity["key"] in preserve_manual:
                continue
            entity_id = combined_keys.get(str(entity["key"]))
            if entity_id:
                canonical = projection["entities"].get(entity_id)
                record_resource(
                    self.db,
                    plan_id,
                    stage_number,
                    entity["key"],
                    "entity",
                    entity_id,
                    canonical if canonical else entity,
                )
        for relation in proposed_relations:
            if not relation.get("key"):
                continue
            source = combined_keys.get(
                relation.get("source_key"),
                relation.get("source_key"),
            )
            target = combined_keys.get(
                relation.get("target_key"),
                relation.get("target_key"),
            )
            relation_id = next(
                (
                    item["id"]
                    for item in projection["relations"].values()
                    if item.get("source_id") == source
                    and item.get("target_id") == target
                    and item.get("relation") == relation.get("relation")
                ),
                None,
            )
            if relation_id:
                record_resource(
                    self.db,
                    plan_id,
                    stage_number,
                    relation["key"],
                    "relationship",
                    relation_id,
                    relation,
                )

        return {"transaction": transaction}

    def prepare_image_stage(
        self,
        plan_id: str,
        draft: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(plan_id)
        prepared = json.loads(
            json.dumps(draft if isinstance(draft, dict) else empty_draft(8))
        )
        plans = prepare_image_plans(
            self.db,
            plan["project_id"],
            plan_id,
            prepared,
        )
        prepared["assets"] = [
            {
                key: image_plan.get(key)
                for key in (
                    "resource_key",
                    "prompt",
                    "negative_prompt",
                    "workflow_preset_id",
                    "width",
                    "height",
                )
            }
            for image_plan in plans
        ]
        return {"draft": prepared, "image_plans": plans}


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
