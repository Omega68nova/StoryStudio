from __future__ import annotations

import copy
from typing import Any

from app.database import new_id
from app.services.world import NormalizedMutation, WorldEngine, WorldValidationError


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
            }})
        relationship_count = 0
        if include_relationships:
            for relation in source.get("relations", {}).values():
                if relation.get("source_id") in selected and relation.get("target_id") in selected:
                    relation_data = {k: v for k, v in relation.items() if k != "id"}
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
        cloned_stats = cloned_effects = cloned_abilities = 0
        if include_rules:
            source_rules, target_rules = self.world.data.rules, self.world.data.rules
            for definition in source_rules.stats(source_project_id):
                if target_rules.stat(target_project_id, definition.stat_key): continue
                target_rules.save_stat(definition.model_copy(update={"project_id": target_project_id})); cloned_stats += 1
            for definition in source_rules.effects(source_project_id):
                if target_rules.effect(target_project_id, definition.effect_key): continue
                target_rules.save_effect(definition.model_copy(update={"project_id": target_project_id})); cloned_effects += 1
            for definition in source_rules.abilities(source_project_id):
                if target_rules.ability(target_project_id, definition.ability_key): continue
                target_rules.save_ability(definition.model_copy(update={"project_id": target_project_id})); cloned_abilities += 1
            active_mutations: list[NormalizedMutation] = []
            target_projection = self.world.projection(target_project_id, project.get("active_node_id"))
            for instance in source.get("active_effects", {}).values():
                if instance.get("target_id") not in selected: continue
                cloned = self._remap(instance, id_map)
                cloned["id"] = new_id()
                clock = cloned.get("clock")
                source_progress = int(source.get("elapsed_minutes", 0)) if clock == "story_minutes" else int(source.get("world_action_count", 0)) if clock == "world_actions" else int(source.get("target_action_counts", {}).get(instance.get("target_id"), 0))
                target_progress = int(target_projection.get("elapsed_minutes", 0)) if clock == "story_minutes" else int(target_projection.get("world_action_count", 0)) if clock == "world_actions" else int(target_projection.get("target_action_counts", {}).get(cloned.get("target_id"), 0))
                for field in ("started_at", "next_tick", "expires_at"):
                    if cloned.get(field) is not None: cloned[field] = target_progress + (int(cloned[field]) - source_progress)
                active_mutations.append(NormalizedMutation("cloneEffectInstance", cloned, False))
            if active_mutations:
                transaction = self.world.commit_to_existing_node(target_project_id, project["active_node_id"], active_mutations, provenance="clone", summary="Cloned active effect instances") if project.get("active_node_id") else self.world.commit_root(target_project_id, active_mutations, provenance="clone", summary="Cloned active effect instances")
        return {"transaction_id": transaction["id"], "entity_id_map": id_map,
                "entity_count": len(selected), "relationship_count": relationship_count,
                "spatial_object_id_map": spatial_id_map, "spatial_object_count": len(spatial_id_map),
                "stat_count": cloned_stats, "effect_count": cloned_effects, "ability_count": cloned_abilities}
