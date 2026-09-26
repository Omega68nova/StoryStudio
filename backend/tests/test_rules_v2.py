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


def test_generalized_stat_cost_can_charge_source_item() -> None:
    from app.domain.rules_v2 import RuleCost, RuleCostExecutor
    from app.domain.world import Stat

    durability = Stat.model_validate({
        "project_id": "project", "stat_key": "durability", "label": "Durability",
        "compatible_owner_kinds": ["item"], "default_value": 10, "minimum": 0, "maximum": 10,
    })
    context = RuleEvaluationContext(bindings={
        "source": snapshot("wand", "item", {"durability": 4}),
    })
    events = RuleCostExecutor().normalize(
        [RuleCost.model_validate({
            "owner": {"kind": "source"},
            "stat_key": "durability",
            "amount": {"kind": "constant", "value": 1},
        })],
        context,
        stat_lookup=lambda key, owner: durability if key == "durability" and owner == "item" else None,
    )
    assert events[0]["entity_id"] == "wand"
    assert events[0]["previous_value"] == 4
    assert events[0]["value"] == 3


def test_generalized_costs_are_cumulative() -> None:
    import pytest
    from app.domain.rules_v2 import RuleCost, RuleCostExecutor, RuleEvaluationError
    from app.domain.world import Stat

    mana = Stat.model_validate({
        "project_id": "project", "stat_key": "mana", "label": "Mana",
        "compatible_owner_kinds": ["location"], "default_value": 5, "minimum": 0, "maximum": 5,
    })
    context = RuleEvaluationContext(projection={"entities": {
        "shrine": {"id": "shrine", "kind": "location", "name": "Shrine", "stats": {"mana": 5}, "state": {}}
    }, "relations": {}})
    costs = [RuleCost.model_validate({
        "owner": {"kind": "explicit", "object_id": "shrine", "object_kind": "location"},
        "stat_key": "mana",
        "amount": {"kind": "constant", "value": amount},
    }) for amount in (3, 3)]
    with pytest.raises(RuleEvaluationError, match="lacks enough"):
        RuleCostExecutor().normalize(
            costs, context,
            stat_lookup=lambda key, owner: mana if key == "mana" and owner == "location" else None,
        )


def test_phase8_effect_and_rule_costs_round_trip_repository(tmp_path) -> None:
    from app.database import Database
    from app.data import DataProvider
    from app.domain.world import Ability, EffectDefinition, Stat

    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project_id = db.create_project("phase8 persistence")["id"]
    data.rules.save_stat(Stat.model_validate({
        "project_id": project_id, "stat_key": "power", "label": "Power",
        "compatible_owner_kinds": ["character", "item", "location"],
        "default_value": 0, "minimum": 0, "maximum": 100,
    }))
    data.rules.save_effect(EffectDefinition.model_validate({
        "project_id": project_id, "effect_key": "scaled", "name": "Scaled",
        "target_stat_key": "power", "formula": {"kind": "constant", "value": 1},
        "value_expression": {
            "kind": "add",
            "children": [
                {"kind": "stat", "selector": {"kind": "source"}, "stat_key": "power"},
                {"kind": "stat", "selector": {"kind": "current_location"}, "stat_key": "power"},
            ],
        },
    }))
    data.rules.save_ability(Ability.model_validate({
        "project_id": project_id, "ability_key": "channel", "name": "Channel",
        "compatible_owner_kinds": ["item"], "target_type": "character",
        "rule_costs": [{
            "owner": {"kind": "source"}, "stat_key": "power",
            "amount": {"kind": "constant", "value": 2},
        }],
        "actions": [{"kind": "apply_effect", "target": "target", "effect_key": "scaled"}],
    }))
    loaded_effect = data.rules.effect(project_id, "scaled")
    loaded_ability = data.rules.ability(project_id, "channel")
    assert loaded_effect is not None and loaded_effect.value_expression["kind"] == "add"
    assert loaded_ability is not None and loaded_ability.rule_costs[0]["owner"]["kind"] == "source"


def test_runtime_phase8_effect_uses_current_location_per_target_context() -> None:
    from types import SimpleNamespace
    from app.domain.world import EffectDefinition, Stat
    from app.services.rules import RulesRuntime

    target_stat = Stat.model_validate({
        "project_id": "project", "stat_key": "hp", "label": "HP",
        "compatible_owner_kinds": ["character"], "default_value": 10, "minimum": 0, "maximum": 100,
    })
    magic_stat = Stat.model_validate({
        "project_id": "project", "stat_key": "magic", "label": "Magic",
        "compatible_owner_kinds": ["location"], "default_value": 0, "minimum": 0, "maximum": 100,
    })
    definition = EffectDefinition.model_validate({
        "project_id": "project", "effect_key": "ambient_hit", "name": "Ambient hit",
        "target_stat_key": "hp", "operation": "subtract",
        "formula": {"kind": "constant", "value": 1},
        "value_expression": {
            "kind": "stat", "selector": {"kind": "current_location"}, "stat_key": "magic",
        },
    })
    class FakeRules:
        def stats(self, _project_id): return [target_stat, magic_stat]
        def stat(self, _project_id, key): return {"hp": target_stat, "magic": magic_stat}.get(key)
        def ability(self, *_args): return None
    runtime = RulesRuntime(SimpleNamespace(rules=FakeRules()), lambda *_args: None)
    projection = {
        "entities": {
            "actor": {"id": "actor", "kind": "character", "name": "Actor", "stats": {"hp": 10}, "state": {"current_location_id": "room"}},
            "target": {"id": "target", "kind": "character", "name": "Target", "stats": {"hp": 10}, "state": {}},
            "room": {"id": "room", "kind": "location", "name": "Room", "stats": {"magic": 3}, "state": {}},
        },
        "relations": {}, "active_effects": {}, "world_action_count": 0, "target_action_counts": {},
    }
    target = SimpleNamespace(id="target", scope="character")
    result = runtime.normalize_effect(
        "project", projection, definition, target,
        {"actor": runtime.participant("project", projection["entities"]["actor"]),
         "source": runtime.participant("project", projection["entities"]["actor"])},
    )
    assert result["resolved_magnitude"] == 3
    assert result["value"] == 7


