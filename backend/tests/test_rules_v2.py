from __future__ import annotations

from app.domain.rules_v2 import (
    ConditionEvaluator,
    ConditionExpression,
    RuleEvaluationContext,
    RuleObjectResolver,
    RuleObjectSelector,
    ValueExpression,
    ValueExpressionEvaluator,
    condition_expression_from_requirement,
    value_expression_from_formula,
)
from app.domain.world import FormulaNode, RequirementExpression


def snapshot(object_id: str, kind: str, stats: dict[str, float], **state):
    return RuleObjectResolver.snapshot({
        "id": object_id,
        "kind": kind,
        "name": object_id,
        "stats": stats,
        "state": state,
    })


def test_value_expression_combines_actor_source_item_and_target() -> None:
    context = RuleEvaluationContext(bindings={
        "actor": snapshot("hero", "character", {"strength": 8}),
        "source": snapshot("sword", "item", {"attack": 12}),
        "target": snapshot("enemy", "character", {"armor": 5}),
    })
    expression = ValueExpression.model_validate({
        "kind": "subtract",
        "children": [
            {
                "kind": "add",
                "children": [
                    {"kind": "stat", "selector": {"kind": "source"}, "stat_key": "attack"},
                    {"kind": "stat", "selector": {"kind": "actor"}, "stat_key": "strength"},
                ],
            },
            {"kind": "stat", "selector": {"kind": "target"}, "stat_key": "armor"},
        ],
    })
    value, inputs = ValueExpressionEvaluator().evaluate(expression, context)
    assert value == 15
    assert inputs == {
        "source.attack": 12.0,
        "actor.strength": 8.0,
        "target.armor": 5.0,
    }


def test_current_location_is_a_first_class_value_source() -> None:
    projection = {
        "entities": {
            "town": {
                "id": "town",
                "kind": "location",
                "name": "Town",
                "stats": {"magic": 7},
                "state": {},
            }
        },
        "relations": {},
    }
    actor = snapshot("hero", "character", {}, current_location_id="town")
    context = RuleEvaluationContext(bindings={"actor": actor}, projection=projection)
    expression = ValueExpression.model_validate({
        "kind": "stat",
        "selector": {"kind": "current_location"},
        "stat_key": "magic",
    })
    value, inputs = ValueExpressionEvaluator().evaluate(expression, context)
    assert value == 7
    assert inputs == {"current_location.magic": 7.0}


def test_explicit_objects_can_be_used_in_conditions() -> None:
    projection = {
        "entities": {
            "altar": {
                "id": "altar",
                "kind": "lore_system",
                "name": "Altar",
                "tags": ["charged"],
                "stats": {"charge": 20},
                "state": {},
            }
        },
        "relations": {},
    }
    context = RuleEvaluationContext(projection=projection)
    condition = ConditionExpression.model_validate({
        "kind": "and",
        "children": [
            {
                "kind": "exists",
                "selector": {"kind": "explicit", "object_id": "altar", "object_kind": "lore_system"},
            },
            {
                "kind": "has_tag",
                "selector": {"kind": "explicit", "object_id": "altar", "object_kind": "lore_system"},
                "tag": "charged",
            },
            {
                "kind": "compare",
                "left": {
                    "kind": "stat",
                    "selector": {"kind": "explicit", "object_id": "altar", "object_kind": "lore_system"},
                    "stat_key": "charge",
                },
                "comparison": "gte",
                "right": {"kind": "constant", "value": 10},
            },
        ],
    })
    assert ConditionEvaluator().evaluate(condition, context)


def test_multi_target_evaluation_rebinds_target_individually() -> None:
    expression = ValueExpression.model_validate({
        "kind": "subtract",
        "children": [
            {"kind": "stat", "selector": {"kind": "source"}, "stat_key": "attack"},
            {"kind": "stat", "selector": {"kind": "target"}, "stat_key": "armor"},
        ],
    })
    source = snapshot("sword", "item", {"attack": 10})
    values = []
    for target in (
        snapshot("light", "character", {"armor": 2}),
        snapshot("heavy", "character", {"armor": 7}),
    ):
        value, _ = ValueExpressionEvaluator().evaluate(
            expression,
            RuleEvaluationContext(bindings={"source": source, "target": target}),
        )
        values.append(value)
    assert values == [8, 3]


