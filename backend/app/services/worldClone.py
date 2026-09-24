from __future__ import annotations

import copy
from typing import Any

from app.database import new_id
from app.services.world import WorldEngine, WorldValidationError


class WorldCloneService:
    """Clone a bounded dependency subgraph while assigning fresh identities."""

    def __init__(self, world: WorldEngine) -> None:
        self.world = world

    @staticmethod
    def _references(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_id") and isinstance(item, str): found.add(item)
                elif key.endswith("_ids") and isinstance(item, list): found.update(str(x) for x in item)
                else: found.update(WorldCloneService._references(item))
        elif isinstance(value, list):
            for item in value: found.update(WorldCloneService._references(item))
        return found

    @staticmethod
    def _remap(value: Any, ids: dict[str, str], field: str = "") -> Any:
        if isinstance(value, dict):
            return {key: WorldCloneService._remap(item, ids, key) for key, item in value.items()}
        if isinstance(value, list): return [WorldCloneService._remap(item, ids, field) for item in value]
        if isinstance(value, str) and (field.endswith("_id") or field.endswith("_ids")):
            return ids.get(value, value)
        return copy.deepcopy(value)

    @staticmethod
    def _rebase_effects(effects: list[dict[str, Any]], source: dict[str, Any], target: dict[str, Any]) -> list[dict[str, Any]]:
        rows = copy.deepcopy(effects)
        for effect in rows:
            if effect.get("expires_sequence") is not None:
                remaining = max(1, int(effect["expires_sequence"]) - int(source.get("branch_sequence", 0)))
                effect["expires_sequence"] = int(target.get("branch_sequence", 0)) + remaining
            if effect.get("expires_elapsed_minutes") is not None:
                remaining = max(1, int(effect["expires_elapsed_minutes"]) - int(source.get("elapsed_minutes", 0)))
                effect["expires_elapsed_minutes"] = int(target.get("elapsed_minutes", 0)) + remaining
        return rows

    def clone(self, target_project_id: str, *, source_project_id: str, entity_ids: list[str],
              include_children: bool = True, include_relationships: bool = True,
              include_referenced_entities: bool = True, include_rules: bool = True,
              max_depth: int = 8) -> dict[str, Any]:
        if not entity_ids: raise WorldValidationError("Select at least one entity to clone")
        source = self.world.projection(source_project_id)
        entities = source.get("entities", {})
        missing = [item for item in entity_ids if item not in entities]
        if missing: raise WorldValidationError(f"Unknown source entity: {missing[0]}")
        selected, frontier = set(entity_ids), set(entity_ids)
        for _ in range(max(0, min(max_depth, 32))):
            added: set[str] = set()
            if include_children:
                added.update(key for key, value in entities.items()
                             if value.get("state", {}).get("parent_location_id") in frontier)
                added.update(key for key, value in entities.items()
                             if value.get("state", {}).get("current_location_id") in frontier)
            if include_referenced_entities:
                for key in frontier: added.update(self._references(entities[key].get("state", {})))
            added = {item for item in added if item in entities} - selected
            if not added: break
            selected.update(added); frontier = added
        id_map = {item: new_id() for item in sorted(selected)}
        selected_anchors = {
            key: value for key, value in source.get("map_anchors", {}).items()
            if value.get("location_id") in selected
        }
        selected_barriers = {
            key: value for key, value in source.get("map_barriers", {}).items()
            if value.get("location_id") in selected
        }
        selected_connections = {
            key: value for key, value in source.get("travel_connections", {}).items()
            if value.get("source_anchor_id") in selected_anchors and value.get("target_anchor_id") in selected_anchors
        }
        selected_encounters = {
            key: value for key, value in source.get("encounter_rules", {}).items()
            if (value.get("location_id") in selected or value.get("connection_id") in selected_connections)
            and all(candidate.get("location_id") in selected for candidate in value.get("candidates", []))
        }
        spatial_id_map = {
            key: new_id() for key in sorted({*selected_anchors, *selected_barriers, *selected_connections, *selected_encounters})
        }
        all_ids = {**id_map, **spatial_id_map}
        target = self.world.projection(target_project_id)
        names = {str(value.get("name", "")).casefold() for value in target.get("entities", {}).values()}
        raw: list[dict[str, Any]] = []
        for source_id in sorted(selected):
            item = entities[source_id]
            name, suffix = str(item["name"]), 2
            base = name
            while name.casefold() in names:
                name = f"{base} (Copy {suffix})"; suffix += 1
            names.add(name.casefold())
            cloned_state = self._remap(item.get("state", {}), id_map)
            if item.get("kind") == "location" and item.get("state", {}).get("parent_location_id") not in selected:
                cloned_state["parent_location_id"] = target.get("root_location_id")
            raw.append({"tool": "createEntity", "arguments": {
                "entity_id": id_map[source_id], "kind": item["kind"], "name": name,
                "aliases": copy.deepcopy(item.get("aliases", [])), "tags": copy.deepcopy(item.get("tags", [])),
                "state": cloned_state,
                "stats": copy.deepcopy(item.get("stats", {})),
                "active_effects": self._remap(self._rebase_effects(item.get("active_effects", []), source, target), id_map),
            }})
        relationship_count = 0
        if include_relationships:
            for relation in source.get("relations", {}).values():
                if relation.get("source_id") in selected and relation.get("target_id") in selected:
                    relation_data = {k: v for k, v in relation.items() if k != "id"}
                    relation_data["active_effects"] = self._rebase_effects(
                        relation.get("active_effects", []), source, target
                    )
                    raw.append({"tool": "setRelationship", "arguments": {
                        **self._remap(relation_data, id_map),
                        "source_id": id_map[relation["source_id"]], "target_id": id_map[relation["target_id"]],
                    }})
                    relationship_count += 1
        for anchor_id, anchor in selected_anchors.items():
            raw.append({"tool": "upsertMapAnchor", "arguments": {"id": spatial_id_map[anchor_id], **self._remap({key: value for key, value in anchor.items() if key != "id"}, all_ids)}})
        for barrier_id, barrier in selected_barriers.items():
            raw.append({"tool": "upsertBarrier", "arguments": {"id": spatial_id_map[barrier_id], **self._remap({key: value for key, value in barrier.items() if key != "id"}, all_ids)}})
        for connection_id, connection in selected_connections.items():
            raw.append({"tool": "upsertTravelConnection", "arguments": {"id": spatial_id_map[connection_id], **self._remap({key: value for key, value in connection.items() if key != "id"}, all_ids)}})
        for encounter_id, encounter in selected_encounters.items():
            raw.append({"tool": "upsertEncounterRule", "arguments": {"id": spatial_id_map[encounter_id], **self._remap({key: value for key, value in encounter.items() if key != "id"}, all_ids)}})
        if source.get("root_location_id") in selected and not target.get("root_location_id"):
            raw.append({"tool": "setWorldRoot", "arguments": {"root_location_id": id_map[source["root_location_id"]], "adopt_top_level": False, "reparent_previous": False}})
        project = self.world.db.get_project(target_project_id) or {}
        mutations = self.world.normalize_mutations(target_project_id, project.get("active_node_id"), raw, provenance="clone")
        if project.get("active_node_id"):
            transaction = self.world.commit_to_existing_node(target_project_id, project["active_node_id"], mutations, provenance="clone", summary="Cloned world subgraph")
        else:
            transaction = self.world.commit_root(target_project_id, mutations, provenance="clone", summary="Cloned world subgraph")
        cloned_stats = cloned_abilities = 0
        if include_rules:
            now = self.world.db.fetch_one("SELECT CURRENT_TIMESTAMP value")["value"]
            for row in self.world.db.fetch_all("SELECT * FROM stat_definitions WHERE project_id=?", (source_project_id,)):
                if self.world.db.fetch_one("SELECT id FROM stat_definitions WHERE project_id=? AND stat_key=?", (target_project_id, row["stat_key"])): continue
                self.world.db.execute(
                    "INSERT INTO stat_definitions(id,project_id,stat_key,label,scope,default_value,minimum,maximum,integer_only,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), target_project_id, row["stat_key"], row["label"], row["scope"], row["default_value"], row["minimum"], row["maximum"], row["integer_only"], row["visibility"], now, now),
                ); cloned_stats += 1
            for row in self.world.db.fetch_all("SELECT * FROM ability_definitions WHERE project_id=?", (source_project_id,)):
                if self.world.db.fetch_one("SELECT id FROM ability_definitions WHERE project_id=? AND ability_key=?", (target_project_id, row["ability_key"])): continue
                self.world.db.execute(
                    "INSERT INTO ability_definitions(id,project_id,ability_key,name,description,target_type,requirements_json,costs_json,effects_json,created_at,updated_at,minigame_profile_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), target_project_id, row["ability_key"], row["name"], row["description"], row["target_type"], row["requirements_json"], row["costs_json"], row["effects_json"], now, now, row.get("minigame_profile_json") or "{}"),
                ); cloned_abilities += 1
        return {"transaction_id": transaction["id"], "entity_id_map": id_map,
                "entity_count": len(selected), "relationship_count": relationship_count,
                "spatial_object_id_map": spatial_id_map, "spatial_object_count": len(spatial_id_map),
                "stat_count": cloned_stats, "ability_count": cloned_abilities}
