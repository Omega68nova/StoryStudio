from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.database import Database
from app.domain.adapters import (
    DomainAdapterError,
    ability_from_record,
    ability_to_record,
    entity_from_projection,
    entity_to_projection,
    stat_from_record,
    stat_to_record,
    weather_from_record,
    weather_to_record,
)
from app.domain.world import (
    Character,
    DomainKind,
    Location,
    Weather,
)
from app.managers.environmentManager import EnvironmentManager
from app.services.environment import EnvironmentService
from app.services.world import WorldEngine


def setup_world(path: Path) -> tuple[Database, dict, WorldEngine]:
    db = Database(path)
    db.initialize()
    project = db.create_project("Typed world")
    return db, project, WorldEngine(db)


def create(
    world: WorldEngine,
    project_id: str,
    **entity: object,
) -> str:
    mutations = world.normalize_mutations(
        project_id,
        None,
        [{"tool": "createEntity", "arguments": entity}],
        provenance="author",
    )
    world.commit_root(
        project_id,
        mutations,
        provenance="author",
        summary="typed fixture",
    )
    return str(mutations[0].arguments["entity_id"])


def test_sparse_character_round_trip_does_not_add_defaults() -> None:
    raw = {
        "id": "character-1",
        "kind": "character",
        "name": "Mara",
    }

    typed = entity_from_projection(raw)

    assert isinstance(typed, Character)
    assert entity_to_projection(typed) == raw


def test_full_character_round_trip_preserves_extension_state() -> None:
    raw = {
        "id": "character-1",
        "kind": "character",
        "name": "Mara",
        "aliases": ["The Cartographer"],
        "tags": ["explorer"],
        "state": {
            "description": "A careful explorer.",
            "identity": "Guild cartographer",
            "pronouns": "she/her",
            "appearance": "Silver-streaked black hair",
            "personality": "Patient and exacting",
            "goals": ["Map the coast"],
            "character_secrets": ["She found the hidden road"],
            "secrets_to_character": ["The guild is watching her"],
            "player_controlled": False,
            "autonomy_enabled": True,
            "current_location_id": "location-1",
            "inventory": [{"item_id": "item-1", "quantity": 2}],
            "custom_plugin_state": {"rank": 7},
        },
        "stats": {"stamina": 72},
        "active_effects": [],
        "plugin_top_level": {"source": "example"},
    }

    typed = entity_from_projection(raw)

    assert isinstance(typed, Character)
    assert typed.reference.id == "character-1"
    assert typed.reference.kind == DomainKind.CHARACTER
    assert typed.state.current_location is not None
    assert typed.state.current_location.id == "location-1"
    assert typed.state.current_location.kind == DomainKind.LOCATION
    assert entity_to_projection(typed) == raw


def test_location_round_trip_and_parent_reference() -> None:
    raw = {
        "id": "location-2",
        "kind": "location",
        "name": "Gatehouse",
        "aliases": [],
        "tags": ["fortified"],
        "state": {
            "description": "The old northern gate.",
            "parent_location_id": "location-1",
            "exposure": "outdoor",
            "x": None,
            "y": 9.5,
            "enabled": True,
            "custom_plugin_state": {"encounter_table": "gate"},
        },
        "custom_projection_field": ["preserved"],
    }

    typed = entity_from_projection(raw)

    assert isinstance(typed, Location)
    assert typed.state.parent_location is not None
    assert typed.state.parent_location.id == "location-1"
    assert typed.state.parent_location.kind == DomainKind.LOCATION
    assert entity_to_projection(typed) == raw


def test_weather_record_round_trip_preserves_json_and_extra_columns() -> None:
    row = {
        "id": "weather-1",
        "project_id": "project-1",
        "name": "Rain",
        "description": "Steady rain",
        "imagegen_description": "Wet streets and silver clouds",
        "tags_json": '["wet", "cool"]',
        "image_tags_json": '["rain"]',
        "enabled": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "provider_metadata": {"seed": 4},
    }

    typed = weather_from_record(row)
    restored = weather_to_record(typed)

    assert typed.reference.kind == DomainKind.WEATHER
    assert json.loads(restored.pop("tags_json")) == json.loads(
        row["tags_json"]
    )
    assert json.loads(restored.pop("image_tags_json")) == json.loads(
        row["image_tags_json"]
    )
    expected = dict(row)
    expected.pop("tags_json")
    expected.pop("image_tags_json")
    assert restored == expected


