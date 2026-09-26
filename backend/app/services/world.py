from __future__ import annotations

import copy
import heapq
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.database import Database, new_id, utc_now
from app.data.dataProvider import DataProvider
from app.domain.adapters import (
    entity_from_projection,
)
from app.domain.operations import DomainOperationError
from app.domain.world import Character, TypedWorldEntity
from app.services.rule_events import RuleEventProjector
from app.services.rules import RulesRuntime, RulesRuntimeError


ENTITY_KINDS = {"character", "location", "faction", "item", "lore_system", "fact", "relationship", "plot_beat"}
NARRATION_MODES = {"first_person", "third_limited", "third_omniscient"}
READ_TOOLS = {
    "searchEntities", "getEntity", "getScene", "getNearbyLocations", "findRoute", "getKnownFacts", "getActivePlotBeats",
    "getStats", "getAbilities", "searchLocations", "getLocationMap", "getSceneEnvironment",
    "getLocalMap", "getTravelOptions", "previewTravel", "getTravelStatus",
    "getSpatialPresets",
}
WRITE_TOOLS = {
    "createEntity", "updateEntity", "moveCharacter", "setRelationship", "revealKnowledge", "advanceTime", "updatePlotBeat",
    "removeRelationship", "adjustStat", "useAbility", "applyEffect", "removeEffect", "selectTheme",
    "adjustInventory", "setSceneEnvironment", "proposeWeather", "playNoise",
    "setWorldRoot", "upsertMapAnchor", "upsertBarrier", "upsertTravelConnection", "upsertEncounterRule",
    "setMapDiscovery", "travelTo", "travelTowards", "exploreFor", "resumeTravel",
    "createLocationFromPreset",
    "editMapGeometry",
    "removeMapObject",
    # Spatial V3 authoring is branch-authoritative but intentionally not exposed
    # to AI tool schemas yet. normalize_mutations additionally rejects AI/storyteller
    # provenance for these tools until the V3 runtime/editor is stable.
    "upsertSpatialV3Space", "removeSpatialV3Space",
    "upsertSpatialV3Feature", "removeSpatialV3Feature",
    "upsertSpatialV3Encounter", "removeSpatialV3Encounter",
    "updateSpatialV3Layer",
    "bindSpatialV3LocationSpace", "unbindSpatialV3LocationSpace",
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
    compact = ". ".join(pieces)[:2400]
    primary_visual = (
        _text(state.get("imagegen_description")).strip()
        or _text(state.get("appearance")).strip()
    )
    supporting_visual_fields = ["wardrobe_notes", "wardrobe", "equipment"]
    visual_parts = [
        primary_visual,
        *[_text(state.get(field)) for field in supporting_visual_fields],
    ]
    visual = f"{name}: " + "; ".join(part for part in visual_parts if part) if any(visual_parts) else ""
    visual_tag_texts = [primary_visual, *[_text(state.get(field)) for field in supporting_visual_fields]]
    tags = list(dict.fromkeys([
        *entity.get("tags", []),
        *[item.strip() for text in visual_tag_texts for item in text.split(",") if item.strip()],
    ]))[:80]
    search = " ".join([name, *entity.get("aliases", []), *entity.get("tags", []), compact])
    return {"compact_text": compact, "visual_description": visual[:1600], "image_tags": tags, "search_text": search[:8000]}


class WorldEngine:
    def __init__(
        self,
        db: Database,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.world
        self.rules_runtime = RulesRuntime(self.data, self.apply_event)

    def _spatial_projection(self, project_id: str, projection: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(projection)
        settings = self.db.fetch_one("SELECT perception_stat_key FROM project_environment_settings WHERE project_id=?", (project_id,)) or {}
        weather = self.db.fetch_one("SELECT visibility_multiplier FROM weather_definitions WHERE id=? AND project_id=?", (projection.get("current_weather_id"), project_id)) or {"visibility_multiplier": 1}
        phases = self.db.fetch_all("SELECT id,duration_minutes,visibility_multiplier FROM time_phases WHERE project_id=? AND enabled=1 ORDER BY position", (project_id,))
        phase_multiplier = 1.0
        total = sum(int(item["duration_minutes"]) for item in phases)
        if total:
            offset = int(projection.get("elapsed_minutes", 0)) % total
            for phase in phases:
                if offset < int(phase["duration_minutes"]):
                    phase_multiplier = float(phase.get("visibility_multiplier", 1))
                    enriched["current_time_phase_id"] = phase["id"]
                    break
                offset -= int(phase["duration_minutes"])
        enriched["spatial_visibility"] = {
            "weather_multiplier": float(weather.get("visibility_multiplier", 1)),
            "time_multiplier": phase_multiplier,
            "perception_stat_key": settings.get("perception_stat_key"),
        }
        return enriched

    def projection(self, project_id: str, head_node_id: str | None = None, *, use_cache: bool = True) -> dict[str, Any]:
        if head_node_id is None:
            project = self.db.get_project(project_id) or {}
            head_node_id = project.get("active_node_id")
        cache_key = f"{project_id}:{head_node_id or 'root'}"
        if use_cache:
            cached = self.repo.cached_projection(cache_key)
            if cached:
                cached.setdefault("spatial_v3", {
                    "spaces": {},
                    "features": {},
                    "encounter_policies": {},
                    "layers": {},
                    "location_space_bindings": {},
                })
                return cached
        ancestry = {node["id"] for node in self.db.story_path(head_node_id)} if head_node_id else set()
        transactions = self.repo.committed_transactions(project_id)
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
            "root_location_id": None,
            "map_anchors": {},
            "map_barriers": {},
            "travel_connections": {},
            "encounter_rules": {},
            "travel_itineraries": {},
            "spatial_v3": {
                "spaces": {},
                "features": {},
                "encounter_policies": {},
                "layers": {},
                "location_space_bindings": {},
            },
            "active_effects": {},
            "world_action_count": 0,
            "target_action_counts": {},
            "transactions": [],
        }
        for transaction in visible:
            events = self.repo.transaction_events(transaction["id"])
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
        self.repo.store_projection(
            cache_key=cache_key,
            project_id=project_id,
            head_node_id=head_node_id,
            projection=projection,
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
            state = entities[entity_id].setdefault("state", {})
            changed_location = state.get("current_location_id") != payload["destination_id"]
            state["current_location_id"] = payload["destination_id"]
            if changed_location and "x" not in payload:
                state["current_x"] = None
                state["current_y"] = None
            if "x" in payload:
                state["current_x"] = payload.get("x")
            if "y" in payload:
                state["current_y"] = payload.get("y")
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
        elif RuleEventProjector.apply(projection, event_type, payload, entity_id):
            pass
        elif event_type == "theme.selected":
            projection["current_theme_id"] = payload.get("theme_id")
        elif event_type == "environment.scene_set":
            projection["focused_character_id"] = payload.get("focused_character_id")
            projection["player_action"] = payload.get("player_action", "standing")
            if payload.get("weather_id"):
                projection["current_weather_id"] = payload["weather_id"]
        elif event_type == "world.root_set":
            previous = projection.get("root_location_id")
            projection["root_location_id"] = payload["root_location_id"]
            entities[payload["root_location_id"]].setdefault("state", {})["parent_location_id"] = None
            for location_id in payload.get("reparent_location_ids", []):
                if location_id in entities and location_id != payload["root_location_id"]:
                    entities[location_id].setdefault("state", {})["parent_location_id"] = payload["root_location_id"]
            if payload.get("reparent_previous") and previous and previous != payload["root_location_id"]:
                entities[previous].setdefault("state", {})["parent_location_id"] = payload["root_location_id"]
        elif event_type == "map.anchor_upserted":
            projection["map_anchors"][payload["id"]] = copy.deepcopy(payload)
        elif event_type == "map.barrier_upserted":
            projection["map_barriers"][payload["id"]] = copy.deepcopy(payload)
        elif event_type == "map.connection_upserted":
            projection["travel_connections"][payload["id"]] = copy.deepcopy(payload)
        elif event_type == "map.encounter_upserted":
            projection["encounter_rules"][payload["id"]] = copy.deepcopy(payload)
        elif event_type == "map.discovery_set":
            collection = projection.get(payload.get("collection"), {})
            if payload.get("id") in collection:
                if payload.get("collection") == "entities":
                    collection[payload["id"]].setdefault("state", {})["discovered"] = bool(payload.get("discovered"))
                else:
                    collection[payload["id"]]["discovered"] = bool(payload.get("discovered"))
        elif event_type == "map.object_removed":
            projection.get(payload.get("collection"), {}).pop(payload.get("id"), None)
        elif event_type.startswith("spatial_v3."):
            spatial_v3 = projection.setdefault("spatial_v3", {
                "spaces": {},
                "features": {},
                "encounter_policies": {},
                "layers": {},
                "location_space_bindings": {},
            })
            if event_type == "spatial_v3.space_upserted":
                spatial_v3["spaces"][payload["id"]] = copy.deepcopy(payload)
            elif event_type == "spatial_v3.space_removed":
                space_id = str(payload["id"])
                spatial_v3["spaces"].pop(space_id, None)
                removed_features = {
                    feature_id
                    for feature_id, feature in list(spatial_v3["features"].items())
                    if feature.get("navigation_space_id") == space_id
                    or (
                        feature.get("feature_kind") == "connector"
                        and (
                            feature.get("properties", {}).get("source", {}).get("navigation_space_id") == space_id
                            or feature.get("properties", {}).get("target", {}).get("navigation_space_id") == space_id
                        )
                    )
                }
                for feature_id in removed_features:
                    spatial_v3["features"].pop(feature_id, None)
                for policy_id, policy in list(spatial_v3["encounter_policies"].items()):
                    if policy.get("navigation_space_id") == space_id or policy.get("feature_id") in removed_features:
                        spatial_v3["encounter_policies"].pop(policy_id, None)
                for layer_id, layer in list(spatial_v3["layers"].items()):
                    if layer.get("navigation_space_id") == space_id:
                        spatial_v3["layers"].pop(layer_id, None)
                for location_id, binding in list(spatial_v3["location_space_bindings"].items()):
                    if binding.get("navigation_space_id") == space_id:
                        spatial_v3["location_space_bindings"].pop(location_id, None)
            elif event_type == "spatial_v3.feature_upserted":
                spatial_v3["features"][payload["id"]] = copy.deepcopy(payload)
            elif event_type == "spatial_v3.feature_removed":
                feature_id = str(payload["id"])
                spatial_v3["features"].pop(feature_id, None)
                for policy_id, policy in list(spatial_v3["encounter_policies"].items()):
                    if policy.get("feature_id") == feature_id:
                        spatial_v3["encounter_policies"].pop(policy_id, None)
            elif event_type == "spatial_v3.encounter_upserted":
                spatial_v3["encounter_policies"][payload["id"]] = copy.deepcopy(payload)
            elif event_type == "spatial_v3.encounter_removed":
                spatial_v3["encounter_policies"].pop(str(payload["id"]), None)
            elif event_type == "spatial_v3.layer_updated":
                layer_id = f"{payload['navigation_space_id']}:{payload['layer_key']}"
                spatial_v3["layers"][layer_id] = copy.deepcopy(payload)
            elif event_type == "spatial_v3.location_space_bound":
                spatial_v3["location_space_bindings"][payload["location_id"]] = copy.deepcopy(payload)
            elif event_type == "spatial_v3.location_space_unbound":
                spatial_v3["location_space_bindings"].pop(str(payload["location_id"]), None)
        elif event_type == "travel.itinerary_set":
            projection["travel_itineraries"][payload["id"]] = copy.deepcopy(payload)

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
            if tool.startswith(("upsertSpatialV3", "removeSpatialV3", "updateSpatialV3", "bindSpatialV3", "unbindSpatialV3")):
                if provenance in {"ai", "storyteller_inline"}:
                    raise WorldValidationError("Spatial V3 authoring is not exposed to AI/storyteller mutations yet")
                from app.domain.spatial_v3 import (
                    EncounterPolicy,
                    LocationNavigationSpace,
                    MapFeature,
                    NavigationLayer,
                    NavigationSpace,
                )
                try:
                    if tool == "upsertSpatialV3Space":
                        model = NavigationSpace.model_validate(arguments)
                        if model.project_id != project_id:
                            raise WorldValidationError("Spatial V3 space belongs to another project")
                        arguments = model.model_dump(mode="json")
                    elif tool == "upsertSpatialV3Feature":
                        model = MapFeature.model_validate(arguments)
                        if model.project_id != project_id:
                            raise WorldValidationError("Spatial V3 feature belongs to another project")
                        arguments = model.model_dump(mode="json")
                    elif tool == "upsertSpatialV3Encounter":
                        model = EncounterPolicy.model_validate(arguments)
                        if model.project_id != project_id:
                            raise WorldValidationError("Spatial V3 encounter belongs to another project")
                        arguments = model.model_dump(mode="json")
                    elif tool == "updateSpatialV3Layer":
                        arguments = NavigationLayer.model_validate(arguments).model_dump(mode="json")
                    elif tool == "bindSpatialV3LocationSpace":
                        model = LocationNavigationSpace.model_validate(arguments)
                        if model.project_id != project_id:
                            raise WorldValidationError("Spatial V3 binding belongs to another project")
                        arguments = model.model_dump(mode="json")
                    elif tool in {"removeSpatialV3Space", "removeSpatialV3Feature", "removeSpatialV3Encounter"}:
                        object_id = str(arguments.get("id") or "").strip()
                        if not object_id:
                            raise WorldValidationError(f"{tool} requires id")
                        arguments = {"id": object_id}
                    elif tool == "unbindSpatialV3LocationSpace":
                        location_id = str(arguments.get("location_id") or "").strip()
                        if not location_id:
                            raise WorldValidationError("unbindSpatialV3LocationSpace requires location_id")
                        arguments = {"location_id": location_id}
                except WorldValidationError:
                    raise
                except ValueError as exc:
                    raise WorldValidationError(f"Invalid Spatial V3 mutation: {exc}") from exc
                mutation = NormalizedMutation(tool, arguments, False)
                normalized.append(mutation)
                self._apply_mutation_preview(projection, mutation)
                continue

            major, reason = False, None
            if tool == "upsertSpatialV3Space":
            return [("spatial_v3.space_upserted", None, args)]
        if tool == "removeSpatialV3Space":
            return [("spatial_v3.space_removed", None, args)]
        if tool == "upsertSpatialV3Feature":
            return [("spatial_v3.feature_upserted", None, args)]
        if tool == "removeSpatialV3Feature":
            return [("spatial_v3.feature_removed", None, args)]
        if tool == "upsertSpatialV3Encounter":
            return [("spatial_v3.encounter_upserted", None, args)]
        if tool == "removeSpatialV3Encounter":
            return [("spatial_v3.encounter_removed", None, args)]
        if tool == "updateSpatialV3Layer":
            return [("spatial_v3.layer_updated", None, args)]
        if tool == "bindSpatialV3LocationSpace":
            return [("spatial_v3.location_space_bound", None, args)]
        if tool == "unbindSpatialV3LocationSpace":
            return [("spatial_v3.location_space_unbound", None, args)]
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
                if provenance != "clone":
                    arguments.pop("stats", None)
                    arguments.pop("active_effects", None)
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
                    try:
                        from app.domain.world import LocationState
                        from app.services.spatial import validate_geometry
                        if location_state.get("footprint"):
                            location_state["footprint"].setdefault("location_id", location_state.get("parent_location_id") or entity_id)
                        if location_state.get("local_bounds"):
                            location_state["local_bounds"].setdefault("location_id", entity_id)
                        LocationState.model_validate(location_state)
                        for geometry_field in ("footprint", "local_bounds"):
                            if location_state.get(geometry_field):
                                validate_geometry(location_state[geometry_field])
                    except ValueError as exc:
                        raise WorldValidationError(f"Invalid location state: {exc}") from exc
                names.add(name.casefold())
                if kind == "lore_system" and provenance == "ai":
                    major, reason = True, "Creates a new world-rule system"
            elif tool == "createLocationFromPreset":
                from app.services.spatialPresets import SPATIAL_PRESETS
                from app.domain.world import LocationState
                preset_key = str(arguments.get("preset") or "")
                preset = SPATIAL_PRESETS.get(preset_key)
                if not preset or preset.get("object") != "location":
                    raise WorldValidationError("Unknown location preset")
                name = str(arguments.get("name") or "").strip()
                if not name or name.casefold() in names:
                    raise WorldValidationError("Location preset creation requires a unique non-empty name")
                state = {**preset.get("state", {}), **(arguments.get("overrides") or {})}
                state.setdefault("description", "")
                state.setdefault("imagegen_description", "")
                state.setdefault("image_tags", [])
                state.setdefault("enabled", True)
                state.setdefault("random_encounter", False)
                state.setdefault("discovered", True)
                settings = self.db.fetch_one("SELECT enabled,ai_create_locations FROM project_environment_settings WHERE project_id=?", (project_id,))
                if provenance in {"ai", "storyteller_inline"} and settings and (not settings["enabled"] or not settings["ai_create_locations"]):
                    raise WorldValidationError("AI location creation is disabled for this story")
                try:
                    LocationState.model_validate(state)
                except ValueError as exc:
                    raise WorldValidationError(f"Invalid location preset overrides: {exc}") from exc
                arguments = {
                    "entity_id": str(arguments.get("entity_id") or new_id()), "kind": "location", "name": name,
                    "aliases": list(dict.fromkeys(arguments.get("aliases", []))), "tags": list(dict.fromkeys(arguments.get("tags", []))),
                    "state": state, "preset": preset_key,
                }
                names.add(name.casefold())
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
                if entity["kind"] == "location":
                    try:
                        from app.domain.world import LocationState
                        from app.services.spatial import validate_geometry
                        if patch.get("footprint"):
                            patch["footprint"].setdefault("location_id", patch.get("parent_location_id", entity.get("state", {}).get("parent_location_id")) or entity["id"])
                        if patch.get("local_bounds"):
                            patch["local_bounds"].setdefault("location_id", entity["id"])
                        merged_location = _deep_merge(entity.get("state", {}), patch)
                        if merged_location.get("footprint"):
                            merged_location["footprint"].setdefault("location_id", merged_location.get("parent_location_id") or entity["id"])
                        if merged_location.get("local_bounds"):
                            merged_location["local_bounds"].setdefault("location_id", entity["id"])
                        LocationState.model_validate(merged_location)
                        for geometry_field in ("footprint", "local_bounds"):
                            if merged_location.get(geometry_field):
                                validate_geometry(merged_location[geometry_field])
                    except ValueError as exc:
                        raise WorldValidationError(f"Invalid location state: {exc}") from exc
            elif tool == "moveCharacter":
                character = self._entity(projection, arguments.get("character_id"), "character")
                destination = self._entity(projection, arguments.get("destination_id"), "location")
                source_id = character.get("state", {}).get("current_location_id")
                arguments["source_id"] = source_id
                if source_id != destination["id"] and not self._location_enabled(projection, destination["id"]):
                    raise WorldValidationError(f"Location '{destination['name']}' is disabled")
                if source_id and source_id != destination["id"] and not arguments.get("bypass_reason"):
                    route = None
                    from app.services.spatial import SpatialService
                    spatial = SpatialService(self._spatial_projection(project_id, projection))
                    if spatial.root_id():
                        route = spatial.preview(character["id"], destination["id"], str(arguments.get("mode") or "walk"))
                        if not route.get("available"):
                            route = None
                    if route is None:
                        route = self._path(projection, source_id, destination["id"], arguments.get("mode"))
                    if not route:
                        raise WorldValidationError(f"No traversable route connects {source_id} to {destination['id']}")
                    arguments.setdefault("elapsed_minutes", int(route.get("travel_minutes", 0)))
                elif arguments.get("bypass_reason"):
                    abilities = _text(character.get("state", {}).get("abilities", [])).casefold()
                    if str(arguments["bypass_reason"]).casefold() not in abilities:
                        raise WorldValidationError("Movement bypass must name an ability possessed by the character")
            elif tool == "setWorldRoot":
                root = self._entity(projection, arguments.get("root_location_id"), "location")
                top_level = [
                    item["id"] for item in projection["entities"].values()
                    if item.get("kind") == "location" and item["id"] != root["id"]
                    and not item.get("state", {}).get("parent_location_id")
                ]
                arguments = {
                    "root_location_id": root["id"],
                    "reparent_previous": bool(arguments.get("reparent_previous", True)),
                    "reparent_location_ids": top_level if arguments.get("adopt_top_level", projection.get("root_location_id") is None) else [],
                }
            elif tool == "upsertMapAnchor":
                from app.domain.world import MapAnchor
                try:
                    arguments.setdefault("id", new_id())
                    owner = self._entity(projection, arguments.get("location_id"), "location")
                    coordinate_space_id = arguments.get("coordinate_space_id")
                    if not coordinate_space_id:
                        coordinate_space_id = owner.get("state", {}).get("parent_location_id") or owner["id"]
                        arguments["coordinate_space_id"] = coordinate_space_id
                    self._entity(projection, coordinate_space_id, "location")
                    binding_kind = str(arguments.get("binding_kind") or "coordinate")
                    binding_target_id = arguments.get("binding_target_id")
                    if binding_kind == "coordinate":
                        arguments["binding_target_id"] = None
                    else:
                        # Bound endpoints derive their position from their
                        # location/area geometry. Do not persist absolute x/y.
                        arguments["x"] = None
                        arguments["y"] = None
                        if not binding_target_id:
                            raise WorldValidationError("Bound map anchors require a binding_target_id")
                        target = self._entity(projection, binding_target_id, "location")
                        target_kind = target.get("state", {}).get("spatial_kind", "spot")
                        if binding_kind in {"area", "area_border"} and target_kind != "area":
                            raise WorldValidationError("Area endpoint bindings require an area target")
                        if binding_kind == "spot" and target_kind == "area":
                            raise WorldValidationError("Spot endpoint bindings require a spot target")
                        target_space = target.get("state", {}).get("parent_location_id") or target["id"]
                        if str(target_space) != str(coordinate_space_id):
                            raise WorldValidationError("Endpoint binding target must exist in the anchor coordinate space")
                        if str(binding_target_id) != str(owner["id"]):
                            raise WorldValidationError("Bound map anchor owner must match its binding target")
                    arguments = MapAnchor.model_validate(arguments).model_dump(mode="json")
                except ValueError as exc:
                    raise WorldValidationError(f"Invalid map anchor: {exc}") from exc
            elif tool == "upsertBarrier":
                from app.domain.world import Barrier
                from app.services.spatial import validate_geometry
                try:
                    arguments.setdefault("id", new_id())
                    self._entity(projection, arguments.get("location_id"), "location")
                    if arguments.get("geometry"):
                        arguments["geometry"].setdefault("location_id", arguments["location_id"])
                        arguments["geometry"] = validate_geometry(arguments["geometry"])
                    else:
                        arguments["requires_map_review"] = True
                    arguments = Barrier.model_validate(arguments).model_dump(mode="json")
                except ValueError as exc:
                    raise WorldValidationError(f"Invalid barrier: {exc}") from exc
            elif tool == "editMapGeometry":
                from app.services.spatial import validate_geometry
                barrier_id = str(arguments.get("barrier_id") or "")
                barrier = copy.deepcopy(projection.get("map_barriers", {}).get(barrier_id))
                if not barrier or not barrier.get("geometry"):
                    raise WorldValidationError("Barrier geometry is unavailable; create its initial geometry first")
                points = list(barrier["geometry"].get("points") or [])
                operation, index = str(arguments.get("operation") or ""), int(arguments.get("index", len(points)))
                point = {"x": float(arguments.get("x", 0)), "y": float(arguments.get("y", 0))}
                if operation == "add_point" and 0 <= index <= len(points): points.insert(index, point)
                elif operation == "move_point" and 0 <= index < len(points): points[index] = point
                elif operation == "remove_point" and 0 <= index < len(points): points.pop(index)
                else: raise WorldValidationError("Geometry edit operation or point index is invalid")
                barrier["geometry"]["points"] = points
                barrier["geometry"] = validate_geometry(barrier["geometry"])
                barrier["requires_map_review"] = False
                arguments = barrier
            elif tool == "upsertTravelConnection":
                from app.services.spatial import SpatialService, SpatialValidationError
                try:
                    arguments.setdefault("id", new_id())
                    arguments = SpatialService(projection).validate_connection(arguments)
                except SpatialValidationError as exc:
                    raise WorldValidationError(f"Invalid travel connection: {exc}") from exc
            elif tool == "upsertEncounterRule":
                from app.domain.world import EncounterRule
                try:
                    arguments.setdefault("id", new_id())
                    arguments = EncounterRule.model_validate(arguments).model_dump(mode="json")
                    if arguments.get("location_id"):
                        self._entity(projection, arguments["location_id"], "location")
                    if arguments.get("connection_id") not in {None, *projection.get("travel_connections", {})}:
                        raise WorldValidationError("Encounter connection is unavailable")
                    for candidate in arguments.get("candidates", []):
                        self._entity(projection, candidate["location_id"], "location")
                except ValueError as exc:
                    raise WorldValidationError(f"Invalid encounter rule: {exc}") from exc
            elif tool == "setMapDiscovery":
                collections = {
                    "anchor": "map_anchors", "barrier": "map_barriers", "connection": "travel_connections",
                    "encounter": "encounter_rules", "location": "entities",
                }
                kind = str(arguments.get("kind") or "")
                collection = collections.get(kind)
                if not collection or arguments.get("id") not in projection.get(collection, {}):
                    raise WorldValidationError("Map object is unavailable")
                if kind == "location" and projection["entities"][str(arguments["id"])].get("kind") != "location":
                    raise WorldValidationError("Map discovery target is not a location")
                arguments = {"collection": collection, "id": str(arguments["id"]), "discovered": bool(arguments.get("discovered", True))}
            elif tool == "removeMapObject":
                collections = {"anchor": "map_anchors", "barrier": "map_barriers", "connection": "travel_connections", "encounter": "encounter_rules"}
                kind = str(arguments.get("kind") or "")
                collection, object_id = collections.get(kind), str(arguments.get("id") or "")
                if not collection or object_id not in projection.get(collection, {}):
                    raise WorldValidationError("Map object is unavailable")
                if kind == "anchor" and any(object_id in {item.get("source_anchor_id"), item.get("target_anchor_id")} for item in projection.get("travel_connections", {}).values()):
                    raise WorldValidationError("Remove connections using this anchor first")
                arguments = {"collection": collection, "kind": kind, "id": object_id}
            elif tool in {"travelTo", "travelTowards", "exploreFor", "resumeTravel"}:
                from app.services.spatial import SpatialService, SpatialValidationError
                character = self._entity(projection, arguments.get("character_id"), "character")
                resolver = SpatialService(self._spatial_projection(project_id, projection))
                try:
                    if tool == "resumeTravel":
                        existing = projection.get("travel_itineraries", {}).get(str(arguments.get("itinerary_id")))
                        if not existing or existing.get("character_id") != character["id"]:
                            raise SpatialValidationError("Travel itinerary is unavailable")
                        if existing.get("status") == "completed":
                            raise SpatialValidationError("Travel itinerary is already complete")
                        interruption = existing.get("interruption") or {}
                        if interruption.get("kind") == "lock":
                            raise SpatialValidationError("Resolve the connection lock before resuming travel")
                        resolved = resolver.itinerary(
                            character["id"], existing["destination_location_id"], existing.get("mode", "walk"),
                            skip_encounter_rule_id=interruption.get("rule_id") if interruption.get("kind") == "encounter" else None,
                        )
                    elif tool == "exploreFor":
                        resolved = resolver.explore(character["id"], float(arguments.get("minutes", 0)), str(arguments.get("mode") or "walk"), arguments.get("optional_direction"))
                    else:
                        allotted = float(arguments.get("minutes", 0)) if tool == "travelTowards" else None
                        if arguments.get("x") is not None and arguments.get("y") is not None:
                            resolved = resolver.coordinate_itinerary(character["id"], float(arguments["x"]), float(arguments["y"]), str(arguments.get("mode") or "walk"), allotted)
                        else:
                            destination_id = str(arguments.get("location_id") or arguments.get("destination_id") or "")
                            self._entity(projection, destination_id, "location")
                            resolved = resolver.itinerary(character["id"], destination_id, str(arguments.get("mode") or "walk"), allotted)
                except (SpatialValidationError, ValueError) as exc:
                    raise WorldValidationError(str(exc)) from exc
                arguments = {
                    "character_id": character["id"], "destination_id": resolved["reached_location_id"],
                    "elapsed_minutes": int(math.ceil(float(resolved["elapsed_minutes"]))),
                    "itinerary": resolved["itinerary"], "discoveries": resolved.get("discoveries", []),
                }
                if "x" in resolved:
                    arguments.update({"x": resolved["x"], "y": resolved["y"]})
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
                try: arguments["scheduled_effects"] = self.rules_runtime.due_effects(project_id, projection, "story_minutes", int(projection.get("elapsed_minutes", 0)) + minutes)
                except (DomainOperationError, RulesRuntimeError) as exc: raise WorldValidationError(str(exc)) from exc
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
                try: arguments = self.rules_runtime.adjust_stat(project_id, projection, arguments)
                except (DomainOperationError, RulesRuntimeError) as exc: raise WorldValidationError(str(exc)) from exc
            elif tool == "useAbility":
                try:
                    arguments = self.rules_runtime.normalize_ability(project_id, projection, arguments, provenance)
                    arguments["scheduled_effects"] = [
                        *self.rules_runtime.due_effects(project_id, projection, "world_actions", int(projection.get("world_action_count", 0)) + 1),
                        *self.rules_runtime.due_effects(project_id, projection, "target_actions", int(projection.get("target_action_counts", {}).get(arguments["actor_id"], 0)) + 1, target_id=str(arguments["actor_id"])),
                    ]
                except (DomainOperationError, RulesRuntimeError) as exc: raise WorldValidationError(str(exc)) from exc
            elif tool == "applyEffect":
                try: arguments = self.rules_runtime.direct_effect(project_id, projection, arguments)
                except (DomainOperationError, RulesRuntimeError) as exc: raise WorldValidationError(str(exc)) from exc
            elif tool == "removeEffect":
                instance_id = str(arguments.get("active_instance_id") or "")
                if instance_id not in projection.get("active_effects", {}): raise WorldValidationError("Active effect instance not found")
                arguments = {"id": instance_id}
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
            elif tool == "playNoise":
                noise_id = str(arguments.get("noise_id") or "")
                noise = self.data.sound.noise_variant(
                    project_id,
                    noise_id,
                    playable_only=True,
                )
                if not noise:
                    raise WorldValidationError(
                        "Noise is not enabled or available for this story"
                    )
                arguments = {
                    "noise_id": noise_id,
                    "noise_label": noise["label"],
                }
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
            base_events = self._base_mutation_events(mutation)
            try:
                elapsed = sum(
                    int(payload.get("minutes", 0))
                    for event_type, _entity_id, payload in base_events
                    if event_type == "time.advanced"
                )
                scheduled_time = (
                    self.rules_runtime.due_effects(
                        project_id,
                        projection,
                        "story_minutes",
                        int(projection.get("elapsed_minutes", 0)) + elapsed,
                    )
                    if elapsed > 0 and tool != "advanceTime"
                    else []
                )
                scheduled_events = [
                    (
                        item["event_type"],
                        item.get("entity_id"),
                        {key: value for key, value in item.items() if key != "event_type"},
                    )
                    for item in scheduled_time
                ]
                rule_base_events = [*base_events, *scheduled_events]
                passive = self.rules_runtime.passive_cascade(project_id, projection, rule_base_events)
                derived = [
                    *scheduled_time,
                    *passive,
                    *self.rules_runtime.dependent_clamps(
                        project_id,
                        projection,
                        [
                            *rule_base_events,
                            *[
                                (
                                    item["event_type"],
                                    item.get("entity_id"),
                                    {key: value for key, value in item.items() if key != "event_type"},
                                )
                                for item in passive
                            ],
                        ],
                    ),
                ]
            except (DomainOperationError, RulesRuntimeError) as exc:
                raise WorldValidationError(str(exc)) from exc
            if derived:
                mutation.arguments["_derived_events"] = derived
            normalized.append(mutation)
            self._apply_mutation_preview(projection, mutation)
        return normalized

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
        spatial_v3 = projection.get("spatial_v3") or {}
        if spatial_v3:
            from app.domain.spatial_v3 import (
                EncounterPolicy,
                LocationNavigationSpace,
                MapFeature,
                NavigationLayer,
                NavigationSpace,
            )
            try:
                spaces = {
                    key: NavigationSpace.model_validate(value)
                    for key, value in spatial_v3.get("spaces", {}).items()
                }
                features = {
                    key: MapFeature.model_validate(value)
                    for key, value in spatial_v3.get("features", {}).items()
                }
                encounters = {
                    key: EncounterPolicy.model_validate(value)
                    for key, value in spatial_v3.get("encounter_policies", {}).items()
                }
                layers = [
                    NavigationLayer.model_validate(value)
                    for value in spatial_v3.get("layers", {}).values()
                ]
                bindings = [
                    LocationNavigationSpace.model_validate(value)
                    for value in spatial_v3.get("location_space_bindings", {}).values()
                ]
            except ValueError as exc:
                raise WorldValidationError(f"Invalid Spatial V3 branch state: {exc}") from exc

            for space in spaces.values():
                if space.project_id != projection["project_id"]:
                    raise WorldValidationError(f"Spatial V3 space {space.id} belongs to another project")
                if space.owner_location_id:
                    owner = entities.get(space.owner_location_id)
                    if not owner or owner.get("kind") != "location":
                        raise WorldValidationError(f"Spatial V3 space {space.id} has an invalid owner location")
            for feature in features.values():
                if feature.project_id != projection["project_id"] or feature.navigation_space_id not in spaces:
                    raise WorldValidationError(f"Spatial V3 feature {feature.id} references an invalid navigation space")
                if feature.semantic_location_id:
                    semantic = entities.get(feature.semantic_location_id)
                    if not semantic or semantic.get("kind") != "location":
                        raise WorldValidationError(f"Spatial V3 feature {feature.id} has an invalid semantic location")
                if str(feature.feature_kind) == "connector":
                    props = feature.properties
                    if props.source.navigation_space_id not in spaces or props.target.navigation_space_id not in spaces:
                        raise WorldValidationError(f"Spatial V3 connector {feature.id} references an invalid endpoint space")
            for policy in encounters.values():
                if policy.project_id != projection["project_id"]:
                    raise WorldValidationError(f"Spatial V3 encounter {policy.id} belongs to another project")
                if policy.navigation_space_id and policy.navigation_space_id not in spaces:
                    raise WorldValidationError(f"Spatial V3 encounter {policy.id} references an invalid navigation space")
                if policy.feature_id and policy.feature_id not in features:
                    raise WorldValidationError(f"Spatial V3 encounter {policy.id} references an invalid feature")
            for layer in layers:
                if layer.navigation_space_id not in spaces:
                    raise WorldValidationError("Spatial V3 layer references an invalid navigation space")
            for binding in bindings:
                if binding.navigation_space_id not in spaces:
                    raise WorldValidationError("Spatial V3 location binding references an invalid navigation space")
                location = entities.get(binding.location_id)
                if not location or location.get("kind") != "location":
                    raise WorldValidationError("Spatial V3 location binding references an invalid location")

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
        rows = WorldEngine._base_mutation_events(mutation)
        rows.extend(
            (str(item["event_type"]), item.get("entity_id"), {key: value for key, value in item.items() if key != "event_type"})
            for item in mutation.arguments.get("_derived_events", [])
        )
        return rows

    @staticmethod
    def _base_mutation_events(mutation: NormalizedMutation) -> list[tuple[str, str | None, dict[str, Any]]]:
        tool, args = mutation.tool, mutation.arguments
        rule_events = RuleEventProjector.mutation_events(tool, args)
        if rule_events is not None:
            return rule_events
        if tool == "createEntity":
            entity = {
                "id": args["entity_id"], "kind": args["kind"], "name": args["name"],
                "aliases": args.get("aliases", []), "tags": args.get("tags", []), "state": args.get("state", {}),
            }
            if "stats" in args:
                entity["stats"] = args["stats"]
            return [("entity.created", entity["id"], {"entity": entity})]
        if tool == "createLocationFromPreset":
            entity = {key: args[key] for key in ("entity_id", "kind", "name", "aliases", "tags", "state")}
            entity["id"] = entity.pop("entity_id")
            return [("entity.created", entity["id"], {"entity": entity, "preset": args.get("preset")})]
        if tool == "updateEntity":
            return [("entity.updated", args["entity_id"], {key: args[key] for key in ("patch", "name", "tags", "aliases") if key in args})]
        if tool == "moveCharacter":
            events = [("character.moved", args["character_id"], args)]
            if args.get("elapsed_minutes") or args.get("display_time"):
                events.append(("time.advanced", None, {"minutes": args.get("elapsed_minutes", 0), "display_time": args.get("display_time")}))
            return events
        if tool == "setWorldRoot":
            return [("world.root_set", args["root_location_id"], args)]
        if tool == "upsertMapAnchor":
            return [("map.anchor_upserted", None, args)]
        if tool == "upsertBarrier":
            return [("map.barrier_upserted", None, args)]
        if tool == "editMapGeometry":
            return [("map.barrier_upserted", None, args)]
        if tool == "upsertTravelConnection":
            return [("map.connection_upserted", None, args)]
        if tool == "upsertEncounterRule":
            return [("map.encounter_upserted", None, args)]
        if tool == "setMapDiscovery":
            return [("map.discovery_set", None, args)]
        if tool == "removeMapObject":
            return [("map.object_removed", None, args)]
        if tool in {"travelTo", "travelTowards", "exploreFor", "resumeTravel"}:
            events = [
                ("travel.itinerary_set", None, args["itinerary"]),
                ("character.moved", args["character_id"], {
                    "destination_id": args["destination_id"],
                    **({"x": args.get("x"), "y": args.get("y")} if "x" in args else {}),
                }),
            ]
            events.extend(
                ("map.discovery_set", None, {
                    "collection": {"barrier": "map_barriers", "anchor": "map_anchors", "connection": "travel_connections", "encounter": "encounter_rules", "location": "entities"}[item["kind"]],
                    "id": item["id"], "discovered": True,
                })
                for item in args.get("discoveries", [])
            )
            if args.get("elapsed_minutes"):
                events.append(("time.advanced", None, {"minutes": args["elapsed_minutes"]}))
            return events
        if tool == "setRelationship":
            return [("relationship.set", None, args)]
        if tool == "removeRelationship":
            return [("relationship.removed", None, args)]
        if tool == "revealKnowledge":
            return [("knowledge.revealed", args["fact_id"], args)]
        if tool == "advanceTime":
            rows = [("time.advanced", None, {key: value for key, value in args.items() if key != "scheduled_effects"})]
            rows.extend((str(item["event_type"]), item.get("entity_id"), {key: value for key, value in item.items() if key != "event_type"}) for item in args.get("scheduled_effects", []))
            return rows
        if tool == "updatePlotBeat":
            return [("plot_beat.updated", args["entity_id"], args)]
        if tool == "selectTheme":
            return [("theme.selected", None, args)]
        if tool == "playNoise":
            return [("noise.played", None, args)]
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
        if not any(item.tool == "useAbility" for item in mutations):
            projected = self.preview(project_id, parent_node_id, mutations)
            try:
                action_args = {
                    "actor_id": pov_character_id,
                    "scheduled_effects": [
                        *self.rules_runtime.due_effects(project_id, projected, "world_actions", int(projected.get("world_action_count", 0)) + 1),
                        *(self.rules_runtime.due_effects(project_id, projected, "target_actions", int(projected.get("target_action_counts", {}).get(pov_character_id, 0)) + 1, target_id=pov_character_id) if pov_character_id else []),
                    ],
                }
                action = NormalizedMutation("storyAction", action_args, False)
                base_events = self._base_mutation_events(action)
                passive = self.rules_runtime.passive_cascade(project_id, projected, base_events)
                action.arguments["_derived_events"] = [*passive, *self.rules_runtime.dependent_clamps(project_id, projected, [*base_events, *[(row["event_type"], row.get("entity_id"), {key: value for key, value in row.items() if key != "event_type"}) for row in passive]])]
            except (DomainOperationError, RulesRuntimeError) as exc:
                raise WorldValidationError(str(exc)) from exc
            mutations = [*mutations, action]
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
            minigame = self.repo.resolved_minigame(minigame_session_id)
            if not minigame or minigame.get("result") is None:
                raise WorldValidationError("Resolved minigame result is missing")
            event_rows.append((new_id(), None, "minigame.completed", {
                "session_id": minigame_session_id,
                "game_key": minigame["game_key"],
                "game_version": minigame["game_version"],
                "invocation": minigame["invocation"],
                "result": minigame["result"],
            }, ordinal))
            ordinal += 1
        self._validate_projection(final)
        transaction_id = new_id()
        branch_sequence = len(self.db.story_path(parent_node_id)) + (
            1 if story_node_id else 0
        )
        elapsed = final["elapsed_minutes"] - base["elapsed_minutes"]

        affected_entities: list[
            tuple[dict[str, Any], dict[str, Any]]
        ] = []
        for entity_id in affected:
            entity = final["entities"].get(entity_id)
            if entity:
                affected_entities.append(
                    (entity, make_lore_card(entity, final))
                )

        return self.repo.persist_commit(
            project_id=project_id,
            story_node_id=story_node_id,
            parent_node_id=parent_node_id,
            branch_sequence=branch_sequence,
            elapsed_minutes=elapsed,
            display_time=final.get("display_time"),
            provenance=provenance,
            summary=summary,
            transaction_id=transaction_id,
            event_rows=event_rows,
            new_entities=list(new_entities.values()),
            affected_entities=affected_entities,
            assistant=assistant,
        )

    def effective_stats(self, project_id: str, container: dict[str, Any], scope: str = "character") -> dict[str, float]:
        return self.rules_runtime.effective_stats(project_id, container, scope)
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
            state = location.get("state", {})
            exposure = state.get("exposure", "outdoor")
            if exposure not in {"indoor", "outdoor", "isolated"}:
                raise WorldValidationError(f"{location['name']} has an invalid exposure")
            if state.get("topology", "closed") not in {"open", "closed"}:
                raise WorldValidationError(f"{location['name']} has an invalid topology")
            if state.get("occupancy", "direct_allowed") not in {"direct_allowed", "child_required"}:
                raise WorldValidationError(f"{location['name']} has an invalid occupancy policy")
            if state.get("boundary_access", "free") not in {"free", "connection_required"}:
                raise WorldValidationError(f"{location['name']} has an invalid boundary access policy")
            visited = {location["id"]}
            parent = location.get("state", {}).get("parent_location_id")
            while parent:
                if parent in visited:
                    raise WorldValidationError(f"Location containment cycle involving {location['name']}")
                visited.add(parent)
                parent = entities[parent].get("state", {}).get("parent_location_id")
        for character in (item for item in entities.values() if item["kind"] == "character"):
            location = entities.get(character.get("state", {}).get("current_location_id"))
            if location and location.get("state", {}).get("occupancy", "direct_allowed") == "child_required":
                raise WorldValidationError(f"{character['name']} cannot directly occupy {location['name']}; a child location is required")
        for relation in projection["relations"].values():
            if relation.get("source_id") not in entities or relation.get("target_id") not in entities:
                raise WorldValidationError("Relationship references an unavailable entity")
        try:
            from app.services.spatial import SpatialService
            SpatialService(projection).validate_hierarchy()
        except ValueError as exc:
            raise WorldValidationError(str(exc)) from exc

    def entity_card(self, project_id: str, entity_id: str, head_node_id: str | None = None) -> dict[str, Any]:
        projection = self.projection(project_id, head_node_id)
        entity = self._entity(projection, entity_id)
        return {**entity, "card": make_lore_card(entity, projection)}

    def typed_entity(
        self,
        project_id: str,
        entity_id: str,
        head_node_id: str | None = None,
    ) -> TypedWorldEntity:
        """Return an opt-in typed view without changing projection storage."""
        projection = self.projection(project_id, head_node_id)
        return entity_from_projection(
            self._entity(projection, entity_id)
        )

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
        from app.services.spatial import SpatialService
        spatial = SpatialService(self._spatial_projection(project_id, projection))
        if spatial.root_id() and projection.get("travel_connections"):
            synthetic_id = "__route_preview__"
            working = copy.deepcopy(projection)
            working["entities"][synthetic_id] = {"id": synthetic_id, "kind": "character", "name": "Route preview", "tags": [], "state": {"current_location_id": source_id, "abilities": [], "inventory": []}, "stats": {}}
            result = SpatialService(self._spatial_projection(project_id, working)).preview(synthetic_id, target_id, mode or "walk")
            return result if result.get("available") else None
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
            typed_pov = entity_from_projection(pov)
            pinned.append({**pov, "card": make_lore_card(pov, projection), "reason": "point_of_view"})
            pinned_ids.add(pov_character_id)
            location_id = (
                typed_pov.state.current_location_id
                if isinstance(typed_pov, Character)
                else pov.get("state", {}).get("current_location_id")
            )
            if location_id in projection["entities"]:
                location = projection["entities"][location_id]
                pinned.append({**location, "card": make_lore_card(location, projection), "reason": "current_location"})
                pinned_ids.add(location_id)
            for entity in projection["entities"].values():
                typed_entity = entity_from_projection(entity)
                if isinstance(typed_entity, Character) and typed_entity.state.current_location_id == location_id and typed_entity.id not in pinned_ids:
                    if self.visible(entity, pov_character_id, narration_mode, projection):
                        pinned.append({**entity, "card": make_lore_card(entity, projection), "reason": "present"})
                        pinned_ids.add(typed_entity.id)
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
        scene_context: dict[str, Any] = {"actor": None, "party": [], "present_non_party": [], "interacting": []}
        if pov_character_id and pov_character_id in projection["entities"]:
            actor = projection["entities"][pov_character_id]
            actor_state = actor.get("state", {})
            location_id = actor_state.get("current_location_id")
            party_ids = {str(item) for item in actor_state.get("party_ids", [])}
            semantic_set = {str(item) for item in semantic_ids or []}
            folded_user_text = user_text.casefold()
            scene_context["actor"] = {"id": actor["id"], "name": actor["name"], "location_id": location_id}
            for entity in projection["entities"].values():
                if entity.get("kind") != "character" or entity["id"] == pov_character_id:
                    continue
                if entity.get("state", {}).get("current_location_id") != location_id:
                    continue
                summary = {"id": entity["id"], "name": entity["name"]}
                if entity["id"] in party_ids:
                    scene_context["party"].append(summary)
                elif self.visible(entity, pov_character_id, narration_mode, projection):
                    scene_context["present_non_party"].append(summary)
                    if entity["id"] in semantic_set or entity["name"].casefold() in folded_user_text:
                        scene_context["interacting"].append(summary)
            scene_context["party"].sort(key=lambda item: item["name"].casefold())
            scene_context["present_non_party"].sort(key=lambda item: item["name"].casefold())
            scene_context["interacting"].sort(key=lambda item: item["name"].casefold())
        result = {
            "world_time": {"elapsed_minutes": projection["elapsed_minutes"], "display_time": projection["display_time"]},
            "pov_character_id": pov_character_id, "narration_mode": narration_mode,
            "scene_context": scene_context,
            "entities": selected, "tokens_estimated": used,
        }
        # Keep private character knowledge out of lore cards/search. The prose
        # narrator receives only secrets it is explicitly allowed to know.
        narrative_secrets = []
        for entity in selected:
            typed_entity = entity_from_projection(entity)
            if not isinstance(typed_entity, Character):
                continue
            state = typed_entity.state
            for secret in state.secrets_to_character:
                if str(secret).strip():
                    narrative_secrets.append({"character_id": typed_entity.id, "character_name": typed_entity.name, "secret": str(secret), "known_to_character": False})
            if narration_mode == "third_omniscient":
                for secret in state.character_secrets:
                    if str(secret).strip():
                        narrative_secrets.append({"character_id": typed_entity.id, "character_name": typed_entity.name, "secret": str(secret), "known_to_character": True})
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
        if tool == "getSpatialPresets":
            from app.services.spatialPresets import public_spatial_presets
            return public_spatial_presets()
        if tool in {"getLocalMap", "getTravelOptions", "previewTravel", "getTravelStatus"}:
            from app.services.spatial import SpatialService
            projection = self.projection(project_id, head_node_id)
            spatial = SpatialService(self._spatial_projection(project_id, projection))
            if tool == "getLocalMap":
                return spatial.local_map(arguments.get("location_id"), administrative=narration_mode == "third_omniscient")
            if tool == "getTravelStatus":
                itinerary = projection.get("travel_itineraries", {}).get(str(arguments.get("itinerary_id") or ""))
                if itinerary:
                    return itinerary
                character_id = str(arguments.get("character_id") or pov_character_id or "")
                matches = [item for item in projection.get("travel_itineraries", {}).values() if item.get("character_id") == character_id]
                return matches[-1] if matches else None
            character_id = str(arguments.get("character_id") or pov_character_id or "")
            if tool == "previewTravel":
                return spatial.preview(character_id, str(arguments.get("location_id") or arguments.get("destination_id") or ""), str(arguments.get("mode") or "walk"))
            options = []
            for location in spatial.locations().values():
                if not location.get("state", {}).get("discovered", True):
                    continue
                preview = spatial.preview(character_id, str(location["id"]), str(arguments.get("mode") or "walk"))
                if preview.get("available") and preview.get("travel_minutes", 0) > 0:
                    options.append({"id": location["id"], "name": location["name"], "minutes": preview["travel_minutes"], "risk": "configured" if location.get("state", {}).get("encounter_rate", 0) else "none"})
            return sorted(options, key=lambda item: (item["minutes"], item["name"]))[:20]
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
            return [
                ability.model_dump(
                    mode="json",
                    include={
                        "ability_key", "name", "description", "target_type",
                        "ability_kind", "compatible_owner_kinds", "requirements", "costs", "actions",
                    },
                )
                for ability in self.data.rules.abilities(project_id)
            ]
        kind = "fact" if tool == "getKnownFacts" else "plot_beat"
        return self.search(project_id, str(arguments.get("query", "")), head_node_id=head_node_id,
                           pov_character_id=pov_character_id, narration_mode=narration_mode, kinds=[kind], limit=12)
