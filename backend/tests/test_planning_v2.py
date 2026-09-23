from pathlib import Path

import pytest

from app.database import Database
from app.services.planning import PlanningService
from app.services.planningWorkspace import PlanningWorkspaceService
from app.services.planning_v2 import compact_schema, empty_draft, merge_generated_batch
from app.services.world import WorldEngine, WorldValidationError


def setup(tmp_path: Path):
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Planning semantics")
    world = WorldEngine(db)
    planning = PlanningService(db, world)
    workspace = PlanningWorkspaceService(db, world=world)
    plan = workspace.create(project["id"], {})
    return db, project, world, planning, workspace, plan


def test_workspace_projects_eight_generation_tasks(tmp_path: Path) -> None:
    _db, _project, _world, _planning, workspace, plan = setup(tmp_path)
    view = workspace.view(plan["id"])

    assert view["schema_version"] == 3
    assert len(view["tasks"]) == 8
    assert view["tasks"][0]["status"] == "ready"
    assert all(
        stage["status"] == "pending"
        for stage in view["tasks"][1:]
    )


def test_runtime_catalog_ids_rejected_before_world_commit(tmp_path: Path) -> None:
    db, project, _world, planning, _workspace, plan = setup(tmp_path)
    draft = {
        **empty_draft(7),
        "music": {
            "mode": "player_managed",
            "enabled_theme_ids": ["invented"],
            "manual_theme_id": None,
        },
    }
    before = db.fetch_one(
        "SELECT COUNT(*) count FROM world_transactions WHERE project_id=?",
        (project["id"],),
    )["count"]

    with pytest.raises(WorldValidationError, match="unavailable themes"):
        planning.publish(plan["id"], 7, draft)

    after = db.fetch_one(
        "SELECT COUNT(*) count FROM world_transactions WHERE project_id=?",
        (project["id"],),
    )["count"]
    assert after == before


def test_ability_validation_names_ability_and_missing_stats(tmp_path: Path) -> None:
    _db, _project, _world, planning, _workspace, plan = setup(tmp_path)
    draft = {
        **empty_draft(4),
        "stats": [
            {"key": "hp", "stat_key": "hp", "label": "Health"},
        ],
        "abilities": [
            {
                "key": "fireball",
                "ability_key": "fireball",
                "name": "Fireball",
                "costs": {"mp": 5},
                "effects": [
                    {
                        "stat_key": "burn",
                        "operation": "add",
                        "amount": 1,
                    }
                ],
            }
        ],
    }

    with pytest.raises(
        WorldValidationError,
        match=r"Ability 'Fireball'.*burn, mp.*Available stat keys: hp",
    ):
        planning.publish(plan["id"], 4, draft)


def test_ability_validation_rejects_unsupported_shape(tmp_path: Path) -> None:
    _db, _project, _world, planning, _workspace, plan = setup(tmp_path)
    draft = {
        **empty_draft(4),
        "abilities": [
            {
                "key": "attack",
                "name": "Attack",
                "target": "enemy",
                "cost": {"stamina": 10},
                "effect": {"damage": "atk"},
            }
        ],
    }

    with pytest.raises(
        WorldValidationError,
        match=r"'target'.*target_type.*'cost'.*costs.*'effect'.*effects",
    ):
        planning.publish(plan["id"], 4, draft)


def test_manual_change_requires_explicit_reconciliation(tmp_path: Path) -> None:
    _db, project, world, planning, _workspace, plan = setup(tmp_path)
    draft = {
        **empty_draft(2),
        "locations": [
            {
                "key": "town",
                "name": "Town",
                "state": {
                    "description": "planned",
                    "planning_tier": "major",
                },
            }
        ],
    }
    planning.publish(plan["id"], 2, draft)
    town = next(
        iter(world.projection(project["id"], use_cache=False)["entities"].values())
    )

    mutation = world.normalize_mutations(
        project["id"],
        None,
        [
            {
                "tool": "updateEntity",
                "arguments": {
                    "entity_id": town["id"],
                    "patch": {"description": "manual"},
                },
            }
        ],
        provenance="author",
    )
    world.commit_root(
        project["id"],
        mutation,
        provenance="author",
        summary="Manual edit",
    )

    conflicts = planning.preflight(plan["id"], 2, draft)
    assert conflicts[0]["proposed"]["_planning_conflict"] == "manual_change"

    planning.publish(
        plan["id"],
        2,
        draft,
        {"town": {"action": "keep_manual"}},
    )
    assert (
        world.projection(project["id"], use_cache=False)["entities"][town["id"]]
        ["state"]["description"]
        == "manual"
    )


