from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.database import Database
from app.domain.operations import DomainOperationError, FormulaEvaluator
from app.domain.world import Ability, EffectDefinition, FormulaNode, Stat
from app.services.world import WorldEngine, WorldValidationError


def setup_world(path: Path) -> tuple[dict, WorldEngine]:
    db = Database(path)
    db.initialize()
    project = db.create_project("Canonical rules")
    return project, WorldEngine(db)


def create_entity(world: WorldEngine, project_id: str, entity_id: str, kind: str, name: str, *, state: dict | None = None, stats: dict | None = None) -> None:
    mutation = world.normalize_mutations(project_id, None, [{"tool": "createEntity", "arguments": {"entity_id": entity_id, "kind": kind, "name": name, "state": state or {}, "stats": stats or {}}}], provenance="author")
    world.commit_root(project_id, mutation, provenance="author", summary=f"Create {name}")


def save_stat(world: WorldEngine, project_id: str, key: str, *, owners: list[str], default: float = 0, minimum: float = 0, maximum: float = 100, minimum_stat_key: str | None = None, maximum_stat_key: str | None = None) -> None:
    world.data.rules.save_stat(Stat(project_id=project_id, stat_key=key, label=key.title(), compatible_owner_kinds=owners, default_value=default, minimum=minimum, maximum=maximum, minimum_stat_key=minimum_stat_key, maximum_stat_key=maximum_stat_key))


def test_normalized_repository_round_trip_has_no_legacy_json_columns(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "hp", owners=["character"], default=50)
    effect = world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="healing", name="Healing", description="Restore health", target_stat_key="hp", operation="add", formula={"kind": "multiply", "children": [{"kind": "constant", "value": 10}, {"kind": "stat", "participant": "source", "stat_key": "hp"}]}))
    ability = world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="renew", name="Renew", requirements={"kind": "compare", "target": "actor", "stat_key": "hp", "comparison": "gte", "value": 1}, costs=[{"kind": "stat", "stat_key": "hp", "amount": 1}], actions=[{"kind": "apply_effect", "target": "target", "effect_key": "healing"}]))

    assert effect.formula.kind == "multiply"
    assert effect.formula.children[1].participant == "source"
    assert ability.requirements.stat_key == "hp"
    assert ability.actions[0].effect_key == "healing"
    assert {row["name"] for row in world.db.fetch_all("PRAGMA table_info(ability_definitions)")}.isdisjoint({"requirements_json", "costs_json", "effects_json", "minigame_profile_json"})


def test_formula_examples_and_invalid_arithmetic() -> None:
    evaluator = FormulaEvaluator()
    bleed = FormulaNode.model_validate({"kind": "multiply", "children": [{"kind": "stat", "participant": "source", "stat_key": "atk"}, {"kind": "stat", "participant": "source", "stat_key": "agility"}]})
    potion = FormulaNode.model_validate({"kind": "multiply", "children": [{"kind": "constant", "value": 10}, {"kind": "stat", "participant": "source", "stat_key": "quality"}]})
    assert evaluator.evaluate(bleed, {"source": {"stats": {"atk": 4, "agility": 3}}})[0] == 12
    assert evaluator.evaluate(potion, {"source": {"stats": {"quality": 2.5}}})[0] == 25
    with pytest.raises(DomainOperationError, match="divides by zero"):
        evaluator.evaluate(FormulaNode.model_validate({"kind": "divide", "children": [{"kind": "constant", "value": 1}, {"kind": "constant", "value": 0}]}), {})
    with pytest.raises(DomainOperationError, match="missing stat"):
        evaluator.evaluate(bleed, {"source": {"stats": {"atk": 4}}})


def test_transitive_dynamic_bounds_emit_persisted_clamps(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "cap_2", owners=["character"], default=100)
    save_stat(world, project["id"], "cap_1", owners=["character"], default=100, maximum_stat_key="cap_2")
    save_stat(world, project["id"], "hp", owners=["character"], default=100, maximum_stat_key="cap_1")
    create_entity(world, project["id"], "hero", "character", "Hero", stats={"hp": 90, "cap_1": 80, "cap_2": 50})
    mutations = world.normalize_mutations(project["id"], None, [{"tool": "adjustStat", "arguments": {"entity_id": "hero", "stat_key": "cap_2", "operation": "set", "amount": 40}}], provenance="author")
    world.commit_root(project["id"], mutations, provenance="author", summary="Lower cap")
    stats = world.projection(project["id"])["entities"]["hero"]["stats"]
    assert stats == {"hp": 40, "cap_1": 40, "cap_2": 40}