def test_stat_and_ability_records_round_trip_semantically() -> None:
    stat_row = {
        "id": "stat-1",
        "project_id": "project-1",
        "stat_key": "stamina",
        "label": "Stamina",
        "scope": "character",
        "default_value": 100.0,
        "minimum": 0.0,
        "maximum": 100.0,
        "integer_only": 1,
        "visibility": "public",
        "created_at": "created",
        "updated_at": "updated",
    }
    ability_row = {
        "id": "ability-1",
        "project_id": "project-1",
        "ability_key": "power_strike",
        "name": "Power Strike",
        "description": "Spend stamina to strike.",
        "target_type": "character",
        "requirements_json": '{"min_stats":{"stamina":10},"plugin_gate":"ready"}',
        "costs_json": '{"stamina":10}',
        "effects_json": '[{"target":"target","stat_key":"hp","operation":"subtract","amount":12,"plugin_effect":"impact"}]',
        "minigame_profile_json": '{"timed_attack":{"line_count":2,"damage_per_line":6}}',
        "created_at": "created",
        "updated_at": "updated",
    }

    stat = stat_from_record(stat_row)
    ability = ability_from_record(ability_row)
    restored_stat = stat_to_record(stat)
    restored_ability = ability_to_record(ability)

    assert restored_stat == stat_row
    assert stat.reference.kind == DomainKind.STAT
    assert ability.reference.kind == DomainKind.ABILITY
    for field in (
        "requirements_json",
        "costs_json",
        "effects_json",
        "minigame_profile_json",
    ):
        assert json.loads(restored_ability.pop(field)) == json.loads(
            ability_row[field]
        )
    expected_ability = dict(ability_row)
    for field in (
        "requirements_json",
        "costs_json",
        "effects_json",
        "minigame_profile_json",
    ):
        expected_ability.pop(field)
    assert restored_ability == expected_ability


@pytest.mark.parametrize(
    ("adapter", "field"),
    [
        (weather_from_record, "tags_json"),
        (ability_from_record, "requirements_json"),
        (ability_from_record, "effects_json"),
    ],
)
def test_record_adapters_reject_malformed_json(adapter, field: str) -> None:
    if adapter is weather_from_record:
        row = {
            "id": "weather-1",
            "project_id": "project-1",
            "name": "Rain",
            "tags_json": "{broken",
            "image_tags_json": "[]",
        }
    else:
        row = {
            "id": "ability-1",
            "project_id": "project-1",
            "ability_key": "strike",
            "name": "Strike",
            "requirements_json": "{}",
            "costs_json": "{}",
            "effects_json": "[]",
            "minigame_profile_json": "{}",
        }
        row[field] = "{broken"

    with pytest.raises(DomainAdapterError, match=field):
        adapter(row)


def test_domain_models_reject_invalid_identity_kind_and_known_fields() -> None:
    with pytest.raises(ValidationError, match="domain id must not be blank"):
        Character.model_validate(
            {"id": " ", "kind": "character", "name": "Mara"}
        )
    with pytest.raises(ValidationError, match="literal_error"):
        Character.model_validate(
            {"id": "location-1", "kind": "location", "name": "Gate"}
        )
    with pytest.raises(ValidationError, match="quantity"):
        Character.model_validate(
            {
                "id": "character-1",
                "kind": "character",
                "name": "Mara",
                "state": {
                    "inventory": [
                        {"item_id": "item-1", "quantity": "not-a-number"}
                    ]
                },
            }
        )


def test_world_engine_typed_entity_is_branch_aware_and_read_only(
    tmp_path: Path,
) -> None:
    db, project, world = setup_world(tmp_path)
    character_id = create(
        world,
        project["id"],
        kind="character",
        name="Mara",
        aliases=[],
        tags=[],
        state={"wardrobe": "blue coat"},
    )
    fork = db.create_story_node(project["id"], None, "user", "Choose")
    left = world.normalize_mutations(
        project["id"],
        fork["id"],
        [{
            "tool": "updateEntity",
            "arguments": {
                "entity_id": character_id,
                "patch": {"wardrobe": "red armor"},
            },
        }],
    )
    left_node, _ = world.commit_story_turn(
        project["id"],
        fork["id"],
        "Left",
        left,
        pov_character_id=None,
        narration_mode="third_omniscient",
    )
    right = world.normalize_mutations(
        project["id"],
        fork["id"],
        [{
            "tool": "updateEntity",
            "arguments": {
                "entity_id": character_id,
                "patch": {"wardrobe": "green cloak"},
            },
        }],
    )
    right_node, _ = world.commit_story_turn(
        project["id"],
        fork["id"],
        "Right",
        right,
        pov_character_id=None,
        narration_mode="third_omniscient",
    )

    left_projection = world.projection(project["id"], left_node["id"])
    before = copy.deepcopy(left_projection)
    left_character = world.typed_entity(
        project["id"],
        character_id,
        left_node["id"],
    )
    right_character = world.typed_entity(
        project["id"],
        character_id,
        right_node["id"],
    )

    assert isinstance(left_character, Character)
    assert isinstance(right_character, Character)
    assert left_character.state.wardrobe == "red armor"
    assert right_character.state.wardrobe == "green cloak"
    assert entity_to_projection(left_character) == before["entities"][character_id]
    assert world.projection(project["id"], left_node["id"]) == before


