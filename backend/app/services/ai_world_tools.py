from __future__ import annotations

import json
import re
from typing import Any

from app.data.dataProvider import DataProvider
from app.managers.soundManager import SoundManager
from app.services.world import READ_TOOLS, WorldEngine


TOOL_DESCRIPTIONS: dict[str, str] = {
    "searchEntities": "Search visible entities by text and optional kinds.",
    "getEntity": "Read one visible entity by exact entity_id.",
    "getScene": "Read current time, POV, location, and present entities.",
    "getNearbyLocations": "List sibling locations, optionally in a cardinal direction.",
    "findRoute": "Find a traversable route between two location IDs.",
    "getKnownFacts": "Search facts visible to the current perspective.",
    "getActivePlotBeats": "Search active plot guidance visible to the narrator.",
    "getStats": "Read current stats for one character.",
    "getAbilities": "Read project ability definitions.",
    "searchLocations": "Search the complete ordinary location catalog in bounded pages.",
    "getLocationMap": "Read one compact hierarchical map layer.",
    "getSceneEnvironment": "Read the current compact scene environment.",
    "getLocalMap": "Read the discovered local map as semantic locations, exits, locks, risks, and blocked reasons; raw geometry is omitted.",
    "getTravelOptions": "List currently reachable discovered destinations and estimated travel time.",
    "previewTravel": "Preview travel time, segments, requirements, risk, and compact blocked reasons.",
    "getTravelStatus": "Read a character's active or named travel itinerary.",
    "getSpatialPresets": "List compact reviewed location, barrier, door, and portal creation presets.",
    "createEntity": "Stage creation of a canonical typed world entity.",
    "updateEntity": "Stage a merge patch to an existing entity.",
    "moveCharacter": "Stage movement to a location over a valid route.",
    "setRelationship": "Stage a relationship or route between two entities.",
    "revealKnowledge": "Stage revealing a fact to characters or factions.",
    "advanceTime": "Stage non-negative elapsed story time.",
    "updatePlotBeat": "Stage a plot beat status change.",
    "adjustStat": "Stage a bounded stat correction.",
    "useAbility": "Stage a known ability after validating costs and targets.",
    "selectTheme": "Choose one project-enabled music theme when AI music is enabled.",
    "setSceneEnvironment": "Set the focused player, short lowercase -ing action, and optionally valid next weather.",
    "proposeWeather": "Propose a reusable weather definition for administrator review.",
    "playNoise": "Play one enabled one-shot noise from the project catalog.",
    "setWorldRoot": "Select a location as the branch world root and optionally place the previous root beneath it.",
    "upsertMapAnchor": "Create or edit a named landmark, entrance, exit, waypoint, or encounter point using flat coordinates.",
    "upsertBarrier": "Create or edit a reviewed map barrier with modes and typed requirements.",
    "upsertTravelConnection": "Create or edit a route, door, or portal between named anchors.",
    "upsertEncounterRule": "Configure deterministic weighted encounters for a location or connection.",
    "setMapDiscovery": "Reveal or hide one map object without changing its mechanical behavior.",
    "travelTo": "Travel a character to a named location using engine-resolved paths.",
    "travelTowards": "Travel toward a named destination for a bounded number of minutes.",
    "exploreFor": "Explore deterministically for a number of minutes and optional cardinal direction.",
    "resumeTravel": "Explicitly resume a paused itinerary.",
    "createLocationFromPreset": "Create a location from a reviewed preset using a name and flat overrides.",
    "editMapGeometry": "Add, move, or remove one reviewed barrier point without replacing raw geometry JSON.",
    "removeMapObject": "Remove one anchor, barrier, connection, or encounter rule after dependency validation.",
}

PLANNER_WRITE_TOOLS = {
    "createEntity",
    "updateEntity",
    "moveCharacter",
    "setRelationship",
    "revealKnowledge",
    "advanceTime",
    "updatePlotBeat",
    "adjustStat",
    "useAbility",
    "selectTheme",
    "setSceneEnvironment",
    "proposeWeather",
    "playNoise",
    "setWorldRoot",
    "upsertMapAnchor",
    "upsertBarrier",
    "upsertTravelConnection",
    "upsertEncounterRule",
    "setMapDiscovery",
    "travelTo",
    "travelTowards",
    "exploreFor",
    "resumeTravel",
    "createLocationFromPreset",
    "editMapGeometry",
    "removeMapObject",
}


