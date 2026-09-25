from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.database import Database, new_id, utc_now
from app.services.environment import EnvironmentService
from app.services.world import WorldEngine, WorldValidationError
from app.schemas import MapLocationPlacementUpdate
from app.domain.world import LocationState


def setup(path: Path):
    db = Database(path); db.initialize(); project = db.create_project("Environment")
    environment = EnvironmentService(db); environment.ensure_project(project["id"])
    return db, project, WorldEngine(db), environment


def create(world: WorldEngine, project_id: str, **arguments):
    mutation = world.normalize_mutations(project_id, None, [{"tool": "createEntity", "arguments": arguments}], provenance="author")
    world.commit_root(project_id, mutation, provenance="author", summary="test")
    return mutation[0].arguments["entity_id"]


def test_legacy_map_placement_canonicalizes_invalid_known_fields() -> None:
    from app.main import _canonical_map_location_patch

    legacy_state = {
        "parent_location_id": "",
        "exposure": "outside",
        "topology": "legacy_routed",
        "occupancy": "legacy",
        "boundary_access": "legacy",
        "minutes_per_unit": 0,
        "base_visibility_units": -5,
        "encounter_rate": 7,
        "priority_layer": "not-a-number",
        "enabled": "yes",
        "discovered": "true",
        "hidden": "false",
        "random_encounter": "0",
        "image_tags": "old-string-format",
        "local_bounds": {"kind": "polygon", "points": []},
        "legacy_marker": {"kept": "outside canonical fields"},
    }
    request = MapLocationPlacementUpdate(
        x=42,
        y=37,
        spatial_kind="spot",
        footprint={
            "location_id": "world",
            "kind": "point",
            "points": [{"x": 42, "y": 37}],
        },
    )
    projection = {
        "entities": {
            "world": {"id": "world", "kind": "location", "state": {"archived": False}},
        }
    }
    patch = _canonical_map_location_patch(legacy_state, request, "legacy-location", projection)
    validated = LocationState.model_validate(patch)

    assert validated.parent_location_id == "world"
    assert validated.exposure == "outdoor"
    assert validated.topology == "closed"
    assert validated.occupancy == "direct_allowed"
    assert validated.boundary_access == "free"
    assert validated.minutes_per_unit == 1
    assert validated.base_visibility_units is None
    assert validated.encounter_rate == 0
    assert validated.x == 42 and validated.y == 37
    assert validated.footprint is not None and validated.footprint.kind == "point"


def test_legacy_map_placement_replaces_missing_parent_with_map_layer() -> None:
    from app.main import _canonical_map_location_patch

    projection = {
        "entities": {
            "current-map": {"id": "current-map", "kind": "location", "state": {"archived": False}},
        }
    }
    request = MapLocationPlacementUpdate(
        x=15,
        y=25,
        spatial_kind="spot",
        footprint={
            "location_id": "current-map",
            "kind": "point",
            "points": [{"x": 15, "y": 25}],
        },
    )
    patch = _canonical_map_location_patch(
        {"parent_location_id": "deleted-old-parent"},
        request,
        "legacy-location",
        projection,
    )
    assert patch["parent_location_id"] == "current-map"
    assert patch["footprint"]["location_id"] == "current-map"


def test_parent_repair_batch_fixes_unrelated_stale_locations() -> None:
    from app.main import _legacy_location_parent_repairs

    projection = {
        "root_location_id": "world",
        "entities": {
            "world": {"id": "world", "kind": "location", "state": {"archived": False}},
            "noble": {
                "id": "noble", "kind": "location",
                "state": {
                    "parent_location_id": "missing-old-parent",
                    "footprint": {"location_id": "world", "kind": "point", "points": [{"x": 1, "y": 1}]},
                },
            },
            "slums": {
                "id": "slums", "kind": "location",
                "state": {
                    "parent_location_id": "missing-old-parent",
                    "footprint": {"location_id": "missing-old-parent", "kind": "point", "points": [{"x": 2, "y": 2}]},
                },
            },
        },
    }

    repairs = _legacy_location_parent_repairs(
        projection,
        target_location_id="noble",
        target_map_id="world",
    )
    by_id = {item["arguments"]["entity_id"]: item["arguments"]["patch"] for item in repairs}

    assert by_id["noble"]["parent_location_id"] == "world"
    assert by_id["noble"]["footprint"]["location_id"] == "world"
    assert by_id["slums"]["parent_location_id"] == "world"
    assert by_id["slums"]["footprint"]["location_id"] == "world"


