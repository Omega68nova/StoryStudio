from __future__ import annotations

import pytest

from app.domain.adapters import relationship_from_projection, relationship_to_projection
from app.domain.operations import DomainOperationError, StatAdjustmentExecutor
from app.domain.world import DomainKind, Relationship, Stat


def test_relationship_projection_round_trip_preserves_extension_fields() -> None:
    raw = {
        "id": "relation-1",
        "source_id": "character-1",
        "target_id": "character-2",
        "relation": "trust",
        "bidirectional": True,
        "stats": {"trust": 4},
        "plugin_relation": {"tone": "warm"},
    }
    typed = relationship_from_projection(raw)
    assert isinstance(typed, Relationship)
    assert typed.reference.kind == DomainKind.RELATIONSHIP
    assert typed.source.kind == DomainKind.CHARACTER
    assert typed.target.kind == DomainKind.CHARACTER
    assert relationship_to_projection(typed) == raw


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

    def lookup(key: str, owner_kind: str) -> Stat:
        return Stat.model_validate({
            "project_id": "project-1",
            "stat_key": key,
            "label": key.title(),
            "compatible_owner_kinds": [owner_kind],
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
