from __future__ import annotations

from pathlib import Path

import pytest

from app.database import Database
from app.managers.batchGenerationManager import BatchGenerationManager
from app.managers.soundManager import SoundManager
from app.services.ai_world_tools import AIAliasResolver
from app.services.batchGeneration import GenerationPlanCycleError, GenerationPlanDefinition, GenerationTaskDefinition
from app.services.planningWorkspace import PlanningWorkspaceService
from app.services.world import WorldEngine
from app.services.worldClone import WorldCloneService


def _projection() -> dict:
    return {
        "entities": {
            "room": {"id": "room", "kind": "location", "name": "Hall", "state": {}},
            "hero": {"id": "hero", "kind": "character", "name": "Mara Vale", "aliases": ["Captain"], "tags": ["brave"], "stats": {"hp": 8}, "state": {"current_location_id": "room", "abilities": ["war_cry"], "inventory": [{"item_id": "key", "quantity": 1}]}},
            "ally": {"id": "ally", "kind": "character", "name": "Ivo", "aliases": [], "tags": [], "stats": {"hp": 5}, "state": {"current_location_id": "room"}},
            "enemy": {"id": "enemy", "kind": "character", "name": "Guard", "aliases": [], "tags": [], "stats": {"hp": 7}, "state": {"current_location_id": "room"}},
            "key": {"id": "key", "kind": "item", "name": "Key", "state": {}},
        },
        "relations": {
            "friend": {"id": "friend", "source_id": "hero", "target_id": "ally", "relation": "ally", "stats": {}},
            "foe": {"id": "foe", "source_id": "hero", "target_id": "enemy", "relation": "enemy", "stats": {}},
        },
        "current_weather_id": "rain",
        "elapsed_minutes": 0,
    }


def test_ai_aliases_are_ephemeral_and_ambiguous_names_are_not_resolved() -> None:
    projection = _projection()
    projection["entities"]["other"] = {"id": "other", "kind": "character", "name": "Other", "aliases": ["Captain"], "state": {}}
    resolver = AIAliasResolver(projection)
    assert resolver.by_id["hero"] == "mara_vale"
    assert resolver.canonicalize({"actor_id": "mara_vale", "target_id": "Ivo"}) == {"actor_id": "hero", "target_id": "ally"}
    assert resolver.canonicalize({"actor_id": "Captain"})["actor_id"] == "Captain"


def test_generation_plan_dependencies_are_editable_and_cycles_rejected(tmp_path: Path) -> None:
    db = Database(tmp_path); db.initialize(); project = db.create_project("DAG")
    manager = BatchGenerationManager(db)
    plan = manager.create_plan(project["id"], GenerationPlanDefinition(name="Editable", tasks=[
        GenerationTaskDefinition(key="a", generator_kind="text", target_kind="text"),
        GenerationTaskDefinition(key="b", generator_kind="text", target_kind="text"),
    ]))
    edited = manager.replace_dependencies(plan["id"], "b", [{"task_key": "a", "required_state": "generated"}])
    assert edited["tasks"][1]["dependencies"] == [{"task_key": "a", "required_state": "generated"}]
    with pytest.raises(GenerationPlanCycleError):
        manager.replace_dependencies(plan["id"], "a", [{"task_key": "b", "required_state": "generated"}])


def test_planning_wire_uses_tasks_only(tmp_path: Path) -> None:
    db = Database(tmp_path); db.initialize(); project = db.create_project("Planning")
    view = PlanningWorkspaceService(db, world=WorldEngine(db)).create(project["id"], {})
    assert "tasks" in view and "current_task" in view
    assert "stages" not in view and "current_stage" not in view
    assert "task_number" in view["tasks"][0]
    assert "stage_number" not in view["tasks"][0]


def test_deep_clone_remaps_children_and_relationships(tmp_path: Path) -> None:
    db = Database(tmp_path); db.initialize()
    source, target = db.create_project("Source"), db.create_project("Target")
    world = WorldEngine(db)
    raw = [
        {"tool": "createEntity", "arguments": {"entity_id": "place", "kind": "location", "name": "Keep", "state": {}}},
        {"tool": "createEntity", "arguments": {"entity_id": "room", "kind": "location", "name": "Room", "state": {"parent_location_id": "place"}}},
        {"tool": "createEntity", "arguments": {"entity_id": "person", "kind": "character", "name": "Mara", "state": {"current_location_id": "room"}}},
        {"tool": "setRelationship", "arguments": {"source_id": "person", "target_id": "place", "relation": "guards"}},
    ]
    world.commit_root(source["id"], world.normalize_mutations(source["id"], None, raw, provenance="author"), provenance="author", summary="fixture")
    result = WorldCloneService(world).clone(target["id"], source_project_id=source["id"], entity_ids=["place"], include_children=True, include_relationships=True, include_referenced_entities=True)
    projection = world.projection(target["id"], use_cache=False)
    assert result["entity_count"] == 3
    assert projection["entities"][result["entity_id_map"]["room"]]["state"]["parent_location_id"] == result["entity_id_map"]["place"]
    assert len(projection["relations"]) == 1


def test_noise_folder_is_not_indexed_as_ambient(tmp_path: Path) -> None:
    db = Database(tmp_path / "data"); db.initialize(); project = db.create_project("Sound")
    sound_root = tmp_path / "sounds"; (sound_root / "noises").mkdir(parents=True)
    (sound_root / "rain.mp3").write_bytes(b"ambient")
    (sound_root / "noises" / "slash.mp3").write_bytes(b"noise")
    manager = SoundManager(db, sound_root=sound_root)
    manager.index_sources(project["id"]); manager.index_noises(project["id"])
    assert [item["source_path"] for item in manager.list_variants(project["id"])] == ["rain.mp3"]
    assert [item["source_path"] for item in manager.list_noises(project["id"])] == ["noises/slash.mp3"]
