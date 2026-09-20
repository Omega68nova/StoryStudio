from __future__ import annotations

import copy
import heapq
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.database import Database, new_id, utc_now


ENTITY_KINDS = {"character", "location", "faction", "item", "lore_system", "fact", "relationship", "plot_beat"}
NARRATION_MODES = {"first_person", "third_limited", "third_omniscient"}
READ_TOOLS = {
    "searchEntities", "getEntity", "getScene", "getNearbyLocations", "findRoute", "getKnownFacts", "getActivePlotBeats",
    "getStats", "getAbilities", "searchLocations", "getLocationMap", "getSceneEnvironment",
}
WRITE_TOOLS = {
    "createEntity", "updateEntity", "moveCharacter", "setRelationship", "revealKnowledge", "advanceTime", "updatePlotBeat",
    "removeRelationship", "adjustStat", "useAbility", "selectTheme",
    "adjustInventory", "setSceneEnvironment", "proposeWeather",
}
MAJOR_PATCH_FIELDS = {"identity", "alive", "permanent_injuries", "core_personality", "player_decision", "world_laws", "destroyed"}


class WorldValidationError(ValueError):
    pass


@dataclass
class NormalizedMutation:
    tool: str
    arguments: dict[str, Any]
    major: bool
    reason: str | None = None


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(target)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif value is None:
            merged.pop(key, None)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        return ", ".join(f"{key.replace('_', ' ')}: {_text(item)}" for key, item in value.items() if _text(item))
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value if _text(item))
    return str(value)


