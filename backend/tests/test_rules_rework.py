from __future__ import annotations

from types import SimpleNamespace
import sqlite3

import pytest
from pydantic import ValidationError

from app.database import Database, utc_now
from app.domain.operations import DomainOperationError, FormulaEvaluator
from app.domain.world import Ability, EffectDefinition, FormulaNode, Stat
from app.services.rules import RulesRuntime, RulesRuntimeError


PROJECT = "project"


class FakeRules:
    def __init__(self, stats: list[Stat], effects: list[EffectDefinition] | None = None, abilities: list[object] | None = None):
        self._stats = {item.stat_key: item for item in stats}
        self._effects = {item.effect_key: item for item in (effects or [])}
        self._abilities = list(abilities or [])

    def stat(self, project_id: str, key: str):
        assert project_id == PROJECT
        return self._stats.get(key)

    def stats(self, project_id: str):
        assert project_id == PROJECT
        return list(self._stats.values())

    def effect(self, project_id: str, key: str):
        assert project_id == PROJECT
        return self._effects.get(key)

    def effects(self, project_id: str):
        assert project_id == PROJECT
        return list(self._effects.values())

    def ability(self, project_id: str, key: str):
        assert project_id == PROJECT
        return next((item for item in self._abilities if getattr(item, "ability_key", None) == key), None)

    def abilities(self, project_id: str):
        assert project_id == PROJECT
        return list(self._abilities)


class FakeEnvironment:
    @staticmethod
    def phases(_project_id: str, *, enabled_only: bool = False):
        return []


class FakeSound:
    @staticmethod
    def noise_variant(*_args, **_kwargs):
        return {"id": "noise"}


class FakeData:
    def __init__(self, rules: FakeRules):
        self.rules = rules
        self.environment = FakeEnvironment()
        self.sound = FakeSound()


def apply_event(projection: dict, event_type: str, payload: dict, entity_id: str | None) -> None:
    entities = projection.setdefault("entities", {})
    relations = projection.setdefault("relations", {})
    if event_type == "stat.changed":
        container = entities.get(payload.get("entity_id")) or relations.get(payload.get("relation_id"))
        if container:
            container.setdefault("stats", {})[payload["stat_key"]] = payload["value"]
    elif event_type == "effect.instance_applied":
        for replaced in payload.get("replace_instance_ids", []):
            projection.setdefault("active_effects", {}).pop(replaced, None)
        projection.setdefault("active_effects", {})[payload["id"]] = dict(payload)
    elif event_type == "effect.instance_updated":
        current = projection.setdefault("active_effects", {}).get(payload["id"])
        if current:
            current.update(payload)
    elif event_type == "effect.instance_removed":
        projection.setdefault("active_effects", {}).pop(payload["id"], None)


def stat(key: str, *, default: float = 0, minimum: float = 0, maximum: float = 100, minimum_stat_key: str | None = None, maximum_stat_key: str | None = None, owners: list[str] | None = None, integer_only: bool = False) -> Stat:
    return Stat.model_validate({
        "project_id": PROJECT,
        "stat_key": key,
        "label": key,
        "compatible_owner_kinds": owners or ["character"],
        "default_value": default,
        "minimum": minimum,
        "maximum": maximum,
        "minimum_stat_key": minimum_stat_key,
        "maximum_stat_key": maximum_stat_key,
        "integer_only": integer_only,
    })


def effect(key: str, formula: dict, *, target: str = "hp", operation: str = "subtract", clock: str = "world_actions", duration: int = 0, tick: int = 0, evaluation: str = "snapshot", stacking: str = "replace", max_stacks: int = 1) -> EffectDefinition:
    return EffectDefinition.model_validate({
        "project_id": PROJECT,
        "effect_key": key,
        "name": key,
        "target_stat_key": target,
        "operation": operation,
        "formula": formula,
        "clock": clock,
        "duration": duration,
        "tick_interval": tick,
        "evaluation_mode": evaluation,
        "stacking_policy": stacking,
        "max_stacks": max_stacks,
    })


