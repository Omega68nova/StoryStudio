from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.database import Database, new_id, utc_now
from app.domain.adapters import (
    relationship_from_projection,
    relationship_to_projection,
)
from app.domain.world import DomainKind, Relationship, Stat
from app.domain.operations import (
    DomainOperationError,
    StatAdjustmentExecutor,
)
from app.services.world import WorldEngine, WorldValidationError


def setup_world(path: Path) -> tuple[Database, dict, WorldEngine]:
    db = Database(path)
    db.initialize()
    project = db.create_project("Typed operations")
    return db, project, WorldEngine(db)


def create_character(
    world: WorldEngine,
    project_id: str,
    name: str,
    *,
    tags: list[str] | None = None,
    state: dict | None = None,
) -> str:
    mutations = world.normalize_mutations(
        project_id,
        None,
        [{
            "tool": "createEntity",
            "arguments": {
                "kind": "character",
                "name": name,
                "tags": tags or [],
                "state": state or {},
            },
        }],
        provenance="author",
    )
    world.commit_root(
        project_id,
        mutations,
        provenance="author",
        summary=name,
    )
    return str(mutations[0].arguments["entity_id"])


def add_stat(
    db: Database,
    project_id: str,
    key: str,
    label: str,
    *,
    scope: str = "character",
    default: float = 0,
    minimum: float = 0,
    maximum: float = 100,
) -> None:
    now = utc_now()
    db.execute(
        "INSERT INTO stat_definitions"
        "(id,project_id,stat_key,label,scope,default_value,minimum,maximum,"
        "integer_only,visibility,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,1,'public',?,?)",
        (
            new_id(),
            project_id,
            key,
            label,
            scope,
            default,
            minimum,
            maximum,
            now,
            now,
        ),
    )


def test_relationship_projection_round_trip_preserves_extension_fields() -> None:
    raw = {
        "id": "relation-1",
        "source_id": "character-1",
        "target_id": "character-2",
        "relation": "route",
        "travel_minutes": 15,
        "modes": ["walk"],
        "bidirectional": True,
        "stats": {"trust": 5},
        "active_effects": [],
        "plugin_metadata": {"road": "stone"},
    }

    relationship = relationship_from_projection(raw)

    assert isinstance(relationship, Relationship)
    assert relationship.reference.id == "relation-1"
    assert relationship.reference.kind == DomainKind.RELATIONSHIP
    assert relationship_to_projection(relationship) == raw


def test_stat_adjustment_executor_preserves_character_and_relation_shapes() -> None:
    projection = {
        "entities": {
            "character-1": {
                "id": "character-1",
                "kind": "character",
                "name": "Mara",
                "stats": {"hp": 8},
            },
        },
        "relations": {
            "relation-1": {
                "id": "relation-1",
                "source_id": "character-1",
                "target_id": "character-2",
                "relation": "trust",
                "stats": {"trust": 2},
            },
        },
    }

    def lookup(key: str, scope: str):
        return Stat.model_validate({
            "id": f"{scope}-{key}",
            "project_id": "project-1",
            "stat_key": key,
            "label": key.title(),
            "scope": scope,
            "minimum": 0,
            "maximum": 10,
            "integer_only": True,
        })

    executor = StatAdjustmentExecutor()
    assert executor.normalize(
        projection=projection,
        entity_id="character-1",
        stat_key="hp",
        operation="add",
        amount=5,
        stat_lookup=lookup,
    ) == {
        "entity_id": "character-1",
        "stat_key": "hp",
        "value": 10,
        "previous_value": 8.0,
    }
    assert executor.normalize(
        projection=projection,
        relation_id="relation-1",
        stat_key="trust",
        operation="subtract",
        amount=1,
        stat_lookup=lookup,
    )["relation_id"] == "relation-1"
    with pytest.raises(DomainOperationError, match="Stat target"):
        executor.normalize(
            projection=projection,
            entity_id="missing",
            stat_key="hp",
            operation="add",
            amount=1,
            stat_lookup=lookup,
        )


