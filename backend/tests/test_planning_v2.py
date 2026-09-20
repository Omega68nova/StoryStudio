from pathlib import Path

import pytest

from app.database import Database
from app.services.planning import PlanningService
from app.services.planning_v2 import compact_schema, empty_draft, merge_generated_batch
from app.services.world import WorldEngine, WorldValidationError


def setup(tmp_path: Path):
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Eight stages")
    world = WorldEngine(db)
    return db, project, world, PlanningService(db, world)


def test_v2_session_defaults_and_skip_are_persistent(tmp_path: Path) -> None:
    db, project, _world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})

    assert session["schema_version"] == 2
    assert session["settings"]["scale_preset"] == "local"
    assert len(session["stages"]) == 8
    skipped = planning.skip_stage(session["id"], 1)
    assert skipped["stages"][0]["status"] == "skipped"

    # Startup repair must not turn an explicit skip into an approval.
    db.initialize()
    assert planning.get_session(session["id"])["stages"][0]["status"] == "skipped"


def test_redo_preserves_stable_ids_and_stales_only_dependencies(tmp_path: Path) -> None:
    _db, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    planning.skip_stage(session["id"], 1)
    macro = {
        **empty_draft(2),
        "locations": [{"key": "town", "name": "Old Town", "tags": ["urban"], "state": {"description": "Original", "planning_tier": "major", "important": True}}],
    }
    planning.approve_stage(session["id"], 2, macro)
    planning.approve_stage(session["id"], 3, empty_draft(3))
    planning.approve_stage(session["id"], 4, empty_draft(4))
    before = planning.get_session(session["id"])
    town_id = next(entity["id"] for entity in world.projection(project["id"], use_cache=False)["entities"].values() if entity["name"] == "Old Town")

    planning.reopen_stage(session["id"], 2)
    macro["locations"][0]["name"] = "New Town"
    macro["locations"][0]["state"]["description"] = "Revised"
    planning.approve_stage(session["id"], 2, macro)
    after = planning.get_session(session["id"])
    projection = world.projection(project["id"], use_cache=False)

    assert projection["entities"][town_id]["name"] == "New Town"
    assert before["stages"][1]["approved_revision_hash"] != after["stages"][1]["approved_revision_hash"]
    assert after["stages"][2]["status"] == "stale"
    assert after["stages"][3]["status"] == "approved"


def test_runtime_catalog_ids_rejected_before_world_commit(tmp_path: Path) -> None:
    db, project, _world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    for stage in range(1, 7):
        planning.skip_stage(session["id"], stage)
    draft = {**empty_draft(7), "music": {"mode": "player_managed", "enabled_theme_ids": ["invented"], "manual_theme_id": None}}
    before = db.fetch_one("SELECT COUNT(*) count FROM world_transactions WHERE project_id=?", (project["id"],))["count"]

    with pytest.raises(WorldValidationError, match="unavailable themes"):
        planning.approve_stage(session["id"], 7, draft)

    after = db.fetch_one("SELECT COUNT(*) count FROM world_transactions WHERE project_id=?", (project["id"],))["count"]
    assert after == before


def test_ability_validation_names_ability_and_missing_stats(tmp_path: Path) -> None:
    _db, project, _world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    for stage in range(1, 4):
        planning.skip_stage(session["id"], stage)
    draft = {
        **empty_draft(4),
        "stats": [{"key": "hp", "stat_key": "hp", "label": "Health"}],
        "abilities": [{"key": "fireball", "ability_key": "fireball", "name": "Fireball", "costs": {"mp": 5}, "effects": [{"stat_key": "burn", "operation": "add", "amount": 1}]}],
    }

    with pytest.raises(WorldValidationError, match=r"Ability 'Fireball'.*burn, mp.*Available stat keys: hp"):
        planning.approve_stage(session["id"], 4, draft)