def test_world_and_direct_domain_writes_roll_back_together(tmp_path: Path) -> None:
    db, project, world, planning, _workspace, plan = setup(tmp_path)
    draft = {
        **empty_draft(2),
        "locations": [
            {
                "key": "lost_city",
                "name": "Lost City",
                "state": {"planning_tier": "major"},
            }
        ],
        "weather": [
            {"key": "storm", "name": "Storm", "enabled": False},
        ],
        "initial_weather_key": "storm",
    }

    with pytest.raises(
        WorldValidationError,
        match="Initial weather must be enabled",
    ):
        planning.publish(plan["id"], 2, draft)

    assert not world.projection(project["id"], use_cache=False)["entities"]
    assert not db.fetch_one(
        "SELECT id FROM weather_definitions "
        "WHERE project_id=? AND name='Storm'",
        (project["id"],),
    )


def test_incremental_batches_preserve_records_and_fill_character_details() -> None:
    systems = {
        **empty_draft(4),
        "stats": [
            {"key": "hp", "stat_key": "hp", "label": "Health"},
        ],
    }
    merged = merge_generated_batch(
        4,
        systems,
        {
            "summary": "More rules",
            "notes": [],
            "stats": [
                {"key": "mana", "stat_key": "mana", "label": "Mana"},
                {"key": "hp", "stat_key": "hp", "label": "Replacement"},
            ],
        },
        "stats",
    )
    assert [item["stat_key"] for item in merged["stats"]] == ["hp", "mana"]
    assert merged["stats"][0]["label"] == "Health"

    details = {
        **empty_draft(6),
        "character_updates": [
            {
                "key": "mara",
                "name": "Mara",
                "state": {"appearance": "red hair"},
            }
        ],
    }
    enriched = merge_generated_batch(
        6,
        details,
        {
            "summary": "Secrets",
            "notes": [],
            "character_updates": [
                {
                    "key": "mara",
                    "name": "Mara",
                    "state": {
                        "appearance": "blue hair",
                        "character_secrets": ["She hid the key"],
                        "secrets_to_character": ["Her mentor lives"],
                    },
                }
            ],
        },
        "character_updates",
    )
    assert enriched["character_updates"][0]["state"]["appearance"] == "red hair"
    assert enriched["character_updates"][0]["state"]["character_secrets"] == [
        "She hid the key"
    ]


def test_cast_schema_and_publication_preserve_complete_profile(
    tmp_path: Path,
) -> None:
    schema_state = compact_schema(5, "characters")["characters"][0]["state"]
    assert {
        "description",
        "identity",
        "pronouns",
        "appearance",
        "personality",
        "goals",
    } <= set(schema_state)

    _db, project, world, planning, _workspace, plan = setup(tmp_path)
    profile = {
        "description": "A patient courier caught between two rival cities.",
        "identity": "Twenty-four-year-old mountain courier.",
        "pronouns": "she/her",
        "appearance": (
            "Short, wind-burned, with black curls and a scarred left hand."
        ),
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

    planning.publish(
        plan["id"],
        5,
        {
            **empty_draft(5),
            "characters": [
                {
                    "key": "mara",
                    "name": "Mara",
                    "aliases": [],
                    "tags": ["courier"],
                    "state": profile,
                }
            ],
        },
    )

    mara = next(
        entity
        for entity in world.projection(
            project["id"],
            use_cache=False,
        )["entities"].values()
        if entity["name"] == "Mara"
    )
    for field, value in profile.items():
        assert mara["state"][field] == value