def projection(*, source_atk: float = 4, source_agility: float = 3, target_hp: float = 100) -> dict:
    return {
        "entities": {
            "actor": {"id": "actor", "kind": "character", "name": "Actor", "state": {}, "stats": {"atk": source_atk, "agility": source_agility}},
            "source": {"id": "source", "kind": "character", "name": "Source", "state": {}, "stats": {"atk": source_atk, "agility": source_agility}},
            "target": {"id": "target", "kind": "character", "name": "Target", "state": {}, "stats": {"hp": target_hp}},
        },
        "relations": {},
        "active_effects": {},
        "elapsed_minutes": 0,
        "world_action_count": 0,
        "target_action_counts": {},
    }


def target():
    return SimpleNamespace(id="target", scope="entity")


def runtime(stats: list[Stat], effects: list[EffectDefinition] | None = None, abilities: list[Ability] | None = None) -> RulesRuntime:
    return RulesRuntime(FakeData(FakeRules(stats, effects, abilities)), apply_event)


def test_formula_bleed_uses_source_stats() -> None:
    formula = FormulaNode.model_validate({
        "kind": "multiply",
        "children": [
            {"kind": "stat", "participant": "source", "stat_key": "atk"},
            {"kind": "stat", "participant": "source", "stat_key": "agility"},
        ],
    })
    magnitude, inputs = FormulaEvaluator().evaluate(formula, {
        "actor": {"stats": {}},
        "source": {"stats": {"atk": 4, "agility": 3}},
        "target": {"stats": {"hp": 100}},
    })
    assert magnitude == 12
    assert inputs == {"source.atk": 4.0, "source.agility": 3.0}


def test_formula_potion_and_safety_errors() -> None:
    formula = FormulaNode.model_validate({
        "kind": "multiply",
        "children": [
            {"kind": "constant", "value": 10},
            {"kind": "stat", "participant": "source", "stat_key": "quality"},
        ],
    })
    magnitude, _ = FormulaEvaluator().evaluate(formula, {
        "actor": {"stats": {}}, "source": {"stats": {"quality": 2.5}}, "target": {"stats": {}},
    })
    assert magnitude == 25
    with pytest.raises(DomainOperationError, match="divides by zero"):
        FormulaEvaluator().evaluate(FormulaNode.model_validate({
            "kind": "divide",
            "children": [{"kind": "constant", "value": 1}, {"kind": "constant", "value": 0}],
        }), {"actor": {"stats": {}}, "source": {"stats": {}}, "target": {"stats": {}}})
    with pytest.raises(DomainOperationError, match="Missing source stat"):
        FormulaEvaluator().evaluate(formula, {
            "actor": {"stats": {}}, "source": {"stats": {}}, "target": {"stats": {}},
        })


@pytest.mark.parametrize("duration,tick", [(0, 1), (-1, 0), (4, 5)])
def test_effect_timing_rejects_invalid_combinations(duration: int, tick: int) -> None:
    with pytest.raises(ValidationError, match="duration/tick"):
        effect("bad", {"kind": "constant", "value": 1}, duration=duration, tick=tick)


@pytest.mark.parametrize("duration,tick", [(0, 0), (5, 0), (5, 1), (5, 5), (-1, 1)])
def test_effect_timing_accepts_supported_combinations(duration: int, tick: int) -> None:
    assert effect("ok", {"kind": "constant", "value": 1}, duration=duration, tick=tick)


def test_immediate_effect_does_not_create_instance() -> None:
    hp = stat("hp")
    definition = effect("hit", {"kind": "constant", "value": 12})
    rt = runtime([hp], [definition])
    world = projection()
    row = rt.normalize_effect(
        PROJECT, world, definition, target(),
        {"actor": rt.participant(PROJECT, world["entities"]["actor"]), "source": rt.participant(PROJECT, world["entities"]["source"])},
    )
    assert row["event_type"] == "stat.changed"
    assert row["previous_value"] == 100
    assert row["value"] == 88
    assert "id" not in row