class AIAliasResolver:
    """Ephemeral friendly keys for AI prompts; canonical IDs remain on disk."""

    def __init__(self, projection: dict[str, Any]) -> None:
        self.by_id: dict[str, str] = {}
        candidates: dict[str, set[str]] = {}
        for entity in projection.get("entities", {}).values():
            entity_id = str(entity["id"])
            base = re.sub(r"[^a-z0-9]+", "_", str(entity.get("name") or entity_id).casefold()).strip("_") or "entity"
            key = base
            if key in self.by_id.values():
                key = f"{base}_{entity_id.replace('-', '')[:6]}"
            self.by_id[entity_id] = key
            for value in [entity_id, key, entity.get("name"), *(entity.get("aliases") or [])]:
                if value:
                    candidates.setdefault(str(value).strip().casefold(), set()).add(entity_id)
        for relation in projection.get("relations", {}).values():
            relation_id = str(relation["id"])
            source = self.by_id.get(str(relation.get("source_id")), "source")
            target = self.by_id.get(str(relation.get("target_id")), "target")
            label = re.sub(r"[^a-z0-9]+", "_", str(relation.get("relation") or "relation").casefold()).strip("_")
            base = f"{source}_{label}_{target}"
            key = base if base not in self.by_id.values() else f"{base}_{relation_id.replace('-', '')[:6]}"
            self.by_id[relation_id] = key
            for value in (relation_id, key):
                candidates.setdefault(value.casefold(), set()).add(relation_id)
        for collection in ("map_anchors", "map_barriers", "travel_connections", "encounter_rules", "travel_itineraries"):
            for item in projection.get(collection, {}).values():
                item_id = str(item["id"])
                label = str(item.get("name") or item.get("kind") or collection.rstrip("s"))
                base = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_") or "map_object"
                key = base if base not in self.by_id.values() else f"{base}_{item_id.replace('-', '')[:6]}"
                self.by_id[item_id] = key
                for value in (item_id, key, item.get("name")):
                    if value:
                        candidates.setdefault(str(value).strip().casefold(), set()).add(item_id)
        self.lookup = {key: next(iter(ids)) for key, ids in candidates.items() if len(ids) == 1}

    def canonicalize(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {item_key: self.canonicalize(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            child_key = key[:-1] if key.endswith("s") else key
            return [self.canonicalize(item, child_key) for item in value]
        if isinstance(value, str) and (key.endswith("_id") or key.endswith("_ids")):
            return self.lookup.get(value.strip().casefold(), value)
        return value


def native_tools(allowed_names: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
        }
        for name, description in TOOL_DESCRIPTIONS.items()
        if allowed_names is None or name in allowed_names
    ]


def split_native_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reads: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function") or {}
        name = str(function.get("name", ""))
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        normalized = {
            "tool": name,
            "arguments": arguments,
            "tool_call_id": call.get("id", ""),
        }
        if name in READ_TOOLS:
            reads.append(normalized)
        elif name in PLANNER_WRITE_TOOLS:
            writes.append(normalized)
    return reads, writes


class AIWorldToolService:
    """The AI-facing boundary over world reads and staged domain writes."""

    def __init__(
        self,
        world: WorldEngine,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.world = world
        self.data = data_provider or world.data
        self.sound = SoundManager(
            self.data.db,
            data_provider=self.data,
        )

    def planner_context(
        self,
        *,
        project_id: str,
        head_node_id: str | None,
        user_text: str,
        pov_character_id: str | None,
        narration_mode: str,
        token_budget: int,
        semantic_ids: list[str] | None,
    ) -> dict[str, Any]:
        package = self.world.context_package(
            project_id,
            head_node_id,
            user_text,
            pov_character_id,
            narration_mode,
            token_budget,
            semantic_ids,
        )
        aliases = AIAliasResolver(self.world.projection(project_id, head_node_id))
        compact_entities = [
            {
                "id": entity["id"],
                "ai_key": aliases.by_id.get(str(entity["id"]), str(entity["id"])),
                "kind": entity["kind"],
                "name": entity["name"],
                "card": entity["card"]["compact_text"],
                "reason": entity.get("reason"),
            }
            for entity in package["entities"]
        ]
        selected_ids = {str(entity["id"]) for entity in package["entities"]}
        compact_relationships = [
            {
                "id": relation["id"],
                "ai_key": aliases.by_id.get(str(relation["id"]), str(relation["id"])),
                "source_id": relation.get("source_id"),
                "target_id": relation.get("target_id"),
                "relation": relation.get("relation"),
                "stats": relation.get("stats", {}),
            }
            for relation in self.world.projection(project_id, head_node_id).get("relations", {}).values()
            if relation.get("source_id") in selected_ids or relation.get("target_id") in selected_ids
        ][:40]
        abilities = self.data.world.ability_summaries(project_id)
        for ability in abilities:
            for field in ("requirements", "costs", "effects"):
                ability[field] = json.loads(ability.pop(f"{field}_json"))
        rules = {
            "stats": self.data.world.stat_summaries(project_id),
            "abilities": abilities,
        }
        noises = [
            {
                "id": noise["id"],
                "label": noise["label"],
                "tags": noise.get("tags", []),
            }
            for noise in self.sound.list_noises(project_id, refresh=True)
            if noise.get("enabled") and noise.get("available")
        ]
        music_settings = self.data.music.project_settings(project_id)
        music = {"mode": music_settings.get("mode", "disabled")}
        music["themes"] = (
            [
                {
                    "id": theme["id"],
                    "name": theme["name"],
                    "description": theme.get("description", ""),
                }
                for theme in self.data.music.available_themes(project_id)
            ]
            if music.get("mode") == "ai_managed"
            else []
        )
        environment = self.data.environment.settings_row(project_id) or {
            "enabled": 0,
            "ai_create_locations": 0,
            "ai_propose_weather": 0,
        }
        allowed = set(READ_TOOLS) | (PLANNER_WRITE_TOOLS - {
            "setSceneEnvironment",
            "proposeWeather",
        })
        if environment.get("enabled"):
            allowed.add("setSceneEnvironment")
        else:
            allowed -= {
                "searchLocations",
                "getLocationMap",
                "getSceneEnvironment",
            }
        if environment.get("enabled") and environment.get(
            "ai_propose_weather"
        ):
            allowed.add("proposeWeather")
        return {
            "scene": {**package, "entities": compact_entities, "relationships": compact_relationships},
            "game_rules": rules,
            "music": music,
            "noises": noises,
            "environment_policy": {
                "enabled": bool(environment.get("enabled")),
                "may_create_locations": bool(
                    environment.get("ai_create_locations")
                ),
                "may_propose_weather": bool(
                    environment.get("ai_propose_weather")
                ),
            },
            "allowed_tools": allowed,
            "read_tools": sorted(READ_TOOLS & allowed),
        }

    def execute_read(
        self,
        *,
        project_id: str,
        head_node_id: str | None,
        pov_character_id: str | None,
        narration_mode: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> Any:
        aliases = AIAliasResolver(
            self.world.projection(project_id, head_node_id)
        )
        return self.world.execute_read_tool(
            project_id,
            head_node_id,
            pov_character_id,
            narration_mode,
            tool,
            aliases.canonicalize(arguments),
        )

    def normalize_writes(
        self,
        *,
        project_id: str,
        head_node_id: str | None,
        mutations: list[dict[str, Any]],
        provenance: str,
    ) -> list[Any]:
        aliases = AIAliasResolver(
            self.world.projection(project_id, head_node_id)
        )
        canonical = [
            {
                **mutation,
                "arguments": aliases.canonicalize(
                    mutation.get("arguments") or mutation.get("args") or {}
                ),
            }
            for mutation in mutations
        ]
        return self.world.normalize_mutations(
            project_id,
            head_node_id,
            canonical,
            provenance=provenance,
        )