def test_ability_and_effect_can_own_stats(tmp_path) -> None:
    from app.database import Database
    from app.data import DataProvider
    from app.domain.world import Ability, EffectDefinition, Stat

    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project_id = db.create_project("rule object stats")["id"]
    data.rules.save_stat(Stat.model_validate({
        "project_id": project_id, "stat_key": "power", "label": "Power",
        "compatible_owner_kinds": ["ability", "effect"],
        "default_value": 1, "minimum": 0, "maximum": 100,
    }))
    data.rules.save_effect(EffectDefinition.model_validate({
        "project_id": project_id, "effect_key": "blast", "name": "Blast",
        "target_stat_key": "power", "formula": {"kind": "constant", "value": 1},
        "stats": {"power": 4},
    }))
    data.rules.save_ability(Ability.model_validate({
        "project_id": project_id, "ability_key": "cast", "name": "Cast",
        "stats": {"power": 9},
    }))
    assert data.rules.effect(project_id, "blast").stats["power"] == 4
    assert data.rules.ability(project_id, "cast").stats["power"] == 9


def test_rule_context_exposes_ability_effect_and_auxiliary_objects(tmp_path) -> None:
    from app.database import Database
    from app.data import DataProvider
    from app.domain.world import Ability, EffectDefinition, Stat
    from app.services.rules import RulesRuntime

    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project_id = db.create_project("rule context objects")["id"]
    data.rules.save_stat(Stat.model_validate({
        "project_id": project_id, "stat_key": "power", "label": "Power",
        "compatible_owner_kinds": ["character", "ability", "effect", "weather"],
        "default_value": 2, "minimum": 0, "maximum": 100,
    }))
    ability = data.rules.save_ability(Ability.model_validate({
        "project_id": project_id, "ability_key": "cast", "name": "Cast", "stats": {"power": 7},
    }))
    effect = data.rules.save_effect(EffectDefinition.model_validate({
        "project_id": project_id, "effect_key": "blast", "name": "Blast",
        "target_stat_key": "power", "formula": {"kind": "constant", "value": 1}, "stats": {"power": 3},
    }))
    data.rules.save_rule_object_stats(project_id, "weather", "storm", {"power": 11})
    runtime = RulesRuntime(data, lambda *_args: None)
    projection = {"entities": {}, "relations": {}}
    context = runtime.rule_context(project_id, projection, ability=ability, effect=effect)
    expression = ValueExpression.model_validate({
        "kind": "add",
        "children": [
            {"kind": "stat", "selector": {"kind": "ability"}, "stat_key": "power"},
            {"kind": "stat", "selector": {"kind": "effect"}, "stat_key": "power"},
        ],
    })
    value, _ = ValueExpressionEvaluator().evaluate(
        expression, context,
        stat_lookup=lambda key, owner: runtime.stat(project_id, key, owner),
    )
    assert value == 10
    explicit = ValueExpression.model_validate({
        "kind": "stat",
        "selector": {"kind": "explicit", "object_kind": "weather", "object_id": "storm"},
        "stat_key": "power",
    })
    weather_value, _ = ValueExpressionEvaluator().evaluate(
        explicit, context,
        stat_lookup=lambda key, owner: runtime.stat(project_id, key, owner),
    )
    assert weather_value == 11


def test_phase8_api_schemas_preserve_generalized_fields() -> None:
    from app.schemas import AbilityDefinitionCreate, EffectDefinitionCreate

    effect = EffectDefinitionCreate.model_validate({
        "effect_key": "scaled",
        "name": "Scaled",
        "target_stat_key": "hp",
        "formula": {"kind": "constant", "value": 1},
        "value_expression": {"kind": "stat", "selector": {"kind": "ability"}, "stat_key": "power"},
        "stats": {"power": 4},
    })
    assert effect.value_expression["selector"]["kind"] == "ability"
    assert effect.stats["power"] == 4

    ability = AbilityDefinitionCreate.model_validate({
        "ability_key": "cast",
        "name": "Cast",
        "rule_costs": [{
            "owner": {"kind": "source"},
            "stat_key": "durability",
            "amount": {"kind": "constant", "value": 1},
        }],
        "stats": {"power": 7},
    })
    assert ability.rule_costs[0]["owner"]["kind"] == "source"
    assert ability.stats["power"] == 7


def test_ability_condition_expression_round_trip_and_runtime(tmp_path) -> None:
    from app.database import Database
    from app.data import DataProvider
    from app.domain.world import Ability, Stat

    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project_id = db.create_project("ability condition v2")["id"]
    data.rules.save_stat(Stat.model_validate({
        "project_id": project_id, "stat_key": "power", "label": "Power",
        "compatible_owner_kinds": ["character"], "default_value": 1,
        "minimum": 0, "maximum": 100,
    }))
    ability = data.rules.save_ability(Ability.model_validate({
        "project_id": project_id, "ability_key": "strong_cast", "name": "Strong Cast",
        "condition_expression": {
            "kind": "compare",
            "left": {"kind": "stat", "selector": {"kind": "actor"}, "stat_key": "power"},
            "comparison": "gte",
            "right": {"kind": "constant", "value": 5},
        },
    }))
    assert ability.condition_expression is not None
    assert ability.condition_expression["kind"] == "compare"