def test_periodic_effect_fires_boundary_and_expires() -> None:
    hp = stat("hp")
    definition = effect("bleed", {"kind": "constant", "value": 2}, duration=6, tick=2)
    rt = runtime([hp], [definition])
    world = projection()
    applied = rt.normalize_effect(
        PROJECT, world, definition, target(),
        {"actor": rt.participant(PROJECT, world["entities"]["actor"]), "source": rt.participant(PROJECT, world["entities"]["source"])},
    )
    apply_event(world, "effect.instance_applied", applied, None)
    emitted = rt.due_effects(PROJECT, world, "world_actions", 6)
    fires = [item for item in emitted if item["event_type"] == "stat.changed"]
    assert [item["fired_at"] for item in fires] == [2, 4, 6]
    assert [item["value"] for item in fires] == [98, 96, 94]
    assert emitted[-1]["event_type"] == "effect.instance_removed"


def test_delayed_effect_fires_once_at_expiry() -> None:
    hp = stat("hp")
    definition = effect("delayed", {"kind": "constant", "value": 7}, duration=5, tick=0)
    rt = runtime([hp], [definition])
    world = projection()
    applied = rt.normalize_effect(
        PROJECT, world, definition, target(),
        {"actor": rt.participant(PROJECT, world["entities"]["actor"]), "source": rt.participant(PROJECT, world["entities"]["source"])},
    )
    apply_event(world, "effect.instance_applied", applied, None)
    emitted = rt.due_effects(PROJECT, world, "world_actions", 50)
    fires = [item for item in emitted if item["event_type"] == "stat.changed"]
    assert len(fires) == 1
    assert fires[0]["fired_at"] == 5
    assert emitted[-1]["event_type"] == "effect.instance_removed"


def test_indefinite_effect_fires_all_due_ticks() -> None:
    hp = stat("hp")
    definition = effect("regen", {"kind": "constant", "value": 1}, operation="add", duration=-1, tick=2)
    rt = runtime([hp], [definition])
    world = projection(target_hp=50)
    applied = rt.normalize_effect(
        PROJECT, world, definition, target(),
        {"actor": rt.participant(PROJECT, world["entities"]["actor"]), "source": rt.participant(PROJECT, world["entities"]["source"])},
    )
    apply_event(world, "effect.instance_applied", applied, None)
    emitted = rt.due_effects(PROJECT, world, "world_actions", 7)
    fires = [item for item in emitted if item["event_type"] == "stat.changed"]
    assert [item["fired_at"] for item in fires] == [2, 4, 6]
    assert not any(item["event_type"] == "effect.instance_removed" for item in emitted)


def test_snapshot_vs_live_evaluation() -> None:
    stats = [stat("hp"), stat("atk")]
    formula = {"kind": "stat", "participant": "source", "stat_key": "atk"}
    snapshot = effect("snapshot", formula, duration=2, tick=2, evaluation="snapshot")
    live = effect("live", formula, duration=2, tick=2, evaluation="live")
    rt = runtime(stats, [snapshot, live])
    for definition, expected in ((snapshot, 96), (live, 90)):
        world = projection(source_atk=4)
        participants = {
            "actor": rt.participant(PROJECT, world["entities"]["actor"]),
            "source": rt.participant(PROJECT, world["entities"]["source"]),
        }
        applied = rt.normalize_effect(PROJECT, world, definition, target(), participants)
        apply_event(world, "effect.instance_applied", applied, None)
        world["entities"]["source"]["stats"]["atk"] = 10
        emitted = rt.due_effects(PROJECT, world, "world_actions", 2)
        fire = next(item for item in emitted if item["event_type"] == "stat.changed")
        assert fire["value"] == expected


def test_replace_refresh_stack_and_independent_instances() -> None:
    hp = stat("hp")
    participants_world = projection()
    for policy in ("replace", "refresh", "stack", "independent"):
        definition = effect(policy, {"kind": "constant", "value": 2}, duration=10, tick=5, stacking=policy, max_stacks=3)
        rt = runtime([hp], [definition])
        world = projection()
        participants = {
            "actor": rt.participant(PROJECT, world["entities"]["actor"]),
            "source": rt.participant(PROJECT, world["entities"]["source"]),
        }
        first = rt.normalize_effect(PROJECT, world, definition, target(), participants)
        apply_event(world, first["event_type"], first, None)
        first_id = first["id"]
        world["world_action_count"] = 2
        second = rt.normalize_effect(PROJECT, world, definition, target(), participants)
        if policy == "replace":
            assert second["event_type"] == "effect.instance_applied"
            assert second["replace_instance_ids"] == [first_id]
            assert second["id"] != first_id
        elif policy == "refresh":
            assert second["event_type"] == "effect.instance_updated"
            assert second["id"] == first_id
            assert second["stacks"] == 1
            assert second["started_at"] == 2
        elif policy == "stack":
            assert second["event_type"] == "effect.instance_updated"
            assert second["id"] == first_id
            assert second["stacks"] == 2
            assert second["started_at"] == 2
        else:
            assert second["event_type"] == "effect.instance_applied"
            assert second["id"] != first_id
            assert second["replace_instance_ids"] == []