def test_legacy_formula_adapts_to_value_expression() -> None:
    legacy = FormulaNode.model_validate({
        "kind": "multiply",
        "children": [
            {"kind": "stat", "participant": "source", "stat_key": "quality"},
            {"kind": "constant", "value": 3},
        ],
    })
    expression = value_expression_from_formula(legacy)
    value, _ = ValueExpressionEvaluator().evaluate(
        expression,
        RuleEvaluationContext(bindings={
            "source": snapshot("potion", "item", {"quality": 4}),
        }),
    )
    assert value == 12


def test_legacy_requirement_adapts_to_shared_condition_engine() -> None:
    legacy = RequirementExpression.model_validate({
        "kind": "compare",
        "target": "target",
        "stat_key": "armor",
        "comparison": "gte",
        "value": 5,
    })
    condition = condition_expression_from_requirement(legacy)
    context = RuleEvaluationContext(bindings={
        "actor": snapshot("hero", "character", {}),
        "target": snapshot("enemy", "character", {"armor": 6}),
    })
    assert ConditionEvaluator().evaluate(condition, context)


def test_stat_lookup_validates_owner_compatibility() -> None:
    expression = ValueExpression.model_validate({
        "kind": "stat",
        "selector": {"kind": "source"},
        "stat_key": "attack",
    })
    context = RuleEvaluationContext(bindings={
        "source": snapshot("wand", "item", {"attack": 5}),
    })

    def stat_lookup(key: str, owner_kind: str):
        assert key == "attack"
        if owner_kind != "item":
            return None
        return object()

    value, _ = ValueExpressionEvaluator().evaluate(
        expression,
        context,
        stat_lookup=stat_lookup,
    )
    assert value == 5


def test_runtime_condition_uses_effective_stats_and_legacy_payload() -> None:
    from types import SimpleNamespace
    from app.domain.world import Stat
    from app.services.rules import RulesRuntime

    class FakeRules:
        def __init__(self):
            self._stat = Stat.model_validate({
                "project_id": "project",
                "stat_key": "mana",
                "label": "Mana",
                "compatible_owner_kinds": ["character"],
                "default_value": 10,
                "minimum": 0,
                "maximum": 10,
            })
        def stats(self, _project_id):
            return [self._stat]
        def stat(self, _project_id, key):
            return self._stat if key == "mana" else None

    runtime = RulesRuntime(
        SimpleNamespace(rules=FakeRules()),
        lambda *_args: None,
    )
    projection = {
        "entities": {
            "hero": {
                "id": "hero",
                "kind": "character",
                "name": "Hero",
                "tags": [],
                "stats": {},
                "state": {},
            }
        },
        "relations": {},
    }
    assert runtime.evaluate_condition(
        "project",
        projection,
        {
            "schema_version": 2,
            "kind": "compare",
            "target": "actor",
            "stat_key": "mana",
            "comparison": "gte",
            "value": 10,
        },
        actor_id="hero",
    )


def test_runtime_condition_can_read_explicit_location_stats() -> None:
    from types import SimpleNamespace
    from app.domain.world import Stat
    from app.services.rules import RulesRuntime

    class FakeRules:
        def __init__(self):
            self._stat = Stat.model_validate({
                "project_id": "project",
                "stat_key": "magic",
                "label": "Magic",
                "compatible_owner_kinds": ["location"],
                "default_value": 0,
                "minimum": 0,
                "maximum": 100,
            })
        def stats(self, _project_id):
            return [self._stat]
        def stat(self, _project_id, key):
            return self._stat if key == "magic" else None

    runtime = RulesRuntime(SimpleNamespace(rules=FakeRules()), lambda *_args: None)
    projection = {
        "entities": {
            "tower": {
                "id": "tower",
                "kind": "location",
                "name": "Tower",
                "tags": [],
                "stats": {"magic": 25},
                "state": {},
            }
        },
        "relations": {},
    }
    assert runtime.evaluate_condition(
        "project",
        projection,
        {
            "kind": "compare",
            "left": {
                "kind": "stat",
                "selector": {
                    "kind": "explicit",
                    "object_id": "tower",
                    "object_kind": "location",
                },
                "stat_key": "magic",
            },
            "comparison": "gt",
            "right": {"kind": "constant", "value": 20},
        },
    )