def test_environment_scene_uses_typed_views_without_changing_payload(
    tmp_path: Path,
) -> None:
    _, project, world = setup_world(tmp_path)
    environment = EnvironmentService(world.db)
    environment.ensure_project(project["id"])
    location_id = create(
        world,
        project["id"],
        kind="location",
        name="Harbor",
        aliases=[],
        tags=["coastal"],
        state={
            "description": "A sheltered harbor.",
            "exposure": "outdoor",
            "custom_plugin_state": {"district": 2},
        },
    )
    character_id = create(
        world,
        project["id"],
        kind="character",
        name="Mara",
        aliases=[],
        tags=[],
        state={
            "player_controlled": True,
            "current_location_id": location_id,
        },
    )
    scene_mutation = world.normalize_mutations(
        project["id"],
        None,
        [{
            "tool": "setSceneEnvironment",
            "arguments": {
                "focused_character_id": character_id,
                "player_action": "standing",
            },
        }],
        provenance="author",
    )
    world.commit_root(
        project["id"],
        scene_mutation,
        provenance="author",
        summary="scene",
    )
    projection = world.projection(project["id"])
    before = copy.deepcopy(projection)

    focus, location = environment.location_models(projection)
    raw_weather = environment._weather(project["id"], projection)
    weather = environment.weather_model(project["id"], raw_weather)
    scene = environment.scene(project["id"], projection)

    class SilentSound:
        def resolve_ambient(self, **_kwargs):
            return []

    class SilentMusic:
        def project_state(self, _project_id, *, head_node_id=None):
            return {"mode": "disabled", "head_node_id": head_node_id}

    managed_scene = EnvironmentManager(
        world.db,
        world,
        environment_service=environment,
        sound_manager=SilentSound(),
        music_manager=SilentMusic(),
    ).scene(project["id"], projection)

    assert isinstance(focus, Character) and focus.id == character_id
    assert isinstance(location, Location) and location.id == location_id
    assert isinstance(weather, Weather)
    assert weather.project_id == project["id"]
    assert scene["focused_character"] == {
        "id": character_id,
        "name": "Mara",
    }
    assert scene["location"] == {
        "id": location_id,
        "name": "Harbor",
        "description": "A sheltered harbor.",
        "tags": ["coastal"],
        "exposure": "outdoor",
        "parent_location_id": None,
    }
    assert scene["weather"] == raw_weather
    for key in (
        "focused_character",
        "player_action",
        "location",
        "location_ancestry",
        "weather",
        "time_phase",
        "allowed_next_weather",
        "background",
    ):
        assert managed_scene[key] == scene[key]
    assert managed_scene["ambient"] == []
    assert managed_scene["music"]["mode"] == "disabled"
    assert projection == before


def test_context_package_uses_typed_character_state_without_shape_changes(
    tmp_path: Path,
) -> None:
    _, project, world = setup_world(tmp_path)
    location_id = create(
        world,
        project["id"],
        kind="location",
        name="Library",
        aliases=[],
        tags=[],
        state={"description": "A quiet archive."},
    )
    pov_id = create(
        world,
        project["id"],
        kind="character",
        name="Mara",
        aliases=[],
        tags=[],
        state={
            "player_controlled": True,
            "current_location_id": location_id,
            "character_secrets": ["Mara forged the map"],
            "secrets_to_character": ["The archive is alive"],
            "custom_plugin_state": {"memory_rank": 4},
        },
    )
    companion_id = create(
        world,
        project["id"],
        kind="character",
        name="Ivo",
        aliases=[],
        tags=[],
        state={"current_location_id": location_id},
    )
    projection = world.projection(project["id"])
    before = copy.deepcopy(projection)

    package = world.context_package(
        project["id"],
        None,
        "Look around",
        pov_id,
        "third_limited",
        4000,
    )

    by_id = {item["id"]: item for item in package["entities"]}
    assert {pov_id, location_id, companion_id}.issubset(by_id)
    assert by_id[pov_id]["state"]["custom_plugin_state"] == {
        "memory_rank": 4
    }
    assert "character_secrets" not in by_id[pov_id]["state"]
    assert "secrets_to_character" not in by_id[pov_id]["state"]
    assert package["narrative_secrets"] == [{
        "character_id": pov_id,
        "character_name": "Mara",
        "secret": "The archive is alive",
        "known_to_character": False,
    }]
    assert projection == before