def test_dynamic_bound_changes_emit_transitive_clamps() -> None:
    max_hp = stat("max_hp", default=100, minimum=1, maximum=999)
    hp = stat("hp", default=100, maximum=999, maximum_stat_key="max_hp")
    shield = stat("shield", default=100, maximum=999, maximum_stat_key="hp")
    rt = runtime([max_hp, hp, shield])
    world = projection(target_hp=100)
    world["entities"]["target"]["stats"].update({"max_hp": 100, "shield": 100})
    event = ("stat.changed", "target", {"entity_id": "target", "stat_key": "max_hp", "previous_value": 100, "value": 40})
    derived = rt.dependent_clamps(PROJECT, world, [event])
    assert [(item["stat_key"], item["value"]) for item in derived] == [("hp", 40.0), ("shield", 40.0)]


def test_due_effects_caps_large_time_jumps() -> None:
    hp = stat("hp", maximum=1_000_000)
    definition = effect("forever", {"kind": "constant", "value": 0}, duration=-1, tick=1)
    rt = runtime([hp], [definition])
    world = projection()
    applied = rt.normalize_effect(
        PROJECT, world, definition, target(),
        {"actor": rt.participant(PROJECT, world["entities"]["actor"]), "source": rt.participant(PROJECT, world["entities"]["source"])},
    )
    apply_event(world, "effect.instance_applied", applied, None)
    with pytest.raises(RulesRuntimeError, match="1,000"):
        rt.due_effects(PROJECT, world, "world_actions", 1001)