def make_lore_card(entity: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    state = entity.get("state", {})
    kind, name = entity["kind"], entity["name"]
    pieces = [f"{name} ({kind.replace('_', ' ')})"]
    ordered_fields = (
        "summary", "description", "personality", "core_personality", "appearance", "wardrobe", "equipment", "inventory", "abilities",
        "terrain", "culture", "rules", "status", "goals", "secrets", "current_location_id",
    )
    for field in ordered_fields:
        value = _text(state.get(field))
        if field == "current_location_id" and value in projection["entities"]:
            value = projection["entities"][value]["name"]
        if field == "inventory":
            value = ", ".join(
                f"{projection['entities'].get(str(entry.get('item_id')), {}).get('name', entry.get('item_id'))} x{entry.get('quantity', 0)}"
                for entry in state.get("inventory", []) if int(entry.get("quantity", 0)) > 0
            )
        if value:
            pieces.append(f"{field.replace('_', ' ')}: {value}")
    if entity.get("stats"):
        pieces.append("stats: " + _text(entity["stats"]))
    if entity.get("active_effects"):
        pieces.append("active effects: " + _text(entity["active_effects"]))
    compact = ". ".join(pieces)[:2400]
    visual_fields = ["appearance", "wardrobe", "equipment"]
    visual_parts = [_text(state.get(field)) for field in visual_fields]
    visual = f"{name}: " + "; ".join(part for part in visual_parts if part) if any(visual_parts) else ""
    tags = list(dict.fromkeys([
        *entity.get("tags", []),
        *[item.strip() for field in visual_fields for item in _text(state.get(field)).split(",") if item.strip()],
    ]))[:80]
    search = " ".join([name, *entity.get("aliases", []), *entity.get("tags", []), compact])
    return {"compact_text": compact, "visual_description": visual[:1600], "image_tags": tags, "search_text": search[:8000]}


class WorldEngine:
    def __init__(self, db: Database) -> None:
        self.db = db

    def projection(self, project_id: str, head_node_id: str | None = None, *, use_cache: bool = True) -> dict[str, Any]:
        if head_node_id is None:
            project = self.db.get_project(project_id) or {}
            head_node_id = project.get("active_node_id")
        cache_key = f"{project_id}:{head_node_id or 'root'}"
        if use_cache:
            cached = self.db.fetch_one("SELECT projection_json FROM world_projection_cache WHERE cache_key = ?", (cache_key,))
            if cached:
                return json.loads(cached["projection_json"])
        ancestry = {node["id"] for node in self.db.story_path(head_node_id)} if head_node_id else set()
        transactions = self.db.fetch_all(
            "SELECT * FROM world_transactions WHERE project_id = ? AND status = 'committed' "
            "AND id NOT IN (SELECT transaction_id FROM inactive_world_transactions) ORDER BY branch_sequence, created_at",
            (project_id,),
        )
        visible = [tx for tx in transactions if tx["story_node_id"] is None or tx["story_node_id"] in ancestry]
        projection: dict[str, Any] = {
            "project_id": project_id,
            "head_node_id": head_node_id,
            "entities": {},
            "relations": {},
            "elapsed_minutes": 0,
            "display_time": None,
            "current_theme_id": None,
            "current_weather_id": None,
            "focused_character_id": None,
            "player_action": "standing",
            "transactions": [],
        }
        for transaction in visible:
            events = self.db.fetch_all(
                "SELECT * FROM world_events WHERE transaction_id = ? ORDER BY ordinal", (transaction["id"],)
            )
            for event in events:
                self.apply_event(projection, event["event_type"], json.loads(event["payload_json"]), event.get("entity_id"))
                if event.get("entity_id") in projection["entities"]:
                    projection["entities"][event["entity_id"]]["last_changed_sequence"] = transaction["branch_sequence"]
            projection["transactions"].append({
                "id": transaction["id"], "story_node_id": transaction["story_node_id"],
                "summary": transaction["summary"], "display_time": transaction["display_time"],
                "elapsed_minutes": transaction["elapsed_minutes"], "provenance": transaction["provenance"],
            })
            projection["branch_sequence"] = transaction["branch_sequence"]
            self._expire_effects(projection)
        self.db.execute(
            "INSERT OR REPLACE INTO world_projection_cache(cache_key, project_id, head_node_id, projection_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (cache_key, project_id, head_node_id, json.dumps(projection), utc_now()),
        )
        return projection

    @staticmethod
    def apply_event(projection: dict[str, Any], event_type: str, payload: dict[str, Any], entity_id: str | None) -> None:
        entities, relations = projection["entities"], projection["relations"]
        if event_type == "entity.created":
            entity = copy.deepcopy(payload["entity"])
            entities[entity["id"]] = entity
        elif event_type == "entity.updated" and entity_id in entities:
            entities[entity_id]["state"] = _deep_merge(entities[entity_id].get("state", {}), payload.get("patch", {}))
            if "name" in payload:
                entities[entity_id]["name"] = payload["name"]
            if "tags" in payload:
                entities[entity_id]["tags"] = list(dict.fromkeys(payload["tags"]))
            if "aliases" in payload:
                entities[entity_id]["aliases"] = list(dict.fromkeys(payload["aliases"]))
        elif event_type == "character.moved" and entity_id in entities:
            entities[entity_id].setdefault("state", {})["current_location_id"] = payload["destination_id"]
            destination = entities.get(payload["destination_id"])
            if destination:
                destination.setdefault("state", {})["discovered"] = True
        elif event_type == "relationship.set":
            relation_id = payload.get("id") or f"{payload['source_id']}:{payload['relation']}:{payload['target_id']}"
            relations[relation_id] = copy.deepcopy({**payload, "id": relation_id})
        elif event_type == "relationship.removed":
            relations.pop(str(payload.get("relationship_id")), None)
        elif event_type == "knowledge.revealed" and entity_id in entities:
            state = entities[entity_id].setdefault("state", {})
            state["known_character_ids"] = list(dict.fromkeys([*state.get("known_character_ids", []), *payload.get("character_ids", [])]))
            state["known_faction_ids"] = list(dict.fromkeys([*state.get("known_faction_ids", []), *payload.get("faction_ids", [])]))
        elif event_type == "time.advanced":
            projection["elapsed_minutes"] += max(0, int(payload.get("minutes", 0)))
            if payload.get("display_time"):
                projection["display_time"] = payload["display_time"]
        elif event_type == "plot_beat.updated" and entity_id in entities:
            entities[entity_id].setdefault("state", {}).update({key: value for key, value in payload.items() if key != "entity_id"})
        elif event_type == "stat.changed":
            container = entities.get(payload.get("entity_id")) or relations.get(payload.get("relation_id"))
            if container is not None:
                container.setdefault("stats", {})[payload["stat_key"]] = payload["value"]
        elif event_type == "effect.applied":
            container = entities.get(payload.get("entity_id")) or relations.get(payload.get("relation_id"))
            if container is not None:
                container.setdefault("active_effects", []).append(copy.deepcopy(payload))
        elif event_type == "theme.selected":
            projection["current_theme_id"] = payload.get("theme_id")
        elif event_type == "environment.scene_set":
            projection["focused_character_id"] = payload.get("focused_character_id")
            projection["player_action"] = payload.get("player_action", "standing")
            if payload.get("weather_id"):
                projection["current_weather_id"] = payload["weather_id"]
        elif event_type == "inventory.adjusted" and entity_id in entities:
            inventory = list(entities[entity_id].setdefault("state", {}).get("inventory", []))
            found = False
            for entry in inventory:
                if entry.get("item_id") == payload["item_id"]:
                    entry["quantity"] = payload["quantity"]
                    found = True
                    break
            if not found and payload["quantity"] > 0:
                inventory.append({"item_id": payload["item_id"], "quantity": payload["quantity"]})
            entities[entity_id]["state"]["inventory"] = [entry for entry in inventory if int(entry.get("quantity", 0)) > 0]

    @staticmethod
    def _expire_effects(projection: dict[str, Any]) -> None:
        sequence, elapsed = projection.get("branch_sequence", 0), projection.get("elapsed_minutes", 0)
        for container in [*projection["entities"].values(), *projection["relations"].values()]:
            container["active_effects"] = [
                effect for effect in container.get("active_effects", [])
                if not ((effect.get("expires_sequence") is not None and sequence >= effect["expires_sequence"])
                        or (effect.get("expires_elapsed_minutes") is not None and elapsed >= effect["expires_elapsed_minutes"]))
            ]

    def normalize_mutations(
        self, project_id: str, head_node_id: str | None, raw: Iterable[dict[str, Any]], *, provenance: str = "ai",
        staged: list[NormalizedMutation] | None = None,
    ) -> list[NormalizedMutation]:
        projection = self.projection(project_id, head_node_id)
        projection["_next_sequence"] = len(self.db.story_path(head_node_id)) + 1
        for mutation in staged or []:
            self._apply_mutation_preview(projection, mutation)
        normalized: list[NormalizedMutation] = []
        names = {entity["name"].casefold() for entity in projection["entities"].values() if not entity.get("state", {}).get("archived")}
        temporary_ids: dict[str, str] = {}
        for item in raw:
            tool = str(item.get("tool") or item.get("name") or "")
            arguments = copy.deepcopy(item.get("arguments") or item.get("args") or {})
            if tool not in WRITE_TOOLS:
                raise WorldValidationError(f"Unsupported mutation tool: {tool or '(missing)'}")
            for key, value in list(arguments.items()):
                if key.endswith("_id") and isinstance(value, str) and value in temporary_ids:
                    arguments[key] = temporary_ids[value]
            major, reason = False, None
            if tool == "createEntity":
                kind = arguments.get("kind")
                name = str(arguments.get("name", "")).strip()
                if kind not in ENTITY_KINDS or not name:
                    raise WorldValidationError("createEntity requires a supported kind and non-empty name")
                if name.casefold() in names:
                    raise WorldValidationError(f"An entity named '{name}' already exists on this branch")
                entity_id = str(arguments.get("entity_id") or new_id())
                if entity_id in projection["entities"]:
                    raise WorldValidationError(f"Entity ID already exists: {entity_id}")
                if arguments.get("key"):
                    temporary_ids[str(arguments["key"])] = entity_id
                arguments["entity_id"] = entity_id
                arguments["name"] = name
                arguments["aliases"] = list(dict.fromkeys(arguments.get("aliases", [])))
                arguments["tags"] = list(dict.fromkeys(arguments.get("tags", [])))
                arguments["state"] = arguments.get("state") or {}
                if kind == "character" and arguments["state"].get("player_controlled") and arguments["state"].get("autonomy_enabled"):
                    raise WorldValidationError("Player-controlled characters cannot enable NPC autonomy")
                if kind == "location":
                    settings = self.db.fetch_one("SELECT enabled,ai_create_locations FROM project_environment_settings WHERE project_id=?", (project_id,))
                    if provenance in {"ai", "storyteller_inline"} and settings and (not settings["enabled"] or not settings["ai_create_locations"]):
                        raise WorldValidationError("AI location creation is disabled for this story")
                    location_state = arguments["state"]
                    location_state.setdefault("description", "")
                    location_state.setdefault("exposure", "outdoor")
                    location_state.setdefault("image_tags", [])
                    location_state.setdefault("imagegen_description", "")
                    location_state.setdefault("enabled", True)
                    location_state.setdefault("random_encounter", False)
                    location_state.setdefault("discovered", not location_state["random_encounter"])
                    if location_state["exposure"] not in {"indoor", "outdoor", "isolated"}:
                        raise WorldValidationError("Location exposure must be indoor, outdoor, or isolated")
                names.add(name.casefold())
                if kind == "lore_system" and provenance == "ai":
                    major, reason = True, "Creates a new world-rule system"
            elif tool == "updateEntity":
                entity = self._entity(projection, arguments.get("entity_id"))
                patch = arguments.get("patch")
                if not isinstance(patch, dict):
                    raise WorldValidationError("updateEntity patch must be an object")
                if not patch and not any(key in arguments for key in ("name", "aliases", "tags")):
                    raise WorldValidationError("updateEntity requires at least one change")
                if "name" in arguments:
                    renamed = str(arguments["name"]).strip()
                    if not renamed:
                        raise WorldValidationError("Entity name cannot be empty")
                    for other in projection["entities"].values():
                        if other["id"] != entity["id"] and not other.get("state", {}).get("archived") and other["name"].casefold() == renamed.casefold():
                            raise WorldValidationError(f"An active entity named '{renamed}' already exists")
                    arguments["name"] = renamed
                changed = MAJOR_PATCH_FIELDS.intersection(patch)
                if changed:
                    major, reason = True, "Changes " + ", ".join(sorted(changed))
                if entity["kind"] == "character" and entity.get("state", {}).get("player_controlled") and {"personality", "core_personality", "goals"}.intersection(patch):
                    major, reason = True, "Changes a player-controlled character's agency or personality"
                if entity["kind"] == "character" and {"player_controlled", "autonomy_enabled"}.intersection(patch):
                    player_controlled = patch.get("player_controlled", entity.get("state", {}).get("player_controlled", False))
                    autonomy_enabled = patch.get("autonomy_enabled", entity.get("state", {}).get("autonomy_enabled", False))
                    if player_controlled and autonomy_enabled:
                        raise WorldValidationError("Player-controlled characters cannot enable NPC autonomy")
                if entity["kind"] == "lore_system" and {"rules", "limits", "costs"}.intersection(patch):
                    major, reason = True, "Changes established world-system rules"
            elif tool == "moveCharacter":
                character = self._entity(projection, arguments.get("character_id"), "character")
                destination = self._entity(projection, arguments.get("destination_id"), "location")
                source_id = character.get("state", {}).get("current_location_id")
                arguments["source_id"] = source_id
                if source_id != destination["id"] and not self._location_enabled(projection, destination["id"]):
                    raise WorldValidationError(f"Location '{destination['name']}' is disabled")
                if source_id and source_id != destination["id"] and not arguments.get("bypass_reason"):
                    route = self._path(projection, source_id, destination["id"], arguments.get("mode"))
                    if not route:
                        raise WorldValidationError(f"No traversable route connects {source_id} to {destination['id']}")
                    arguments.setdefault("elapsed_minutes", int(route.get("travel_minutes", 0)))
                elif arguments.get("bypass_reason"):
                    abilities = _text(character.get("state", {}).get("abilities", [])).casefold()
                    if str(arguments["bypass_reason"]).casefold() not in abilities:
                        raise WorldValidationError("Movement bypass must name an ability possessed by the character")
            elif tool == "setRelationship":
                self._entity(projection, arguments.get("source_id"))
                self._entity(projection, arguments.get("target_id"))
                relation = str(arguments.get("relation", "")).strip()
                if not relation:
                    raise WorldValidationError("setRelationship requires a relation type")
                if relation in {"allegiance", "marriage", "oath"} and arguments.get("major", False):
                    major, reason = True, f"Major relationship change: {relation}"
            elif tool == "removeRelationship":
                relationship_id = str(arguments.get("relationship_id", ""))
                if relationship_id not in projection["relations"]:
                    raise WorldValidationError("Relationship is not available on this branch")
                arguments = {"relationship_id": relationship_id}
            elif tool == "revealKnowledge":
                self._entity(projection, arguments.get("fact_id"), "fact")
                for character_id in arguments.get("character_ids", []):
                    self._entity(projection, character_id, "character")
                for faction_id in arguments.get("faction_ids", []):
                    self._entity(projection, faction_id, "faction")
            elif tool == "advanceTime":
                minutes = int(arguments.get("minutes", 0))
                if minutes < 0:
                    raise WorldValidationError("Story time cannot move backward")
                arguments["minutes"] = minutes
            elif tool == "setSceneEnvironment":
                settings = self.db.fetch_one("SELECT enabled,initial_weather_id FROM project_environment_settings WHERE project_id=?", (project_id,)) or {"enabled": 0}
                if not settings["enabled"]:
                    raise WorldValidationError("The environment system is disabled")
                focus_id = str(arguments.get("focused_character_id") or "")
                focus = self._entity(projection, focus_id, "character")
                if not focus.get("state", {}).get("player_controlled"):
                    raise WorldValidationError("Scene focus must be a player-controlled character")
                action = str(arguments.get("player_action") or "").strip().casefold()
                if len(action) > 48 or not re.fullmatch(r"[a-z][a-z -]*ing", action):
                    raise WorldValidationError("Player action must be a short lowercase action ending in ing")
                arguments = {"focused_character_id": focus_id, "player_action": action}
                requested_weather = item.get("arguments", {}).get("weather_id")
                if requested_weather:
                    weather = self.db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=? AND enabled=1", (requested_weather, project_id))
                    if not weather:
                        raise WorldValidationError("Weather is not enabled for this story")
                    current = projection.get("current_weather_id") or settings.get("initial_weather_id")
                    if not self.db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=? AND enabled=1", (current, project_id)):
                        current = settings.get("initial_weather_id")
                    if current != requested_weather and not self.db.fetch_one("SELECT 1 FROM weather_transitions WHERE project_id=? AND source_weather_id=? AND target_weather_id=?", (project_id, current, requested_weather)):
                        raise WorldValidationError("The requested weather transition is not allowed")
                    arguments["weather_id"] = requested_weather
            elif tool == "proposeWeather":
                settings = self.db.fetch_one("SELECT enabled,ai_propose_weather FROM project_environment_settings WHERE project_id=?", (project_id,)) or {"enabled": 0, "ai_propose_weather": 0}
                if not settings["enabled"] or not settings["ai_propose_weather"]:
                    raise WorldValidationError("AI weather proposals are disabled")
                name = str(arguments.get("name") or "").strip()
                if not name:
                    raise WorldValidationError("Weather proposal requires a name")
                arguments = {"proposal_id": new_id(), "name": name[:120], "description": str(arguments.get("description") or "")[:2000], "tags": list(arguments.get("tags") or [])[:40], "image_tags": list(arguments.get("image_tags") or [])[:40], "transition_ids": list(arguments.get("transition_ids") or [])[:40]}
            elif tool == "updatePlotBeat":
                self._entity(projection, arguments.get("entity_id"), "plot_beat")
                if arguments.get("status") not in {"planned", "available", "active", "resolved", "abandoned"}:
                    raise WorldValidationError("Unsupported plot-beat status")
            elif tool == "adjustStat":
                arguments = self._normalize_stat_adjustment(project_id, projection, arguments)
            elif tool == "useAbility":
                arguments = self._normalize_ability(project_id, projection, arguments, provenance)
            elif tool == "selectTheme":
                theme_id = str(arguments.get("theme_id", ""))
                settings = self.db.fetch_one("SELECT mode FROM project_music_settings WHERE project_id = ?", (project_id,))
                if provenance in {"ai", "npc"} and (not settings or settings["mode"] != "ai_managed"):
                    raise WorldValidationError("The storyteller may select music only in AI-managed mode")
                allowed = self.db.fetch_one(
                    "SELECT 1 FROM project_music_themes WHERE project_id = ? AND theme_id = ?", (project_id, theme_id)
                )
                mode = self.db.fetch_one("SELECT mode FROM project_music_settings WHERE project_id = ?", (project_id,)) or {"mode": "disabled"}
                if not allowed or (provenance == "ai" and mode["mode"] != "ai_managed"):
                    raise WorldValidationError("Theme is not enabled for AI selection in this project")
            elif tool == "adjustInventory":
                character = self._entity(projection, arguments.get("character_id"), "character")
                item = self._entity(projection, arguments.get("item_id"), "item")
                delta = int(arguments.get("delta", 0))
                if not delta:
                    raise WorldValidationError("Inventory adjustment cannot be zero")
                current = next((int(entry.get("quantity", 0)) for entry in character.get("state", {}).get("inventory", []) if entry.get("item_id") == item["id"]), 0)
                if current + delta < 0:
                    raise WorldValidationError(f"{character['name']} does not have enough {item['name']}")
                arguments = {"character_id": character["id"], "item_id": item["id"], "delta": delta, "previous_quantity": current, "quantity": current + delta}
            mutation = NormalizedMutation(tool, arguments, major, reason)
            normalized.append(mutation)
            self._apply_mutation_preview(projection, mutation)
        return normalized

    def _stat_definition(self, project_id: str, key: str, scope: str) -> dict[str, Any]:
        definition = self.db.fetch_one(
            "SELECT * FROM stat_definitions WHERE project_id = ? AND stat_key = ? AND scope = ?", (project_id, key, scope)
        )
        if not definition:
            raise WorldValidationError(f"Unknown {scope} stat: {key}")
        return definition

    def _normalize_stat_adjustment(self, project_id: str, projection: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        target_key = "entity_id" if arguments.get("entity_id") else "relation_id"
        target_id = str(arguments.get(target_key, ""))
        container = projection["entities"].get(target_id) if target_key == "entity_id" else projection["relations"].get(target_id)
        scope = "character" if target_key == "entity_id" else "relationship"
        if not container or (scope == "character" and container.get("kind") != "character"):
            raise WorldValidationError("Stat target is not available")
        definition = self._stat_definition(project_id, str(arguments.get("stat_key", "")), scope)
        current = float(container.get("stats", {}).get(definition["stat_key"], definition["default_value"]))
        amount, operation = float(arguments.get("amount", 0)), arguments.get("operation", "add")
        if operation not in {"add", "subtract", "set"}:
            raise WorldValidationError("Stat operation must be add, subtract, or set")
        value = amount if operation == "set" else current + amount * (1 if operation == "add" else -1)
        value = max(float(definition["minimum"]), min(float(definition["maximum"]), value))
        if definition["integer_only"]:
            value = int(round(value))
        return {target_key: target_id, "stat_key": definition["stat_key"], "value": value, "previous_value": current}

    def _normalize_ability(self, project_id: str, projection: dict[str, Any], arguments: dict[str, Any], provenance: str) -> dict[str, Any]:
        actor = self._entity(projection, arguments.get("actor_id"), "character")
        if actor.get("state", {}).get("player_controlled") and provenance not in {"player", "author"}:
            raise WorldValidationError("Player-character abilities require an explicit player request")
        row = self.db.fetch_one("SELECT * FROM ability_definitions WHERE project_id = ? AND ability_key = ?", (project_id, arguments.get("ability_key")))
        if not row:
            raise WorldValidationError("Unknown ability")
        known = actor.get("state", {}).get("abilities", [])
        if row["ability_key"] not in known and row["name"] not in known:
            raise WorldValidationError(f"{actor['name']} does not know {row['name']}")
        requirements = json.loads(row["requirements_json"])
        if not set(requirements.get("tags", [])).issubset(set(actor.get("tags", []))):
            raise WorldValidationError(f"{actor['name']} does not meet the ability requirements")
        actor_effective = self.effective_stats(project_id, actor)
        for key, minimum in requirements.get("min_stats", {}).items():
            definition = self._stat_definition(project_id, key, "character")
            if float(actor_effective.get(key, definition["default_value"])) < float(minimum):
                raise WorldValidationError(f"{actor['name']} does not meet the {definition['label']} requirement")
        target_id = arguments.get("target_id") or actor["id"]
        if row["target_type"] in {"self", "character"}:
            target = self._entity(projection, target_id, "character")
            if row["target_type"] == "self" and target["id"] != actor["id"]:
                raise WorldValidationError("This ability can target only its actor")
        elif target_id not in projection["relations"]:
            raise WorldValidationError("Ability relationship target is unavailable")
        costs, effects = json.loads(row["costs_json"]), json.loads(row["effects_json"])
        working_values: dict[tuple[str, str, str], float] = {}

        def base_value(scope: str, container_id: str, definition: dict[str, Any]) -> float:
            key = (scope, container_id, definition["stat_key"])
            if key not in working_values:
                container = projection["relations"].get(container_id) if scope == "relationship" else projection["entities"].get(container_id)
                working_values[key] = float(container.get("stats", {}).get(definition["stat_key"], definition["default_value"]))
            return working_values[key]

        normalized_costs = []
        for key, cost in costs.items():
            definition = self._stat_definition(project_id, key, "character")
            cost = float(cost)
            if cost < 0:
                raise WorldValidationError("Ability costs cannot be negative")
            current = base_value("character", actor["id"], definition)
            available = self.effective_stats(project_id, actor).get(key, current)
            if available < cost:
                raise WorldValidationError(f"{actor['name']} lacks enough {definition['label']}")
            value = max(float(definition["minimum"]), min(float(definition["maximum"]), current - cost))
            if definition["integer_only"]: value = int(round(value))
            working_values[("character", actor["id"], key)] = value
            normalized_costs.append({"entity_id": actor["id"], "stat_key": key, "value": value, "previous_value": current})
        normalized_effects = []
        for effect in effects:
            resolved_target = actor["id"] if effect.get("target", "target") == "actor" else target_id
            scope = "relationship" if row["target_type"] == "relationship" and resolved_target == target_id else "character"
            definition = self._stat_definition(project_id, str(effect.get("stat_key", "")), scope)
            current = base_value(scope, resolved_target, definition)
            operation, amount = effect.get("operation", "add"), float(effect.get("amount", 0))
            if operation not in {"add", "subtract", "set"}:
                raise WorldValidationError("Ability effect operation must be add, subtract, or set")
            value = amount if operation == "set" else current + amount * (1 if operation == "add" else -1)
            value = max(float(definition["minimum"]), min(float(definition["maximum"]), value))
            if definition["integer_only"]:
                value = int(round(value))
            target_key = "relation_id" if scope == "relationship" else "entity_id"
            normalized = {"stat_key": definition["stat_key"], "operation": operation, "amount": amount,
                          "previous_value": current, "value": value, target_key: resolved_target}
            duration_type, duration = effect.get("duration_type"), int(effect.get("duration_value", 0) or 0)
            if duration_type == "turns" and duration > 0:
                normalized["expires_sequence"] = int(projection.get("_next_sequence", 0)) + duration
            elif duration_type == "minutes" and duration > 0:
                normalized["expires_elapsed_minutes"] = int(projection.get("elapsed_minutes", 0)) + duration
            else:
                working_values[(scope, resolved_target, definition["stat_key"])] = value
            normalized_effects.append(normalized)
        return {"actor_id": actor["id"], "target_id": target_id, "ability_key": row["ability_key"], "ability_name": row["name"], "costs": normalized_costs, "effects": normalized_effects}

    @staticmethod
    def _entity(projection: dict[str, Any], entity_id: Any, expected_kind: str | None = None) -> dict[str, Any]:
        entity = projection["entities"].get(str(entity_id))
        if not entity:
            raise WorldValidationError(f"Unknown entity: {entity_id}")
        if expected_kind and entity["kind"] != expected_kind:
            raise WorldValidationError(f"Entity '{entity['name']}' is not a {expected_kind}")
        return entity

    @staticmethod
    def _route(projection: dict[str, Any], source_id: str, target_id: str, mode: str | None = None) -> dict[str, Any] | None:
        for relation in projection["relations"].values():
            if relation.get("relation") != "route" or relation.get("blocked"):
                continue
            endpoints = {relation.get("source_id"), relation.get("target_id")}
            if endpoints == {source_id, target_id} and (not mode or mode in relation.get("modes", [mode])):
                return relation
        return None

    @staticmethod
    def _location_enabled(projection: dict[str, Any], location_id: str | None) -> bool:
        current, seen = projection.get("entities", {}).get(location_id), set()
        while current and current.get("kind") == "location" and current["id"] not in seen:
            seen.add(current["id"])
            if not current.get("state", {}).get("enabled", True):
                return False
            current = projection["entities"].get(current.get("state", {}).get("parent_location_id"))
        return True

    @staticmethod
    def _path(projection: dict[str, Any], source_id: str, target_id: str, mode: str | None = None) -> dict[str, Any] | None:
        adjacency: dict[str, list[tuple[str, int, dict[str, Any]]]] = {}
        for relation in projection["relations"].values():
            if relation.get("relation") != "route" or relation.get("blocked") or (mode and mode not in relation.get("modes", [mode])):
                continue
            source, target = relation["source_id"], relation["target_id"]
            weight = max(0, int(relation.get("travel_minutes", 0)))
            adjacency.setdefault(source, []).append((target, weight, relation))
            if relation.get("bidirectional", True): adjacency.setdefault(target, []).append((source, weight, relation))
        if source_id != target_id and not WorldEngine._location_enabled(projection, target_id):
            return None
        allowed_disabled: set[str] = set()
        if not WorldEngine._location_enabled(projection, source_id):
            pending = [source_id]
            while pending:
                current = pending.pop()
                if current in allowed_disabled:
                    continue
                allowed_disabled.add(current)
                pending.extend(neighbor for neighbor, _, _ in adjacency.get(current, []) if not WorldEngine._location_enabled(projection, neighbor))
        heap: list[tuple[int, str, list[str], list[str]]] = [(0, source_id, [], [source_id])]
        visited: set[str] = set()
        while heap:
            total, current, relation_ids, location_ids = heapq.heappop(heap)
            if current in visited: continue
            visited.add(current)
            if current == target_id:
                return {"travel_minutes": total, "relation_ids": relation_ids, "location_ids": location_ids,
                        "locations": [{"id": value, "name": projection["entities"].get(value, {}).get("name", value)} for value in location_ids]}
            for neighbor, weight, relation in adjacency.get(current, []):
                if not WorldEngine._location_enabled(projection, neighbor) and neighbor not in allowed_disabled:
                    continue
                if neighbor not in visited: heapq.heappush(heap, (total + weight, neighbor, [*relation_ids, relation["id"]], [*location_ids, neighbor]))
        return None

    def _apply_mutation_preview(self, projection: dict[str, Any], mutation: NormalizedMutation) -> None:
        for event_type, entity_id, payload in self._mutation_events(mutation):
            self.apply_event(projection, event_type, payload, entity_id)

    @staticmethod
    def _mutation_events(mutation: NormalizedMutation) -> list[tuple[str, str | None, dict[str, Any]]]:
        tool, args = mutation.tool, mutation.arguments
        if tool == "createEntity":
            entity = {
                "id": args["entity_id"], "kind": args["kind"], "name": args["name"],
                "aliases": args.get("aliases", []), "tags": args.get("tags", []), "state": args.get("state", {}),
            }
            return [("entity.created", entity["id"], {"entity": entity})]
        if tool == "updateEntity":
            return [("entity.updated", args["entity_id"], {key: args[key] for key in ("patch", "name", "tags", "aliases") if key in args})]
        if tool == "moveCharacter":
            events = [("character.moved", args["character_id"], args)]
            if args.get("elapsed_minutes") or args.get("display_time"):
                events.append(("time.advanced", None, {"minutes": args.get("elapsed_minutes", 0), "display_time": args.get("display_time")}))
            return events
        if tool == "setRelationship":
            return [("relationship.set", None, args)]
        if tool == "removeRelationship":
            return [("relationship.removed", None, args)]
        if tool == "revealKnowledge":
            return [("knowledge.revealed", args["fact_id"], args)]
        if tool == "advanceTime":
            return [("time.advanced", None, args)]
        if tool == "updatePlotBeat":
            return [("plot_beat.updated", args["entity_id"], args)]
        if tool == "adjustStat":
            return [("stat.changed", args.get("entity_id"), args)]
        if tool == "selectTheme":
            return [("theme.selected", None, args)]
        if tool == "useAbility":
            rows: list[tuple[str, str | None, dict[str, Any]]] = [("ability.used", args["actor_id"], args)]
            rows.extend(("stat.changed", cost.get("entity_id"), cost) for cost in args.get("costs", []))
            for effect in args.get("effects", []):
                payload = {**effect, "ability_key": args["ability_key"]}
                if "expires_sequence" in effect or "expires_elapsed_minutes" in effect:
                    rows.append(("effect.applied", payload.get("entity_id"), payload))
                else:
                    rows.append(("stat.changed", payload.get("entity_id"), payload))
            return rows
        if tool == "adjustInventory":
            return [("inventory.adjusted", args["character_id"], args)]
        if tool == "setSceneEnvironment":
            return [("environment.scene_set", None, args)]
        if tool == "proposeWeather":
            return [("weather.proposed", None, args)]
        raise WorldValidationError(f"Unsupported mutation tool: {tool}")

    def preview(self, project_id: str, head_node_id: str | None, mutations: list[NormalizedMutation]) -> dict[str, Any]:
        projected = copy.deepcopy(self.projection(project_id, head_node_id))
        for mutation in mutations:
            self._apply_mutation_preview(projected, mutation)
        return projected

    def commit_story_turn(
        self,
        project_id: str,
        parent_node_id: str,
        content: str,
        mutations: list[NormalizedMutation],
        *,
        pov_character_id: str | None,
        narration_mode: str,
        provenance: str = "ai",
        status: str = "complete",
        interventions: list[dict[str, Any]] | None = None,
        appearances: list[dict[str, Any]] | None = None,
        minigame_session_id: str | None = None,
        minigame_session_ids: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if narration_mode not in NARRATION_MODES:
            raise WorldValidationError("Unsupported narration mode")
        assistant_id = new_id()
        return self._commit(
            project_id, assistant_id, parent_node_id, mutations, provenance=provenance,
            assistant={"id": assistant_id, "content": content, "pov_character_id": pov_character_id,
                       "narration_mode": narration_mode, "status": status,
                       "interventions": interventions or [], "appearances": appearances or [],
                       "minigame_session_ids": list(dict.fromkeys([*(minigame_session_ids or []), *([minigame_session_id] if minigame_session_id else [])]))},
        )

    def commit_root(self, project_id: str, mutations: list[NormalizedMutation], *, provenance: str, summary: str) -> dict[str, Any]:
        _, transaction = self._commit(project_id, None, None, mutations, provenance=provenance, summary=summary)
        return transaction

    def commit_to_existing_node(
        self, project_id: str, story_node_id: str, mutations: list[NormalizedMutation], *, provenance: str, summary: str = ""
    ) -> dict[str, Any]:
        node = self.db.fetch_one("SELECT parent_id FROM story_nodes WHERE id = ? AND project_id = ?", (story_node_id, project_id))
        if not node:
            raise WorldValidationError("Story node not found")
        _, transaction = self._commit(project_id, story_node_id, node["parent_id"], mutations, provenance=provenance, summary=summary)
        return transaction

    def _commit(
        self,
        project_id: str,
        story_node_id: str | None,
        parent_node_id: str | None,
        mutations: list[NormalizedMutation],
        *,
        provenance: str,
        summary: str = "",
        assistant: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        base = self.projection(project_id, parent_node_id, use_cache=False)
        final = copy.deepcopy(base)
        event_rows: list[tuple[str, str | None, str, dict[str, Any], int]] = []
        new_entities: dict[str, dict[str, Any]] = {}
        affected: set[str] = set()
        ordinal = 0
        for mutation in mutations:
            for event_type, entity_id, payload in self._mutation_events(mutation):
                event_rows.append((new_id(), entity_id, event_type, payload, ordinal))
                ordinal += 1
                self.apply_event(final, event_type, payload, entity_id)
                if entity_id:
                    affected.add(entity_id)
                if event_type == "entity.created":
                    new_entities[entity_id or ""] = payload["entity"]
        for minigame_session_id in (assistant or {}).get("minigame_session_ids", []):
            minigame = self.db.fetch_one(
                "SELECT game_key,game_version,invocation_json,result_json FROM minigame_sessions WHERE id=?",
                (minigame_session_id,),
            )
            if not minigame or not minigame.get("result_json"):
                raise WorldValidationError("Resolved minigame result is missing")
            event_rows.append((new_id(), None, "minigame.completed", {
                "session_id": minigame_session_id, "game_key": minigame["game_key"],
                "game_version": minigame["game_version"], "invocation": json.loads(minigame["invocation_json"]),
                "result": json.loads(minigame["result_json"]),
            }, ordinal))
            ordinal += 1
        self._validate_projection(final)
        transaction_id, now = new_id(), utc_now()
        branch_sequence = len(self.db.story_path(parent_node_id)) + (1 if story_node_id else 0)
        elapsed = final["elapsed_minutes"] - base["elapsed_minutes"]
        with self.db._lock, self.db.connect() as connection:
            # Same-turn encounters and NPC records may reference an entity that
            # was just created by an inline action, so establish entity rows first.
            for entity in new_entities.values():
                connection.execute(
                    "INSERT INTO world_entities(id, project_id, kind, canonical_name, aliases_json, tags_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (entity["id"], project_id, entity["kind"], entity["name"], json.dumps(entity["aliases"]), json.dumps(entity["tags"]), now),
                )
            if assistant:
                connection.execute(
                    "INSERT INTO story_nodes(id, project_id, parent_id, role, content, status, created_at, pov_character_id, narration_mode) "
                    "VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?)",
                    (assistant["id"], project_id, parent_node_id, assistant["content"], assistant["status"], now,
                     assistant["pov_character_id"], assistant["narration_mode"]),
                )
                for intervention in assistant.get("interventions", []):
                    connection.execute(
                        "INSERT INTO npc_interventions(id, story_node_id, npc_id, dialogue, attempted_action, cited_fact_ids_json, ability_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (new_id(), assistant["id"], intervention["npc_id"], intervention.get("dialogue", ""),
                         intervention.get("attempted_action", ""), json.dumps(intervention.get("cited_fact_ids", [])),
                         intervention.get("ability_key"), now),
                    )
                for appearance in assistant.get("appearances", []):
                    connection.execute(
                        "INSERT INTO scene_appearances(id, story_node_id, entity_id, outfit_id, encounter_kind, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (new_id(), assistant["id"], appearance["entity_id"], appearance.get("outfit_id"), appearance["encounter_kind"], now),
                    )
            connection.execute(
                "INSERT INTO world_transactions(id, project_id, story_node_id, parent_node_id, branch_sequence, elapsed_minutes, display_time, provenance, status, summary, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'committed', ?, ?)",
                (transaction_id, project_id, story_node_id, parent_node_id, branch_sequence, elapsed,
                 final.get("display_time"), provenance, summary, now),
            )
            for event_id, entity_id, event_type, payload, event_ordinal in event_rows:
                connection.execute(
                    "INSERT INTO world_events(id, transaction_id, entity_id, event_type, ordinal, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (event_id, transaction_id, entity_id, event_type, event_ordinal, json.dumps(payload), now),
                )
                if event_type == "weather.proposed":
                    connection.execute(
                        "INSERT OR IGNORE INTO weather_proposals(id,project_id,name,description,tags_json,image_tags_json,transitions_json,source_story_node_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (payload["proposal_id"], project_id, payload["name"], payload.get("description", ""), json.dumps(payload.get("tags", [])), json.dumps(payload.get("image_tags", [])), json.dumps(payload.get("transition_ids", [])), story_node_id, now, now),
                    )
            for entity_id in affected:
                entity = final["entities"].get(entity_id)
                if not entity:
                    continue
                connection.execute(
                    "UPDATE world_entities SET canonical_name = ?, aliases_json = ?, tags_json = ? WHERE id = ?",
                    (entity["name"], json.dumps(entity.get("aliases", [])), json.dumps(entity.get("tags", [])), entity_id),
                )
                card, version_id = make_lore_card(entity, final), new_id()
                connection.execute(
                    "INSERT INTO lore_card_versions(id, entity_id, transaction_id, state_json, compact_text, visual_description, image_tags_json, search_text, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (version_id, entity_id, transaction_id, json.dumps(entity["state"]), card["compact_text"],
                     card["visual_description"], json.dumps(card["image_tags"]), card["search_text"], now),
                )
                connection.execute(
                    "INSERT INTO lore_card_search(entity_id, project_id, version_id, search_text) VALUES (?, ?, ?, ?)",
                    (entity_id, project_id, version_id, card["search_text"]),
                )
            if story_node_id:
                connection.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (story_node_id, now, project_id))
                for minigame_session_id in (assistant or {}).get("minigame_session_ids", []):
                    connection.execute(
                        "UPDATE minigame_sessions SET status='committed',story_node_id=?,committed_at=?,updated_at=? WHERE id=? AND status IN ('resolved','committed')",
                        (story_node_id, now, now, minigame_session_id),
                    )
            else:
                connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
            connection.execute("DELETE FROM world_projection_cache WHERE project_id = ?", (project_id,))
        node = self.db.fetch_one("SELECT * FROM story_nodes WHERE id = ?", (story_node_id,)) if story_node_id else {}
        transaction = self.db.fetch_one("SELECT * FROM world_transactions WHERE id = ?", (transaction_id,)) or {}
        return node or {}, transaction

    def effective_stats(self, project_id: str, container: dict[str, Any], scope: str = "character") -> dict[str, float]:
        definitions = self.db.fetch_all("SELECT * FROM stat_definitions WHERE project_id = ? AND scope = ?", (project_id, scope))
        values: dict[str, float] = {row["stat_key"]: max(float(row["minimum"]), min(float(row["maximum"]), container.get("stats", {}).get(row["stat_key"], row["default_value"]))) for row in definitions}
        by_key = {row["stat_key"]: row for row in definitions}
        for effect in container.get("active_effects", []):
            key = effect.get("stat_key")
            if key not in values: continue
            operation, amount = effect.get("operation", "add"), float(effect.get("amount", 0))
            values[key] = amount if operation == "set" else values[key] + amount * (1 if operation == "add" else -1)
            values[key] = max(float(by_key[key]["minimum"]), min(float(by_key[key]["maximum"]), values[key]))
            if by_key[key]["integer_only"]: values[key] = int(round(values[key]))
        return values

    def _validate_projection(self, projection: dict[str, Any]) -> None:
        entities = projection["entities"]
        for entity in entities.values():
            state = entity.get("state", {})
            if entity["kind"] == "character":
                for entry in state.get("inventory", []):
                    item_id, quantity = entry.get("item_id"), entry.get("quantity")
                    if item_id not in entities or entities[item_id]["kind"] != "item":
                        raise WorldValidationError(f"{entity['name']} inventory references an invalid item")
                    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
                        raise WorldValidationError(f"{entity['name']} inventory quantity must be a nonnegative integer")
            for field in ("current_location_id", "parent_location_id"):
                reference = state.get(field)
                if reference and (reference not in entities or entities[reference]["kind"] != "location"):
                    raise WorldValidationError(f"{entity['name']} has an invalid {field}: {reference}")
            outfit_id = state.get("active_outfit_id")
            if outfit_id and not self.db.fetch_one("SELECT id FROM entity_outfits WHERE id = ? AND entity_id = ?", (outfit_id, entity["id"])):
                raise WorldValidationError(f"{entity['name']} has an invalid active outfit")
        for location in (item for item in entities.values() if item["kind"] == "location"):
            exposure = location.get("state", {}).get("exposure", "outdoor")
            if exposure not in {"indoor", "outdoor", "isolated"}:
                raise WorldValidationError(f"{location['name']} has an invalid exposure")
            visited = {location["id"]}
            parent = location.get("state", {}).get("parent_location_id")
            while parent:
                if parent in visited:
                    raise WorldValidationError(f"Location containment cycle involving {location['name']}")
                visited.add(parent)
                parent = entities[parent].get("state", {}).get("parent_location_id")

    def entity_card(self, project_id: str, entity_id: str, head_node_id: str | None = None) -> dict[str, Any]:
        projection = self.projection(project_id, head_node_id)
        entity = self._entity(projection, entity_id)
        return {**entity, "card": make_lore_card(entity, projection)}

    def visible(
        self, entity: dict[str, Any], pov_character_id: str | None, narration_mode: str,
        projection: dict[str, Any] | None = None,
    ) -> bool:
        if entity.get("state", {}).get("archived"):
            return False
        if narration_mode == "third_omniscient":
            return True
        visibility = entity.get("state", {}).get("visibility", "public")
        if visibility == "public":
            return True
        if not pov_character_id:
            return False
        state = entity.get("state", {})
        if state.get("revealed") or pov_character_id in state.get("known_character_ids", []):
            return True
        if projection:
            pov = projection["entities"].get(pov_character_id, {})
            memberships = set(pov.get("state", {}).get("faction_ids", []))
            return bool(memberships.intersection(state.get("known_faction_ids", [])))
        return False

    def search(
        self, project_id: str, query: str, *, head_node_id: str | None = None,
        pov_character_id: str | None = None, narration_mode: str = "third_limited", kinds: list[str] | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        projection = self.projection(project_id, head_node_id)
        terms = {term.casefold() for term in re.findall(r"[\w'-]+", query) if len(term) > 1}
        scored: list[tuple[int, int, str, dict[str, Any]]] = []
        for entity in projection["entities"].values():
            if kinds and entity["kind"] not in kinds or not self.visible(entity, pov_character_id, narration_mode, projection):
                continue
            if entity.get("kind") == "location" and not self._location_enabled(projection, entity.get("id")):
                continue
            card = make_lore_card(entity, projection)
            haystack = card["search_text"].casefold()
            score = sum(20 if term in entity["name"].casefold() else 5 for term in terms if term in haystack)
            if not terms or score:
                scored.append((-score, -int(entity.get("last_changed_sequence", 0)), entity["name"].casefold(), {**entity, "card": card, "score": score}))
        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[3] for item in scored[: max(1, min(limit, 50))]]

    def nearby(
        self, project_id: str, origin_id: str, *, head_node_id: str | None = None,
        direction: str | None = None, limit: int = 12,
    ) -> list[dict[str, Any]]:
        projection = self.projection(project_id, head_node_id)
        origin = self._entity(projection, origin_id, "location")
        origin_state = origin.get("state", {})
        ox, oy, parent = float(origin_state.get("x", 0)), float(origin_state.get("y", 0)), origin_state.get("parent_location_id")
        vectors = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}
        vector = vectors.get(direction or "")
        results = []
        for entity in projection["entities"].values():
            state = entity.get("state", {})
            if entity["kind"] != "location" or entity["id"] == origin_id or state.get("parent_location_id") != parent:
                continue
            if not self._location_enabled(projection, entity["id"]):
                continue
            dx, dy = float(state.get("x", 0)) - ox, float(state.get("y", 0)) - oy
            distance = math.hypot(dx, dy)
            if vector and (distance == 0 or (dx * vector[0] + dy * vector[1]) / distance < 0.5):
                continue
            results.append({"id": entity["id"], "name": entity["name"], "distance": distance, "bearing": self._bearing(dx, dy)})
        return sorted(results, key=lambda item: (item["distance"], item["name"]))[:limit]

    @staticmethod
    def _bearing(dx: float, dy: float) -> str:
        if abs(dx) > abs(dy):
            return "east" if dx > 0 else "west"
        return "north" if dy >= 0 else "south"

    def route(
        self, project_id: str, source_id: str, target_id: str, *, head_node_id: str | None = None, mode: str | None = None
    ) -> dict[str, Any] | None:
        projection = self.projection(project_id, head_node_id)
        self._entity(projection, source_id, "location")
        self._entity(projection, target_id, "location")
        return self._path(projection, source_id, target_id, mode)

    def context_package(
        self, project_id: str, head_node_id: str | None, user_text: str, pov_character_id: str | None,
        narration_mode: str, token_budget: int, semantic_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        projection = self.projection(project_id, head_node_id)
        pinned: list[dict[str, Any]] = []
        pinned_ids: set[str] = set()
        if pov_character_id and pov_character_id in projection["entities"]:
            pov = projection["entities"][pov_character_id]
            pinned.append({**pov, "card": make_lore_card(pov, projection), "reason": "point_of_view"})
            pinned_ids.add(pov_character_id)
            location_id = pov.get("state", {}).get("current_location_id")
            if location_id in projection["entities"]:
                location = projection["entities"][location_id]
                pinned.append({**location, "card": make_lore_card(location, projection), "reason": "current_location"})
                pinned_ids.add(location_id)
            for entity in projection["entities"].values():
                if entity["kind"] == "character" and entity.get("state", {}).get("current_location_id") == location_id and entity["id"] not in pinned_ids:
                    if self.visible(entity, pov_character_id, narration_mode, projection):
                        pinned.append({**entity, "card": make_lore_card(entity, projection), "reason": "present"})
                        pinned_ids.add(entity["id"])
        candidates = self.search(project_id, user_text, head_node_id=head_node_id, pov_character_id=pov_character_id,
                                 narration_mode=narration_mode, limit=30)
        graph_neighbors: list[dict[str, Any]] = []
        neighbor_ids: set[str] = set()
        for relation in projection["relations"].values():
            source, target = relation.get("source_id"), relation.get("target_id")
            neighbor = target if source in pinned_ids else source if target in pinned_ids else None
            entity = projection["entities"].get(neighbor)
            if entity and neighbor not in pinned_ids and neighbor not in neighbor_ids and self.visible(entity, pov_character_id, narration_mode, projection):
                graph_neighbors.append({**entity, "card": make_lore_card(entity, projection), "reason": "graph_distance_1"})
                neighbor_ids.add(neighbor)
        graph_neighbors.sort(key=lambda item: item["name"].casefold())
        active_plots = [
            {**entity, "card": make_lore_card(entity, projection), "reason": "active_plot"}
            for entity in projection["entities"].values()
            if entity["kind"] == "plot_beat"
            and entity.get("state", {}).get("status", "available") in {"available", "active"}
            and self.visible(entity, pov_character_id, narration_mode, projection)
        ]
        active_plots.sort(key=lambda item: item["name"].casefold())
        semantic = []
        for entity_id in semantic_ids or []:
            entity = projection["entities"].get(entity_id)
            if entity and entity_id not in pinned_ids and self.visible(entity, pov_character_id, narration_mode, projection):
                semantic.append({**entity, "card": make_lore_card(entity, projection), "reason": "semantic"})
        selected, used = [], 0
        ranked = [
            *pinned,
            *[{**item, "reason": "explicit_reference_or_tag"} for item in candidates if item["id"] not in pinned_ids],
            *graph_neighbors,
            *active_plots,
            *semantic,
        ]
        seen: set[str] = set()
        for entity in ranked:
            if entity["id"] in seen:
                continue
            seen.add(entity["id"])
            cost = max(1, len(entity["card"]["compact_text"]) // 4)
            if selected and used + cost > token_budget:
                continue
            selected.append(entity)
            used += cost
        result = {
            "world_time": {"elapsed_minutes": projection["elapsed_minutes"], "display_time": projection["display_time"]},
            "pov_character_id": pov_character_id, "narration_mode": narration_mode,
            "entities": selected, "tokens_estimated": used,
        }
        # Keep private character knowledge out of lore cards/search. The prose
        # narrator receives only secrets it is explicitly allowed to know.
        narrative_secrets = []
        for entity in selected:
            if entity.get("kind") != "character":
                continue
            state = entity.get("state", {})
            for secret in state.get("secrets_to_character", []) if isinstance(state.get("secrets_to_character"), list) else []:
                if str(secret).strip():
                    narrative_secrets.append({"character_id": entity["id"], "character_name": entity["name"], "secret": str(secret), "known_to_character": False})
            if narration_mode == "third_omniscient":
                for secret in state.get("character_secrets", []) if isinstance(state.get("character_secrets"), list) else []:
                    if str(secret).strip():
                        narrative_secrets.append({"character_id": entity["id"], "character_name": entity["name"], "secret": str(secret), "known_to_character": True})
        if narrative_secrets:
            result["narrative_secrets"] = narrative_secrets[:40]
        result["entities"] = [
            {
                **entity,
                "state": {
                    key: value for key, value in entity.get("state", {}).items()
                    if key not in {"character_secrets", "secrets_to_character"}
                },
            }
            if entity.get("kind") == "character" else entity
            for entity in selected
        ]
        settings = self.db.fetch_one("SELECT enabled FROM project_environment_settings WHERE project_id=?", (project_id,))
        if settings and settings["enabled"]:
            from app.services.environment import EnvironmentService
            scene = EnvironmentService(self.db).scene(project_id, projection)
            result["environment"] = {key: scene.get(key) for key in ("focused_character", "player_action", "location", "weather", "time_phase", "allowed_next_weather")}
        return result

    def execute_read_tool(
        self, project_id: str, head_node_id: str | None, pov_character_id: str | None,
        narration_mode: str, tool: str, arguments: dict[str, Any],
    ) -> Any:
        if tool not in READ_TOOLS:
            raise WorldValidationError(f"Unsupported read tool: {tool}")
        if tool == "searchEntities":
            return self.search(project_id, str(arguments.get("query", "")), head_node_id=head_node_id,
                               pov_character_id=pov_character_id, narration_mode=narration_mode,
                               kinds=arguments.get("kinds"), limit=int(arguments.get("limit", 8)))
        if tool == "getEntity":
            card = self.entity_card(project_id, str(arguments.get("entity_id")), head_node_id)
            if not self.visible(card, pov_character_id, narration_mode, self.projection(project_id, head_node_id)):
                raise WorldValidationError("That entity is outside the current knowledge scope")
            return card
        if tool == "getScene":
            return self.context_package(project_id, head_node_id, "", pov_character_id, narration_mode, 1800)
        if tool == "getNearbyLocations":
            return self.nearby(project_id, str(arguments.get("origin_id")), head_node_id=head_node_id,
                               direction=arguments.get("direction"), limit=int(arguments.get("limit", 8)))
        if tool == "findRoute":
            return self.route(project_id, str(arguments.get("source_id")), str(arguments.get("target_id")),
                              head_node_id=head_node_id, mode=arguments.get("mode"))
        if tool in {"searchLocations", "getLocationMap", "getSceneEnvironment"}:
            from app.services.environment import EnvironmentService
            environment = EnvironmentService(self.db)
            projection = self.projection(project_id, head_node_id)
            if tool == "getSceneEnvironment":
                scene = environment.scene(project_id, projection)
                return {key: scene.get(key) for key in ("focused_character", "player_action", "location", "weather", "time_phase", "allowed_next_weather")}
            if tool == "getLocationMap":
                focus, location = environment._location(projection)
                parent_id = arguments.get("parent_id")
                if parent_id is None and location:
                    parent_id = location.get("state", {}).get("parent_location_id")
                layer = environment.map_layer(project_id, projection, str(parent_id) if parent_id else None, admin=True)
                current_parent = (location or {}).get("id")
                layer["locations"] = [
                    item for item in layer["locations"]
                    if self._location_enabled(projection, item["id"])
                    and (not projection["entities"][item["id"]].get("state", {}).get("random_encounter") or parent_id == current_parent)
                ]
                visible_ids = {item["id"] for item in layer["locations"]}
                layer["routes"] = [edge for edge in layer["routes"] if edge["source_id"] in visible_ids and edge["target_id"] in visible_ids]
                return layer
            query = str(arguments.get("query") or "").casefold()
            limit = min(20, max(1, int(arguments.get("limit", 8))))
            cursor = max(0, int(arguments.get("cursor", 0)))
            _, current_location = environment._location(projection)
            matches = []
            for entity in projection["entities"].values():
                if entity.get("kind") != "location" or entity.get("state", {}).get("archived") or not self._location_enabled(projection, entity.get("id")):
                    continue
                state = entity.get("state", {})
                if state.get("random_encounter") and state.get("parent_location_id") != (current_location or {}).get("id"):
                    continue
                haystack = " ".join([entity["name"], *entity.get("aliases", []), *entity.get("tags", [])]).casefold()
                if query and query not in haystack:
                    continue
                matches.append({"id": entity["id"], "name": entity["name"], "parent_location_id": state.get("parent_location_id"), "tags": entity.get("tags", []), "exposure": state.get("exposure", "outdoor")})
            matches.sort(key=lambda item: item["name"].casefold())
            page = matches[cursor:cursor + limit]
            return {"items": page, "next_cursor": cursor + limit if cursor + limit < len(matches) else None}
        if tool == "getStats":
            entity = self._entity(self.projection(project_id, head_node_id), arguments.get("entity_id"), "character")
            return self.effective_stats(project_id, entity)
        if tool == "getAbilities":
            return self.db.fetch_all("SELECT ability_key, name, description, target_type, costs_json, effects_json FROM ability_definitions WHERE project_id = ?", (project_id,))
        kind = "fact" if tool == "getKnownFacts" else "plot_beat"
        return self.search(project_id, str(arguments.get("query", "")), head_node_id=head_node_id,
                           pov_character_id=pov_character_id, narration_mode=narration_mode, kinds=[kind], limit=12)