def test_ability_validation_rejects_ai_friendly_but_unsupported_shape(tmp_path: Path) -> None:
    _db, project, _world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    for stage in range(1, 4):
        planning.skip_stage(session["id"], stage)
    draft = {
        **empty_draft(4),
        "abilities": [{"key": "attack", "name": "Attack", "target": "enemy", "cost": {"stamina": 10}, "effect": {"damage": "atk"}}],
    }

    with pytest.raises(WorldValidationError, match=r"'target'.*target_type.*'cost'.*costs.*'effect'.*effects"):
        planning.approve_stage(session["id"], 4, draft)


def test_manual_change_requires_explicit_reconciliation(tmp_path: Path) -> None:
    _db, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    planning.skip_stage(session["id"], 1)
    draft = {**empty_draft(2), "locations": [{"key": "town", "name": "Town", "state": {"description": "planned", "planning_tier": "major"}}]}
    planning.approve_stage(session["id"], 2, draft)
    town = next(iter(world.projection(project["id"], use_cache=False)["entities"].values()))
    mutation = world.normalize_mutations(project["id"], None, [{"tool": "updateEntity", "arguments": {"entity_id": town["id"], "patch": {"description": "manual"}}}], provenance="author")
    world.commit_root(project["id"], mutation, provenance="author", summary="Manual edit")
    planning.reopen_stage(session["id"], 2)

    conflicts = planning.preflight(session["id"], 2, draft)
    assert conflicts[0]["proposed"]["_planning_conflict"] == "manual_change"
    planning.approve_stage(session["id"], 2, draft, {"town": {"action": "keep_manual"}})
    assert world.projection(project["id"], use_cache=False)["entities"][town["id"]]["state"]["description"] == "manual"


def test_world_and_direct_stage_writes_roll_back_together(tmp_path: Path) -> None:
    db, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    planning.skip_stage(session["id"], 1)
    draft = {
        **empty_draft(2),
        "locations": [{"key": "lost_city", "name": "Lost City", "state": {"planning_tier": "major"}}],
        "weather": [{"key": "storm", "name": "Storm", "enabled": False}],
        "initial_weather_key": "storm",
    }

    with pytest.raises(WorldValidationError, match="Initial weather must be enabled"):
        planning.approve_stage(session["id"], 2, draft)

    assert not world.projection(project["id"], use_cache=False)["entities"]
    assert not db.fetch_one("SELECT id FROM weather_definitions WHERE project_id=? AND name='Storm'", (project["id"],))


def test_incremental_batches_preserve_records_and_fill_character_details() -> None:
    systems = {**empty_draft(4), "stats": [{"key": "hp", "stat_key": "hp", "label": "Health"}]}
    merged = merge_generated_batch(4, systems, {"summary": "More rules", "notes": [], "stats": [{"key": "mana", "stat_key": "mana", "label": "Mana"}, {"key": "hp", "stat_key": "hp", "label": "Replacement"}]}, "stats")
    assert [item["stat_key"] for item in merged["stats"]] == ["hp", "mana"]
    assert merged["stats"][0]["label"] == "Health"

    details = {**empty_draft(6), "character_updates": [{"key": "mara", "name": "Mara", "state": {"appearance": "red hair"}}]}
    enriched = merge_generated_batch(6, details, {"summary": "Secrets", "notes": [], "character_updates": [{"key": "mara", "name": "Mara", "state": {"appearance": "blue hair", "character_secrets": ["She hid the key"], "secrets_to_character": ["Her mentor lives"]}}]}, "character_updates")
    assert enriched["character_updates"][0]["state"]["appearance"] == "red hair"
    assert enriched["character_updates"][0]["state"]["character_secrets"] == ["She hid the key"]