def test_fresh_database_has_normalized_rules_schema(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    versions = {row["version"] for row in db.fetch_all("SELECT version FROM schema_migrations")}
    assert "041_spatial_canonical_storage" in versions
    assert "042_canonical_rules" in versions

    tables = {row["name"] for row in db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "stat_definitions",
        "stat_definition_owner_kinds",
        "effect_definitions",
        "effect_formula_nodes",
        "ability_definitions",
        "ability_owner_kinds",
        "ability_requirement_nodes",
        "ability_costs",
        "ability_actions",
        "ability_passive_triggers",
        "ability_bullethell_skills",
        "rule_migration_warnings",
    } <= tables
    ability_columns = {row["name"] for row in db.fetch_all("PRAGMA table_info(ability_definitions)")}
    assert "requirements_json" not in ability_columns
    assert "costs_json" not in ability_columns
    assert "effects_json" not in ability_columns


def test_canonical_rule_keys_are_database_immutable(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Rules")
    now = utc_now()
    db.execute(
        "INSERT INTO stat_definitions(project_id,stat_key,label,description,default_value,minimum,maximum,display_style,integer_only,visibility,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (project["id"], "hp", "HP", "", 10, 0, 10, "bar", 1, "public", now, now),
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE stat_definitions SET stat_key='health' WHERE project_id=? AND stat_key='hp'",
            (project["id"],),
        )



def test_multiple_stat_costs_cannot_spend_the_same_resource_twice() -> None:
    mana = stat("mana", default=10, minimum=0, maximum=10)
    ability = Ability.model_validate({
        "project_id": PROJECT,
        "ability_key": "double_cost",
        "name": "Double cost",
        "target_type": "self",
        "compatible_owner_kinds": ["character"],
        "costs": [
            {"kind": "stat", "stat_key": "mana", "amount": 6},
            {"kind": "stat", "stat_key": "mana", "amount": 6},
        ],
        "actions": [],
    })
    rt = runtime([mana], abilities=[ability])
    world = projection()
    world["entities"]["actor"]["state"]["abilities"] = ["double_cost"]
    world["entities"]["actor"]["stats"]["mana"] = 10
    with pytest.raises(RulesRuntimeError, match="lacks enough mana"):
        rt.normalize_ability(PROJECT, world, {"actor_id": "actor", "ability_key": "double_cost"}, "player")


def test_item_costs_are_cumulative_and_rollback_on_failure() -> None:
    ability = Ability.model_validate({
        "project_id": PROJECT,
        "ability_key": "item_cast",
        "name": "Item cast",
        "target_type": "self",
        "compatible_owner_kinds": ["item"],
        "costs": [
            {"kind": "consume_source", "amount": 1},
            {"kind": "consume_source", "amount": 1},
        ],
        "actions": [],
    })
    rt = runtime([], abilities=[ability])
    world = projection()
    world["entities"]["wand"] = {"id": "wand", "kind": "item", "name": "Wand", "state": {"abilities": ["item_cast"]}, "stats": {}}
    world["entities"]["actor"]["state"]["inventory"] = [{"item_id": "wand", "quantity": 1}]
    with pytest.raises(RulesRuntimeError, match="item cost"):
        rt.normalize_ability(PROJECT, world, {"actor_id": "actor", "ability_key": "item_cast", "source_item_id": "wand"}, "player")
    assert world["entities"]["actor"]["state"]["inventory"] == [{"item_id": "wand", "quantity": 1}]


def test_ability_created_effect_starts_after_committing_action() -> None:
    hp = stat("hp")
    definition = effect("bleed_after", {"kind": "constant", "value": 1}, duration=1, tick=1)
    ability = Ability.model_validate({
        "project_id": PROJECT,
        "ability_key": "apply_bleed",
        "name": "Apply bleed",
        "target_type": "self",
        "compatible_owner_kinds": ["character"],
        "actions": [{"kind": "apply_effect", "target": "target", "effect_key": "bleed_after"}],
    })
    rt = runtime([hp], [definition], [ability])
    world = projection()
    world["entities"]["actor"]["state"]["abilities"] = ["apply_bleed"]
    world["entities"]["actor"]["stats"]["hp"] = 100
    world["world_action_count"] = 5
    world["target_action_counts"]["actor"] = 5
    normalized = rt.normalize_ability(PROJECT, world, {"actor_id": "actor", "ability_key": "apply_bleed"}, "player")
    active = normalized["effects"][0]
    assert active["event_type"] == "effect.instance_applied"
    assert active["started_at"] == 6
    assert active["next_tick"] == 7
    assert active["expires_at"] == 7



def test_legacy_inline_ability_migrates_to_effects_actions_and_warnings(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Legacy rules")
    project_id = project["id"]
    now = utc_now()
    db.execute(
        "INSERT INTO stat_definitions(project_id,stat_key,label,description,default_value,minimum,maximum,display_style,integer_only,visibility,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, "hp", "HP", "", 100, 0, 100, "bar", 1, "public", now, now),
    )
    db.execute(
        "INSERT INTO stat_definition_owner_kinds(project_id,stat_key,owner_kind) VALUES(?,?,?)",
        (project_id, "hp", "character"),
    )

    with db._lock, db.connect() as connection:
        connection.execute(
            "CREATE TABLE ability_definitions_legacy_v2("
            "id TEXT PRIMARY KEY,project_id TEXT,ability_key TEXT,name TEXT,description TEXT,target_type TEXT,"
            "requirements_json TEXT,costs_json TEXT,effects_json TEXT,minigame_profile_json TEXT,created_at TEXT,updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO ability_definitions_legacy_v2 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-ability", project_id, "slash", "Slash", "", "character",
                '{"kind":"not","child":{"kind":"has_tag","tag":"invulnerable","target":"target"}}',
                '{"hp":5}',
                '[{"operation":"subtract","stat_key":"hp","amount":12,"target":"target"},'
                '{"operation":"move","destination_id":"somewhere","target":"actor"},'
                '{"operation":"apply_status","status":"bleeding","target":"target"}]',
                '{}', now, now,
            ),
        )
        db._migrate_canonical_rules(connection)

    ability = db.fetch_one("SELECT * FROM ability_definitions WHERE project_id=? AND ability_key='slash'", (project_id,))
    assert ability is not None
    generated = db.fetch_one("SELECT * FROM effect_definitions WHERE project_id=? AND effect_key='slash_effect_1'", (project_id,))
    assert generated is not None
    assert generated["target_stat_key"] == "hp"
    assert generated["operation"] == "subtract"
    formula = db.fetch_one(
        "SELECT node_kind,constant_value FROM effect_formula_nodes WHERE project_id=? AND effect_key='slash_effect_1'",
        (project_id,),
    )
    assert formula == {"node_kind": "constant", "constant_value": 12.0}
    actions = db.fetch_all(
        "SELECT action_kind,effect_key,destination_id FROM ability_actions WHERE project_id=? AND ability_key='slash' ORDER BY position",
        (project_id,),
    )
    assert [item["action_kind"] for item in actions] == ["apply_effect", "move"]
    assert actions[0]["effect_key"] == "slash_effect_1"
    root = db.fetch_one(
        "SELECT id,node_kind FROM ability_requirement_nodes WHERE project_id=? AND ability_key='slash' AND parent_id IS NULL",
        (project_id,),
    )
    assert root and root["node_kind"] == "not"
    child = db.fetch_one(
        "SELECT edge_kind,node_kind,tag FROM ability_requirement_nodes WHERE parent_id=?",
        (root["id"],),
    )
    assert child == {"edge_kind": "not_child", "node_kind": "has_tag", "tag": "invulnerable"}
    warnings = db.fetch_all(
        "SELECT warning_kind,details_json FROM rule_migration_warnings WHERE project_id=?",
        (project_id,),
    )
    assert any(item["warning_kind"] == "discarded_marker_status" for item in warnings)


def test_legacy_active_effect_events_are_removed_but_stat_history_remains(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Legacy effect history")
    project_id = project["id"]
    now = utc_now()
    node_id = "story-node"
    db.execute(
        "INSERT INTO story_nodes(id,project_id,parent_id,role,content,status,created_at,narration_mode,action_kind) "
        "VALUES(?,?,NULL,'assistant','x','complete',?,'third_limited','story')",
        (node_id, project_id, now),
    )
    transaction_id = "legacy-tx"
    db.execute(
        "INSERT INTO world_transactions(id,project_id,story_node_id,parent_node_id,branch_sequence,elapsed_minutes,provenance,status,summary,created_at) "
        "VALUES(?,?,?,NULL,1,0,'author','committed','legacy',?)",
        (transaction_id, project_id, node_id, now),
    )
    entity_id = "legacy-character"
    db.execute(
        "INSERT INTO world_entities(id,project_id,kind,canonical_name,aliases_json,tags_json,created_at) VALUES(?,?, 'character','Hero','[]','[]',?)",
        (entity_id, project_id, now),
    )
    db.execute(
        "INSERT INTO world_events(id,transaction_id,entity_id,event_type,ordinal,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
        ("effect-event", transaction_id, entity_id, "effect.applied", 0, '{"stat_key":"hp"}', now),
    )
    db.execute(
        "INSERT INTO world_events(id,transaction_id,entity_id,event_type,ordinal,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
        ("stat-event", transaction_id, entity_id, "stat.changed", 1, '{"stat_key":"hp","value":80}', now),
    )

    with db._lock, db.connect() as connection:
        connection.execute(
            "CREATE TABLE ability_definitions_legacy_v2("
            "id TEXT PRIMARY KEY,project_id TEXT,ability_key TEXT,name TEXT,description TEXT,target_type TEXT,"
            "requirements_json TEXT,costs_json TEXT,effects_json TEXT,minigame_profile_json TEXT,created_at TEXT,updated_at TEXT)"
        )
        db._migrate_canonical_rules(connection)

    assert db.fetch_one("SELECT id FROM world_events WHERE id='effect-event'") is None
    assert db.fetch_one("SELECT id FROM world_events WHERE id='stat-event'") is not None
    warning = db.fetch_one(
        "SELECT warning_kind,details_json FROM rule_migration_warnings WHERE project_id=? AND warning_kind='discarded_active_effects'",
        (project_id,),
    )
    assert warning is not None
    assert '"instance_count": 1' in warning["details_json"]