def test_repository_rejects_indirect_bound_cycles_and_incompatible_owners(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "first", owners=["character"])
    save_stat(world, project["id"], "second", owners=["character"], maximum_stat_key="first")
    with pytest.raises(ValueError, match="cycle"):
        world.data.rules.save_stat(Stat(project_id=project["id"], stat_key="first", label="First", compatible_owner_kinds=["character"], maximum_stat_key="second"), previous_key="first")
    save_stat(world, project["id"], "item_cap", owners=["item"])
    with pytest.raises(ValueError, match="incompatible"):
        world.data.rules.save_stat(Stat(project_id=project["id"], stat_key="invalid", label="Invalid", compatible_owner_kinds=["character"], maximum_stat_key="item_cap"))


def test_repository_rejects_unknown_formula_and_ability_references(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "hp", owners=["character"])
    with pytest.raises(ValueError, match="formula references unknown"):
        world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="invalid_formula", name="Invalid formula", target_stat_key="hp", formula={"kind": "stat", "participant": "source", "stat_key": "missing"}))
    with pytest.raises(ValueError, match="unknown effect"):
        world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="invalid_ability", name="Invalid ability", actions=[{"kind": "apply_effect", "effect_key": "missing"}]))


def test_item_ability_requires_the_source_item_to_own_it(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "hp", owners=["character"], default=20, maximum=100)
    save_stat(world, project["id"], "quality", owners=["item"], default=1, maximum=10)
    world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="potion_heal", name="Potion heal", target_stat_key="hp", operation="add", formula={"kind": "multiply", "children": [{"kind": "constant", "value": 10}, {"kind": "stat", "participant": "source", "stat_key": "quality"}]}))
    world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="drink_potion", name="Drink potion", compatible_owner_kinds=["item"], target_type="self", costs=[{"kind": "consume_source", "amount": 1}], actions=[{"kind": "apply_effect", "target": "actor", "effect_key": "potion_heal"}]))
    create_entity(world, project["id"], "potion", "item", "Potion", state={"abilities": ["drink_potion"]}, stats={"quality": 2})
    create_entity(world, project["id"], "decoy", "item", "Decoy", state={}, stats={"quality": 9})
    create_entity(world, project["id"], "hero", "character", "Hero", state={"inventory": [{"item_id": "potion", "quantity": 1}, {"item_id": "decoy", "quantity": 1}]}, stats={"hp": 20})
    with pytest.raises(WorldValidationError, match="does not provide"):
        world.normalize_mutations(project["id"], None, [{"tool": "useAbility", "arguments": {"actor_id": "hero", "source_item_id": "decoy", "ability_key": "drink_potion"}}], provenance="author")
    mutations = world.normalize_mutations(project["id"], None, [{"tool": "useAbility", "arguments": {"actor_id": "hero", "source_item_id": "potion", "ability_key": "drink_potion"}}], provenance="author")
    world.commit_root(project["id"], mutations, provenance="author", summary="Drink")
    hero = world.projection(project["id"])["entities"]["hero"]
    assert hero["stats"]["hp"] == 40
    assert all(entry["item_id"] != "potion" for entry in hero["state"]["inventory"])


def test_periodic_effect_fires_at_each_interval_and_expires(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "hp", owners=["character"], default=20)
    create_entity(world, project["id"], "hero", "character", "Hero", stats={"hp": 20})
    world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="bleed", name="Bleed", target_stat_key="hp", operation="subtract", formula={"kind": "constant", "value": 2}, clock="story_minutes", duration=10, tick_interval=5))
    applied = world.normalize_mutations(project["id"], None, [{"tool": "applyEffect", "arguments": {"effect_key": "bleed", "target_id": "hero"}}], provenance="author")
    world.commit_root(project["id"], applied, provenance="author", summary="Apply bleed")
    assert len(world.projection(project["id"])["active_effects"]) == 1
    advanced = world.normalize_mutations(project["id"], None, [{"tool": "advanceTime", "arguments": {"minutes": 10}}], provenance="author")
    world.commit_root(project["id"], advanced, provenance="author", summary="Advance")
    projection = world.projection(project["id"])
    assert projection["entities"]["hero"]["stats"]["hp"] == 16
    assert projection["active_effects"] == {}


