from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.database import Database
from app.domain.adapters import outfit_from_record, outfit_to_record, stat_from_record
from app.domain.world import Character, DomainKind, Stat, resolve_stat_bounds
from app.services.planning_v2 import compact_schema
from app.services.world import WorldEngine


def test_character_legacy_fields_normalize_to_canonical_contract() -> None:
    character = Character.model_validate({
        "id": "character-1",
        "kind": "character",
        "name": "Mara",
        "state": {
            "identity": "Courier from the northern coast.",
            "core_personality": "Quiet but stubborn.",
            "wardrobe": "Usually wears a weathered coat.",
            "secrets": "The map is forged.",
        },
    })

    assert character.state.description == "Courier from the northern coast."
    assert character.state.personality == "Quiet but stubborn."
    assert character.state.wardrobe_notes == "Usually wears a weathered coat."
    assert character.state.secrets_to_character == ["The map is forged."]

    # Old readers still work, but canonical serialization no longer owns
    # duplicate legacy keys.
    assert character.state.identity == character.state.description
    assert character.state.core_personality == character.state.personality
    assert character.state.wardrobe == character.state.wardrobe_notes
    dumped = character.model_dump(mode="json")
    assert "identity" not in dumped["state"]
    assert "core_personality" not in dumped["state"]
    assert "wardrobe" not in dumped["state"]
    assert "secrets" not in dumped["state"]


def test_outfit_round_trip_has_semantic_and_image_descriptions() -> None:
    row = {
        "id": "outfit-1",
        "entity_id": "character-1",
        "name": "Rain coat",
        "description": "Practical wet-weather clothing.",
        "imagegen_description": "Long yellow oilskin coat, brass clasps.",
        "equipment_json": '["lantern"]',
        "created_at": "created",
        "updated_at": "updated",
    }
    outfit = outfit_from_record(row)

    assert outfit.description == "Practical wet-weather clothing."
    assert outfit.imagegen_description.startswith("Long yellow")
    assert outfit.reference.kind == DomainKind.OUTFIT
    assert outfit_to_record(outfit) == row


def test_stat_dynamic_bounds_resolve_from_live_values() -> None:
    maximum = Stat.model_validate({
        "id": "stat-max-hp",
        "project_id": "project",
        "stat_key": "max_hp",
        "label": "Maximum Health",
        "default_value": 100,
        "minimum": 1,
        "maximum": 999,
    })
    health = Stat.model_validate({
        "id": "stat-hp",
        "project_id": "project",
        "stat_key": "hp",
        "label": "Health",
        "description": "Current physical health.",
        "default_value": 100,
        "minimum": 0,
        "maximum": 100,
        "maximum_stat_key": "max_hp",
        "display_style": "bar",
        "color": "#00aa00",
        "minimum_color": "#aa0000",
    })

    by_key = {"max_hp": maximum, "hp": health}
    bounds = resolve_stat_bounds(
        health,
        {"hp": 80, "max_hp": 125},
        lambda key, _scope: by_key[key],
    )

    assert bounds.minimum == 0
    assert bounds.maximum == 125
    assert bounds.maximum_stat_key == "max_hp"


def test_stat_cannot_reference_itself_as_bound() -> None:
    with pytest.raises(ValidationError, match="itself"):
        Stat.model_validate({
            "id": "stat-hp",
            "project_id": "project",
            "stat_key": "hp",
            "label": "Health",
            "maximum_stat_key": "hp",
        })


def test_world_effective_stats_use_dynamic_bounds(tmp_path: Path) -> None:
    db = Database(tmp_path / "data")
    db.initialize()
    project = db.create_project("Dynamic bounds")
    now = "now"
    db.execute(
        "INSERT INTO stat_definitions("
        "id,project_id,stat_key,label,description,scope,default_value,"
        "minimum,maximum,minimum_stat_key,maximum_stat_key,color,"
        "minimum_color,maximum_color,display_style,integer_only,visibility,"
        "created_at,updated_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "max-hp",
            project["id"],
            "max_hp",
            "Maximum Health",
            "",
            "character",
            100,
            1,
            999,
            None,
            None,
            None,
            None,
            None,
            "compact",
            1,
            "public",
            now,
            now,
        ),
    )
    db.execute(
        "INSERT INTO stat_definitions("
        "id,project_id,stat_key,label,description,scope,default_value,"
        "minimum,maximum,minimum_stat_key,maximum_stat_key,color,"
        "minimum_color,maximum_color,display_style,integer_only,visibility,"
        "created_at,updated_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "hp",
            project["id"],
            "hp",
            "Health",
            "",
            "character",
            100,
            0,
            100,
            None,
            "max_hp",
            None,
            None,
            None,
            "bar",
            1,
            "public",
            now,
            now,
        ),
    )

    values = WorldEngine(db).effective_stats(
        project["id"],
        {"stats": {"hp": 140, "max_hp": 75}, "active_effects": []},
    )

    assert values["max_hp"] == 75
    assert values["hp"] == 75


def test_migration_exposes_new_stat_and_outfit_columns(tmp_path: Path) -> None:
    db = Database(tmp_path / "data")
    db.initialize()
    stat_columns = {
        row["name"] for row in db.fetch_all("PRAGMA table_info(stat_definitions)")
    }
    outfit_columns = {
        row["name"] for row in db.fetch_all("PRAGMA table_info(entity_outfits)")
    }

    assert {
        "description",
        "minimum_stat_key",
        "maximum_stat_key",
        "color",
        "minimum_color",
        "maximum_color",
        "display_style",
    } <= stat_columns
    assert "imagegen_description" in outfit_columns


def test_planning_schema_targets_canonical_character_and_outfit_fields() -> None:
    cast = compact_schema(5)
    state = cast["characters"][0]["state"]
    assert "description" in state
    assert "imagegen_description" in state
    assert "identity" not in state

    details = compact_schema(6)
    update = details["character_updates"][0]["state"]
    assert "wardrobe_notes" in update
    assert "wardrobe" not in update
    outfit = details["outfits"][0]
    assert "description" in outfit
    assert "imagegen_description" in outfit


def test_stat_adapter_reads_new_metadata() -> None:
    row = {
        "id": "stat-hp",
        "project_id": "project",
        "stat_key": "hp",
        "label": "Health",
        "description": "Current health.",
        "scope": "character",
        "default_value": 100,
        "minimum": 0,
        "maximum": 100,
        "minimum_stat_key": None,
        "maximum_stat_key": "max_hp",
        "color": "#00aa00",
        "minimum_color": "#aa0000",
        "maximum_color": None,
        "display_style": "bar",
        "integer_only": 1,
        "visibility": "public",
        "created_at": "created",
        "updated_at": "updated",
    }
    stat = stat_from_record(row)
    assert stat.description == "Current health."
    assert stat.maximum_stat_key == "max_hp"
    assert stat.display_style == "bar"
    assert stat.integer_only is True