def test_defaults_time_cycle_and_branch_scene(tmp_path: Path) -> None:
    db, project, world, environment = setup(tmp_path)
    settings = environment.settings(project["id"])
    assert settings["enabled"] and settings["weather"][0]["name"] == "Sunny"
    assert [item["name"] for item in settings["time_phases"]] == ["Morning", "Day", "Noon", "Afternoon", "Night"]
    assert environment.phase(project["id"], 0)["name"] == "Morning"
    assert environment.phase(project["id"], 180)["name"] == "Day"
    assert environment.phase(project["id"], 1440)["name"] == "Morning"
    place = create(world, project["id"], kind="location", name="Square", state={})
    hero = create(world, project["id"], kind="character", name="Hero", state={"player_controlled": True, "current_location_id": place})
    mutation = world.normalize_mutations(project["id"], None, [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": hero, "player_action": "walking"}}])
    world.commit_root(project["id"], mutation, provenance="test", summary="scene")
    scene = environment.scene(project["id"], world.projection(project["id"]))
    assert scene["focused_character"]["id"] == hero and scene["location"]["id"] == place and scene["player_action"] == "walking"
    with pytest.raises(WorldValidationError, match="ending in ing"):
        world.normalize_mutations(project["id"], None, [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": hero, "player_action": "walk"}}])


def test_directed_weather_and_ordered_route(tmp_path: Path) -> None:
    db, project, world, environment = setup(tmp_path); now = utc_now()
    sunny = environment.settings(project["id"])["initial_weather_id"]; rain = new_id()
    db.execute("INSERT INTO weather_definitions(id,project_id,name,description,created_at,updated_at) VALUES(?,?, 'Rain','',?,?)", (rain, project["id"], now, now))
    a = create(world, project["id"], kind="location", name="A", state={}); b = create(world, project["id"], kind="location", name="B", state={}); c = create(world, project["id"], kind="location", name="C", state={})
    routes = world.normalize_mutations(project["id"], None, [
        {"tool": "setRelationship", "arguments": {"source_id": a, "target_id": b, "relation": "route", "travel_minutes": 3}},
        {"tool": "setRelationship", "arguments": {"source_id": b, "target_id": c, "relation": "route", "travel_minutes": 4}},
    ], provenance="author")
    world.commit_root(project["id"], routes, provenance="author", summary="routes")
    assert world.route(project["id"], a, c)["location_ids"] == [a, b, c]
    hero = create(world, project["id"], kind="character", name="Hero", state={"player_controlled": True, "current_location_id": a})
    with pytest.raises(WorldValidationError, match="transition"):
        world.normalize_mutations(project["id"], None, [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": hero, "player_action": "waiting", "weather_id": rain}}])
    db.execute("INSERT INTO weather_transitions(project_id,source_weather_id,target_weather_id) VALUES(?,?,?)", (project["id"], sunny, rain))
    assert world.normalize_mutations(project["id"], None, [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": hero, "player_action": "waiting", "weather_id": rain}}])


def test_isolated_location_uses_only_location_ambient(tmp_path: Path) -> None:
    db, project, world, environment = setup(tmp_path); now = utc_now()
    place = create(world, project["id"], kind="location", name="Bunker", state={"exposure": "isolated"})
    hero = create(world, project["id"], kind="character", name="Hero", state={"player_controlled": True, "current_location_id": place})
    scene_mutation = world.normalize_mutations(project["id"], None, [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": hero, "player_action": "standing"}}])
    world.commit_root(project["id"], scene_mutation, provenance="test", summary="scene")
    weather = environment.settings(project["id"])["initial_weather_id"]
    variants = [new_id(), new_id()]
    for variant in variants:
        db.execute("INSERT INTO ambient_variants(id,project_id,source_path,label,tags_json,available,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)", (variant, project["id"], f"{variant}.mp3", variant, json.dumps([]), now, now))
    db.execute("INSERT INTO ambient_assignments(id,project_id,owner_type,owner_id,selector_type,variant_id) VALUES(?,?, 'weather',?,'default',?)", (new_id(), project["id"], weather, variants[0]))
    db.execute("INSERT INTO ambient_assignments(id,project_id,owner_type,owner_id,selector_type,variant_id) VALUES(?,?, 'location',?,'default',?)", (new_id(), project["id"], place, variants[1]))
    resolved = environment.scene(project["id"], world.projection(project["id"]))["ambient"]
    assert [item["id"] for item in resolved] == [variants[1]]


def test_environment_form_fields_conditional_sets_and_disabled_filters(tmp_path: Path) -> None:
    db, project, world, environment = setup(tmp_path); now = utc_now()
    settings = environment.settings(project["id"])
    assert settings["weather"][0]["imagegen_description"] == ""
    assert settings["time_phases"][0]["description"] == ""
    place = create(world, project["id"], kind="location", name="Garden", state={"enabled": True, "exposure": "outdoor"})
    hidden = create(world, project["id"], kind="location", name="Closed wing", state={"enabled": False})
    hero = create(world, project["id"], kind="character", name="Hero", state={"player_controlled": True, "current_location_id": place})
    mutation = world.normalize_mutations(project["id"], None, [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": hero, "player_action": "standing"}}])
    world.commit_root(project["id"], mutation, provenance="test", summary="scene")
    variant = new_id()
    db.execute("INSERT INTO ambient_variants(id,project_id,source_path,label,tags_json,available,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)", (variant, project["id"], "birds.ogg", "Birds", "[]", now, now))
    weather_id, phase_id = settings["initial_weather_id"], settings["time_phases"][0]["id"]
    environment.replace_ambient_sets(project["id"], "location", place, [{"selector_type": "outdoor", "weather_id": weather_id, "time_phase_id": phase_id, "variant_ids": [variant, variant]}])
    assert [item["id"] for item in environment.scene(project["id"], world.projection(project["id"]))["ambient"]] == [variant]
    assert hidden not in {item["id"] for item in environment.map_layer(project["id"], world.projection(project["id"]), None, admin=False)["locations"]}
    db.execute("UPDATE time_phases SET position=99 WHERE id=?", (phase_id,))
    assert environment.ambient_sets(project["id"], "location", place)[0]["variant_ids"] == [variant]