def test_cast_schema_and_approval_preserve_complete_character_profile(tmp_path: Path) -> None:
    schema_state = compact_schema(5, "characters")["characters"][0]["state"]
    assert {"description", "identity", "pronouns", "appearance", "personality", "goals"} <= set(schema_state)

    _db, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    for stage_number in range(1, 5):
        planning.skip_stage(session["id"], stage_number)
    profile = {
        "description": "A patient courier caught between two rival cities.",
        "identity": "Twenty-four-year-old mountain courier.",
        "pronouns": "she/her",
        "appearance": "Short, wind-burned, with black curls and a scarred left hand.",
        "personality": "Observant and kind, but stubborn when challenged.",
        "goals": ["Reconnect the mountain settlements"],
        "secrets": "She once carried a forged peace treaty.",
        "character_secrets": ["She knows the northern pass is still open"],
        "secrets_to_character": ["Her missing mentor leads the rival couriers"],
        "cast_role": "active_npc",
        "player_controlled": False,
        "autonomy_enabled": True,
        "intervention_frequency": "normal",
    }
    planning.approve_stage(session["id"], 5, {
        **empty_draft(5),
        "characters": [{"key": "mara", "name": "Mara", "aliases": [], "tags": ["courier"], "state": profile}],
    })

    mara = next(entity for entity in world.projection(project["id"], use_cache=False)["entities"].values() if entity["name"] == "Mara")
    for field, value in profile.items():
        assert mara["state"][field] == value


def test_accepted_batch_is_canonical_and_cleared_without_future_regeneration_deleting_it(tmp_path: Path) -> None:
    _db, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    planning.skip_stage(session["id"], 1)
    draft = {
        **empty_draft(2),
        "locations": [{"key": "harbor", "name": "Harbor", "state": {"planning_tier": "major", "description": "Old docks"}}],
    }

    planning.accept_stage_batch(session["id"], 2, "locations", draft)
    saved = planning.get_session(session["id"])["stages"][1]
    harbor = next(entity for entity in world.projection(project["id"], use_cache=False)["entities"].values() if entity["name"] == "Harbor")
    assert saved["status"] == "ready" and saved["draft"]["locations"] == []

    # Saving or regenerating an empty editor section cannot remove an accepted canonical record.
    planning.save_draft(saved["id"], saved["draft"])
    assert world.projection(project["id"], use_cache=False)["entities"][harbor["id"]]["name"] == "Harbor"
    inventory = planning.world_inventory(project["id"], session_id=session["id"])
    assert any(item["id"] == "harbor" and item["name"] == "Harbor" for item in inventory)


def test_stage_four_saves_stats_before_abilities_and_lore_has_description(tmp_path: Path) -> None:
    db, project, world, planning = setup(tmp_path)
    session = planning.create_session(project["id"], {})
    for stage_number in range(1, 4):
        planning.skip_stage(session["id"], stage_number)

    stats = {
        **empty_draft(4),
        "stats": [{
            "key": "stamina", "stat_key": "stamina", "label": "Stamina", "scope": "character",
            "default_value": 100, "minimum": 0, "maximum": 100, "integer_only": True, "visibility": "public",
        }],
    }
    planning.accept_stage_batch(session["id"], 4, "stats", stats)
    assert db.fetch_one("SELECT stat_key FROM stat_definitions WHERE project_id=?", (project["id"],))["stat_key"] == "stamina"

    abilities = {
        **empty_draft(4),
        "abilities": [{
            "key": "sprint", "ability_key": "sprint", "name": "Sprint", "description": "Run quickly.",
            "target_type": "self", "requirements": {}, "costs": {"stamina": 10},
            "effects": [{"target": "actor", "stat_key": "stamina", "operation": "subtract", "amount": 10}],
            "minigame_profile": {},
        }],
    }
    planning.accept_stage_batch(session["id"], 4, "abilities", abilities)
    assert db.fetch_one("SELECT ability_key FROM ability_definitions WHERE project_id=?", (project["id"],))["ability_key"] == "sprint"

    lore = {
        **empty_draft(4),
        "lore_systems": [{
            "key": "breath_magic", "name": "Breath Magic", "tags": ["magic"],
            "state": {"description": "Magic is shaped through controlled breathing.", "rules": [], "limits": [], "costs": [], "secrets": []},
        }],
    }
    planning.accept_stage_batch(session["id"], 4, "lore_systems", lore)
    entity = next(item for item in world.projection(project["id"], use_cache=False)["entities"].values() if item["kind"] == "lore_system")
    assert entity["state"]["description"] == "Magic is shaped through controlled breathing."

    lore["lore_systems"][0]["state"]["description"] = ""
    with pytest.raises(WorldValidationError, match="requires a description"):
        planning.accept_stage_batch(session["id"], 4, "lore_systems", lore)