def test_stacked_effect_uses_one_instance_and_multiplies_each_tick(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "hp", owners=["character"], default=20)
    create_entity(world, project["id"], "hero", "character", "Hero", stats={"hp": 20})
    world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="bleed", name="Bleed", target_stat_key="hp", operation="subtract", formula={"kind": "constant", "value": 2}, clock="story_minutes", duration=10, tick_interval=5, stacking_policy="stack", max_stacks=3))
    for _ in range(2):
        mutation = world.normalize_mutations(project["id"], None, [{"tool": "applyEffect", "arguments": {"effect_key": "bleed", "target_id": "hero"}}], provenance="author")
        world.commit_root(project["id"], mutation, provenance="author", summary="Apply bleed")
    active = list(world.projection(project["id"])["active_effects"].values())
    assert len(active) == 1
    assert active[0]["stacks"] == 2
    advanced = world.normalize_mutations(project["id"], None, [{"tool": "advanceTime", "arguments": {"minutes": 5}}], provenance="author")
    world.commit_root(project["id"], advanced, provenance="author", summary="Advance")
    assert world.projection(project["id"])["entities"]["hero"]["stats"]["hp"] == 16


def test_time_advanced_by_an_ability_ticks_story_minute_effects(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "hp", owners=["character"], default=20)
    world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="bleed", name="Bleed", target_stat_key="hp", operation="subtract", formula={"kind": "constant", "value": 2}, clock="story_minutes", duration=10, tick_interval=5))
    world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="wait", name="Wait", actions=[{"kind": "advance_time", "target": "actor", "minutes": 5}]))
    create_entity(world, project["id"], "hero", "character", "Hero", state={"abilities": ["wait"]}, stats={"hp": 20})
    applied = world.normalize_mutations(project["id"], None, [{"tool": "applyEffect", "arguments": {"effect_key": "bleed", "target_id": "hero"}}], provenance="author")
    world.commit_root(project["id"], applied, provenance="author", summary="Apply bleed")
    waited = world.normalize_mutations(project["id"], None, [{"tool": "useAbility", "arguments": {"actor_id": "hero", "ability_key": "wait"}}], provenance="author")
    world.commit_root(project["id"], waited, provenance="author", summary="Wait")
    projection = world.projection(project["id"])
    assert projection["elapsed_minutes"] == 5
    assert projection["entities"]["hero"]["stats"]["hp"] == 18


def test_passive_requirements_filter_instead_of_failing_triggering_action(tmp_path: Path) -> None:
    project, world = setup_world(tmp_path)
    save_stat(world, project["id"], "hp", owners=["character"], default=10)
    world.data.rules.save_effect(EffectDefinition(project_id=project["id"], effect_key="heal", name="Heal", target_stat_key="hp", formula={"kind": "constant", "value": 5}))
    world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="wait", name="Wait", actions=[]))
    world.data.rules.save_ability(Ability(project_id=project["id"], ability_key="conditional_heal", name="Conditional heal", ability_kind="passive", requirements={"kind": "has_tag", "target": "actor", "tag": "blessed"}, passive_triggers=[{"kind": "ability_used"}], actions=[{"kind": "apply_effect", "target": "actor", "effect_key": "heal"}]))
    create_entity(world, project["id"], "hero", "character", "Hero", state={"abilities": ["wait", "conditional_heal"]}, stats={"hp": 10})
    mutation = world.normalize_mutations(project["id"], None, [{"tool": "useAbility", "arguments": {"actor_id": "hero", "ability_key": "wait"}}], provenance="author")
    world.commit_root(project["id"], mutation, provenance="author", summary="Wait")
    assert world.projection(project["id"])["entities"]["hero"]["stats"]["hp"] == 10


@pytest.mark.parametrize("duration,tick", [(0, 1), (-1, 0), (4, 5)])
def test_invalid_effect_timing_is_rejected(duration: int, tick: int) -> None:
    with pytest.raises(ValidationError, match="duration/tick"):
        EffectDefinition(project_id="project", effect_key="invalid", name="Invalid", target_stat_key="hp", formula={"kind": "constant", "value": 1}, duration=duration, tick_interval=tick)