def test_typed_ability_services_preserve_normalized_payload(
    tmp_path: Path,
) -> None:
    db, project, world = setup_world(tmp_path)
    add_stat(db, project["id"], "mana", "Mana", default=20)
    add_stat(db, project["id"], "hp", "Health", default=50)
    actor_id = create_character(
        world,
        project["id"],
        "Mara",
        tags=["mage"],
        state={"abilities": ["arc_bolt"]},
    )
    target_id = create_character(
        world,
        project["id"],
        "Ivo",
    )
    now = utc_now()
    ability_id = new_id()
    db.execute(
        "INSERT INTO ability_definitions"
        "(id,project_id,ability_key,name,description,target_type,"
        "requirements_json,costs_json,effects_json,created_at,updated_at) "
        "VALUES(?,?,?,?,?,'character',?,?,?,?,?)",
        (
            ability_id,
            project["id"],
            "arc_bolt",
            "Arc Bolt",
            "A focused bolt.",
            json.dumps({"tags": ["mage"], "min_stats": {"mana": 10}}),
            json.dumps({"mana": 5}),
            json.dumps([{
                "target": "target",
                "stat_key": "hp",
                "operation": "subtract",
                "amount": 12,
            }]),
            now,
            now,
        ),
    )

    mutation = world.normalize_mutations(
        project["id"],
        None,
        [{
            "tool": "useAbility",
            "arguments": {
                "actor_id": actor_id,
                "target_id": target_id,
                "ability_key": "arc_bolt",
            },
        }],
        provenance="author",
    )[0]

    assert mutation.arguments == {
        "actor_id": actor_id,
        "target_id": target_id,
        "ability_key": "arc_bolt",
        "ability_name": "Arc Bolt",
        "costs": [{
            "entity_id": actor_id,
            "stat_key": "mana",
            "value": 15,
            "previous_value": 20.0,
        }],
        "effects": [{
            "stat_key": "hp",
            "operation": "subtract",
            "amount": 12.0,
            "previous_value": 50.0,
            "value": 38,
            "entity_id": target_id,
        }],
    }

    db.execute(
        "UPDATE ability_definitions SET requirements_json=? WHERE id=?",
        (json.dumps({"min_stats": {"mana": 25}}), ability_id),
    )
    with pytest.raises(WorldValidationError, match="Mana requirement"):
        world.normalize_mutations(
            project["id"],
            None,
            [{
                "tool": "useAbility",
                "arguments": {
                    "actor_id": actor_id,
                    "target_id": target_id,
                    "ability_key": "arc_bolt",
                },
            }],
            provenance="author",
        )


def test_typed_target_resolution_preserves_self_and_relationship_rules(
    tmp_path: Path,
) -> None:
    db, project, world = setup_world(tmp_path)
    add_stat(
        db,
        project["id"],
        "favorability",
        "Favorability",
        scope="relationship",
        default=0,
        minimum=-100,
    )
    actor_id = create_character(
        world,
        project["id"],
        "Mara",
        state={"abilities": ["focus", "charm"]},
    )
    target_id = create_character(world, project["id"], "Ivo")
    relation_id = "mara-ivo"
    relationship = world.normalize_mutations(
        project["id"],
        None,
        [{
            "tool": "setRelationship",
            "arguments": {
                "id": relation_id,
                "source_id": actor_id,
                "target_id": target_id,
                "relation": "affection",
            },
        }],
        provenance="author",
    )
    world.commit_root(
        project["id"],
        relationship,
        provenance="author",
        summary="relationship",
    )
    now = utc_now()
    db.execute(
        "INSERT INTO ability_definitions"
        "(id,project_id,ability_key,name,description,target_type,"
        "requirements_json,costs_json,effects_json,created_at,updated_at) "
        "VALUES(?,?,?,'Focus','','self','{}','{}','[]',?,?)",
        (new_id(), project["id"], "focus", now, now),
    )
    db.execute(
        "INSERT INTO ability_definitions"
        "(id,project_id,ability_key,name,description,target_type,"
        "requirements_json,costs_json,effects_json,created_at,updated_at) "
        "VALUES(?,?,?,'Charm','','relationship','{}','{}',?, ?, ?)",
        (
            new_id(),
            project["id"],
            "charm",
            json.dumps([{
                "stat_key": "favorability",
                "operation": "add",
                "amount": 5,
            }]),
            now,
            now,
        ),
    )

    with pytest.raises(WorldValidationError, match="only its actor"):
        world.normalize_mutations(
            project["id"],
            None,
            [{
                "tool": "useAbility",
                "arguments": {
                    "actor_id": actor_id,
                    "target_id": target_id,
                    "ability_key": "focus",
                },
            }],
            provenance="author",
        )

    charm = world.normalize_mutations(
        project["id"],
        None,
        [{
            "tool": "useAbility",
            "arguments": {
                "actor_id": actor_id,
                "target_id": relation_id,
                "ability_key": "charm",
            },
        }],
        provenance="author",
    )[0]
    assert charm.arguments["target_id"] == relation_id
    assert charm.arguments["effects"][0]["relation_id"] == relation_id
