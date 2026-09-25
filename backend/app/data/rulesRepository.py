from __future__ import annotations

import json
from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now
from app.domain.world import (
    Ability,
    AbilityAction,
    AbilityCost,
    EffectDefinition,
    FormulaNode,
    PassiveTrigger,
    RequirementExpression,
    Stat,
)


class RulesRepository(BaseRepository):
    """Canonical normalized persistence for project rules."""

    @staticmethod
    def dependency_ordered_stats(stats: list[Stat], available: set[str] | None = None) -> list[Stat]:
        """Return definitions in an order safe for incremental normalized writes."""
        pending = {item.stat_key: item for item in stats}
        ready_keys = set(available or ())
        ordered: list[Stat] = []
        while pending:
            ready = sorted(
                (
                    item for item in pending.values()
                    if {
                        key for key in (item.minimum_stat_key, item.maximum_stat_key)
                        if key and key in pending
                    }.issubset(ready_keys)
                ),
                key=lambda item: item.stat_key,
            )
            if not ready:
                raise ValueError("Stat bound dependencies contain a cycle")
            for item in ready:
                ordered.append(item)
                ready_keys.add(item.stat_key)
                pending.pop(item.stat_key)
        return ordered

    @staticmethod
    def _formula_stat_keys(node: FormulaNode) -> set[str]:
        keys = {node.stat_key} if node.stat_key else set()
        for child in node.children:
            keys.update(RulesRepository._formula_stat_keys(child))
        return keys

    @staticmethod
    def _requirement_references(node: RequirementExpression) -> tuple[set[str], set[str]]:
        stats = {node.stat_key} if node.stat_key else set()
        abilities = {node.ability_key} if node.ability_key else set()
        for child in node.children:
            child_stats, child_abilities = RulesRepository._requirement_references(child)
            stats.update(child_stats)
            abilities.update(child_abilities)
        if node.child:
            child_stats, child_abilities = RulesRepository._requirement_references(node.child)
            stats.update(child_stats)
            abilities.update(child_abilities)
        return stats, abilities

    def _validate_stat(self, stat: Stat) -> None:
        definitions = {item.stat_key: item for item in self.stats(str(stat.project_id))}
        definitions[stat.stat_key] = stat
        owners = set(map(str, stat.compatible_owner_kinds))
        for field in ("minimum_stat_key", "maximum_stat_key"):
            dependency_key = getattr(stat, field)
            if not dependency_key:
                continue
            dependency = definitions.get(dependency_key)
            if dependency is None:
                raise ValueError(f"{field} references an unknown stat: {dependency_key}")
            missing = owners.difference(map(str, dependency.compatible_owner_kinds))
            if missing:
                raise ValueError(f"{field} is incompatible with owner kinds: {', '.join(sorted(missing))}")

        graph = {
            key: [candidate for candidate in (item.minimum_stat_key, item.maximum_stat_key) if candidate]
            for key, item in definitions.items()
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("Stat bound dependencies contain a cycle")
            if key in visited:
                return
            visiting.add(key)
            for child in graph.get(key, []):
                visit(child)
            visiting.remove(key)
            visited.add(key)

        for key in graph:
            visit(key)

        for dependent in definitions.values():
            if stat.stat_key not in {dependent.minimum_stat_key, dependent.maximum_stat_key}:
                continue
            missing = set(map(str, dependent.compatible_owner_kinds)).difference(owners)
            if missing:
                raise ValueError(
                    f"{stat.stat_key} is incompatible with dependent stat {dependent.stat_key} "
                    f"for owner kinds: {', '.join(sorted(missing))}"
                )
        if "character" not in owners and self.db.fetch_one(
            "SELECT 1 FROM ability_costs WHERE project_id=? AND stat_key=? LIMIT 1",
            (str(stat.project_id), stat.stat_key),
        ):
            raise ValueError("A stat used as an ability cost must remain character-compatible")

    def _validate_effect(self, effect: EffectDefinition) -> None:
        known = {item.stat_key for item in self.stats(str(effect.project_id))}
        if effect.target_stat_key not in known:
            raise ValueError(f"Effect targets an unknown stat: {effect.target_stat_key}")
        missing = self._formula_stat_keys(effect.formula).difference(known)
        if missing:
            raise ValueError(f"Effect formula references unknown stat(s): {', '.join(sorted(missing))}")

    def _validate_ability(self, ability: Ability, available_ability_keys: set[str] | None = None) -> None:
        project_id = str(ability.project_id)
        definitions = {item.stat_key: item for item in self.stats(project_id)}
        requirement_stats, requirement_abilities = self._requirement_references(ability.requirements)
        missing_stats = requirement_stats.difference(definitions)
        missing_stats.update(str(cost.stat_key) for cost in ability.costs if cost.stat_key and cost.stat_key not in definitions)
        missing_stats.update(str(trigger.stat_key) for trigger in ability.passive_triggers if trigger.stat_key and trigger.stat_key not in definitions)
        if missing_stats:
            raise ValueError(f"Ability references unknown stat(s): {', '.join(sorted(missing_stats))}")
        invalid_costs = [
            str(cost.stat_key) for cost in ability.costs
            if cost.stat_key and "character" not in map(str, definitions[cost.stat_key].compatible_owner_kinds)
        ]
        if invalid_costs:
            raise ValueError(f"Ability cost stat(s) are not character-compatible: {', '.join(sorted(set(invalid_costs)))}")
        invalid_triggers = [
            str(trigger.stat_key) for trigger in ability.passive_triggers
            if trigger.stat_key and "character" not in map(str, definitions[trigger.stat_key].compatible_owner_kinds)
        ]
        if invalid_triggers:
            raise ValueError(f"Passive trigger stat(s) are not character-compatible: {', '.join(sorted(set(invalid_triggers)))}")
        known_abilities = {item.ability_key for item in self.abilities(project_id)} | {ability.ability_key} | set(available_ability_keys or ())
        missing_abilities = requirement_abilities.difference(known_abilities)
        if missing_abilities:
            raise ValueError(f"Ability requirements reference unknown ability key(s): {', '.join(sorted(missing_abilities))}")
        effect_definitions = {item.effect_key: item for item in self.effects(project_id)}
        known_effects = set(effect_definitions)
        missing_effects = {
            str(action.effect_key) for action in ability.actions
            if action.effect_key and action.effect_key not in known_effects
        }
        if missing_effects:
            raise ValueError(f"Ability references unknown effect(s): {', '.join(sorted(missing_effects))}")
        for action in ability.actions:
            if not action.effect_key:
                continue
            effect = effect_definitions[action.effect_key]
            target_kind = (
                "location" if str(action.target) == "location"
                else "relationship" if str(action.target) == "target" and str(ability.target_type) == "relationship"
                else "location" if str(action.target) == "target" and str(ability.target_type) == "location"
                else "character"
            )
            target_stat = definitions[effect.target_stat_key]
            if target_kind not in map(str, target_stat.compatible_owner_kinds):
                raise ValueError(
                    f"Effect {effect.effect_key} cannot target {target_kind} through this ability action"
                )
            duration = effect.duration if action.duration_override is None else action.duration_override
            tick = effect.tick_interval if action.tick_override is None else action.tick_override
            if not (
                (duration == 0 and tick == 0)
                or (duration > 0 and tick <= duration)
                or (duration == -1 and tick > 0)
            ):
                raise ValueError(f"Ability action for {action.effect_key} has an invalid duration/tick override")

    def stats(self, project_id: str) -> list[Stat]:
        rows = self.db.fetch_all(
            "SELECT * FROM stat_definitions WHERE project_id=? ORDER BY label,stat_key",
            (project_id,),
        )
        owners = self.db.fetch_all(
            "SELECT stat_key,owner_kind FROM stat_definition_owner_kinds WHERE project_id=? ORDER BY owner_kind",
            (project_id,),
        )
        by_key: dict[str, list[str]] = {}
        for row in owners:
            by_key.setdefault(row["stat_key"], []).append(row["owner_kind"])
        return [
            Stat.model_validate({**row, "integer_only": bool(row["integer_only"]), "compatible_owner_kinds": by_key.get(row["stat_key"], [])})
            for row in rows
        ]

    def stat(self, project_id: str, stat_key: str) -> Stat | None:
        return next((item for item in self.stats(project_id) if item.stat_key == stat_key), None)

    def save_stat(self, stat: Stat, *, previous_key: str | None = None) -> Stat:
        key = previous_key or stat.stat_key
        self._validate_stat(stat)
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM stat_definitions WHERE project_id=? AND stat_key=?", (stat.project_id, key)
            ).fetchone()
            if previous_key and previous_key != stat.stat_key:
                raise ValueError("stat_key is immutable")
            values = stat.model_dump(mode="json")
            values["created_at"] = existing["created_at"] if existing else now
            values["updated_at"] = now
            connection.execute(
                "INSERT INTO stat_definitions(project_id,stat_key,label,description,default_value,minimum,maximum,minimum_stat_key,maximum_stat_key,color,minimum_color,maximum_color,icon,display_style,integer_only,visibility,created_at,updated_at) "
                "VALUES(:project_id,:stat_key,:label,:description,:default_value,:minimum,:maximum,:minimum_stat_key,:maximum_stat_key,:color,:minimum_color,:maximum_color,:icon,:display_style,:integer_only,:visibility,:created_at,:updated_at) "
                "ON CONFLICT(project_id,stat_key) DO UPDATE SET label=excluded.label,description=excluded.description,default_value=excluded.default_value,minimum=excluded.minimum,maximum=excluded.maximum,minimum_stat_key=excluded.minimum_stat_key,maximum_stat_key=excluded.maximum_stat_key,color=excluded.color,minimum_color=excluded.minimum_color,maximum_color=excluded.maximum_color,icon=excluded.icon,display_style=excluded.display_style,integer_only=excluded.integer_only,visibility=excluded.visibility,updated_at=excluded.updated_at",
                values,
            )
            connection.execute("DELETE FROM stat_definition_owner_kinds WHERE project_id=? AND stat_key=?", (stat.project_id, stat.stat_key))
            connection.executemany(
                "INSERT INTO stat_definition_owner_kinds(project_id,stat_key,owner_kind) VALUES(?,?,?)",
                [(str(stat.project_id), stat.stat_key, str(kind)) for kind in stat.compatible_owner_kinds],
            )
        return self.stat(str(stat.project_id), stat.stat_key)  # type: ignore[return-value]

    def effects(self, project_id: str) -> list[EffectDefinition]:
        rows = self.db.fetch_all("SELECT * FROM effect_definitions WHERE project_id=? ORDER BY name,effect_key", (project_id,))
        return [EffectDefinition.model_validate({**row, "enabled": bool(row["enabled"]), "formula": self._formula(project_id, row["effect_key"])}) for row in rows]

    def effect(self, project_id: str, effect_key: str) -> EffectDefinition | None:
        return next((item for item in self.effects(project_id) if item.effect_key == effect_key), None)

    def _formula(self, project_id: str, effect_key: str) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT * FROM effect_formula_nodes WHERE project_id=? AND effect_key=? ORDER BY position", (project_id, effect_key)
        )
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for row in rows:
            by_parent.setdefault(row["parent_id"], []).append(row)
        def build(row: dict[str, Any]) -> dict[str, Any]:
            result: dict[str, Any] = {"kind": row["node_kind"]}
            if row["node_kind"] == "constant": result["value"] = row["constant_value"]
            if row["node_kind"] == "stat": result.update(participant=row["participant"], stat_key=row["stat_key"])
            children = by_parent.get(row["id"], [])
            if children: result["children"] = [build(child) for child in children]
            return result
        roots = by_parent.get(None, [])
        if len(roots) != 1:
            raise ValueError(f"Effect {effect_key} needs exactly one formula root")
        return build(roots[0])

    def save_effect(self, effect: EffectDefinition, *, previous_key: str | None = None) -> EffectDefinition:
        if previous_key and previous_key != effect.effect_key:
            raise ValueError("effect_key is immutable")
        self._validate_effect(effect)
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            existing = connection.execute("SELECT created_at FROM effect_definitions WHERE project_id=? AND effect_key=?", (effect.project_id, effect.effect_key)).fetchone()
            data = effect.model_dump(mode="json", exclude={"formula"})
            data.update(created_at=existing["created_at"] if existing else now, updated_at=now)
            connection.execute(
                "INSERT INTO effect_definitions(project_id,effect_key,name,description,target_stat_key,operation,clock,duration,tick_interval,evaluation_mode,stacking_policy,max_stacks,visibility,icon,enabled,created_at,updated_at) VALUES(:project_id,:effect_key,:name,:description,:target_stat_key,:operation,:clock,:duration,:tick_interval,:evaluation_mode,:stacking_policy,:max_stacks,:visibility,:icon,:enabled,:created_at,:updated_at) "
                "ON CONFLICT(project_id,effect_key) DO UPDATE SET name=excluded.name,description=excluded.description,target_stat_key=excluded.target_stat_key,operation=excluded.operation,clock=excluded.clock,duration=excluded.duration,tick_interval=excluded.tick_interval,evaluation_mode=excluded.evaluation_mode,stacking_policy=excluded.stacking_policy,max_stacks=excluded.max_stacks,visibility=excluded.visibility,icon=excluded.icon,enabled=excluded.enabled,updated_at=excluded.updated_at",
                data,
            )
            connection.execute("DELETE FROM effect_formula_nodes WHERE project_id=? AND effect_key=?", (effect.project_id, effect.effect_key))
            self._write_formula(connection, str(effect.project_id), effect.effect_key, effect.formula, None, 0)
        return self.effect(str(effect.project_id), effect.effect_key)  # type: ignore[return-value]

    def _write_formula(self, connection: Any, project_id: str, effect_key: str, node: FormulaNode, parent_id: str | None, position: int) -> None:
        node_id = new_id()
        connection.execute(
            "INSERT INTO effect_formula_nodes(id,project_id,effect_key,parent_id,position,node_kind,constant_value,participant,stat_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (node_id, project_id, effect_key, parent_id, position, str(node.kind), node.value, str(node.participant) if node.participant else None, node.stat_key),
        )
        for index, child in enumerate(node.children): self._write_formula(connection, project_id, effect_key, child, node_id, index)

    def abilities(self, project_id: str) -> list[Ability]:
        rows = self.db.fetch_all("SELECT * FROM ability_definitions WHERE project_id=? ORDER BY name,ability_key", (project_id,))
        return [self._ability(row) for row in rows]

    def ability(self, project_id: str, ability_key: str) -> Ability | None:
        row = self.db.fetch_one("SELECT * FROM ability_definitions WHERE project_id=? AND ability_key=?", (project_id, ability_key))
        return self._ability(row) if row else None

    def _ability(self, row: dict[str, Any]) -> Ability:
        project_id, key = row["project_id"], row["ability_key"]
        owners = [item["owner_kind"] for item in self.db.fetch_all("SELECT owner_kind FROM ability_owner_kinds WHERE project_id=? AND ability_key=? ORDER BY owner_kind", (project_id, key))]
        costs = [AbilityCost.model_validate({"kind": item["cost_kind"], "stat_key": item["stat_key"], "item_id": item["item_id"], "amount": item["amount"]}) for item in self.db.fetch_all("SELECT * FROM ability_costs WHERE project_id=? AND ability_key=? ORDER BY position", (project_id, key))]
        actions = [AbilityAction.model_validate({"kind": item["action_kind"], "target": item["target"], "effect_key": item["effect_key"], "destination_id": item["destination_id"], "entity_kind": item["entity_kind"], "entity_name": item["entity_name"], "state": json.loads(item["state_json"] or "{}"), "fact_id": item["fact_id"], "relation": item["relation"], "minutes": item["minutes"], "noise_id": item["noise_id"], "duration_override": item["duration_override"], "tick_override": item["tick_override"]}) for item in self.db.fetch_all("SELECT * FROM ability_actions WHERE project_id=? AND ability_key=? ORDER BY position", (project_id, key))]
        triggers = [PassiveTrigger.model_validate({"kind": item["trigger_kind"], "stat_key": item["stat_key"]}) for item in self.db.fetch_all("SELECT * FROM ability_passive_triggers WHERE project_id=? AND ability_key=?", (project_id, key))]
        skills = [item["skill_id"] for item in self.db.fetch_all("SELECT skill_id FROM ability_bullethell_skills WHERE project_id=? AND ability_key=? ORDER BY position", (project_id, key))]
        return Ability.model_validate({**row, "enabled": bool(row["enabled"]), "compatible_owner_kinds": owners, "requirements": self._requirement(project_id, key), "costs": costs, "actions": actions, "passive_triggers": triggers, "bullethell_skill_ids": skills})

    def _requirement(self, project_id: str, ability_key: str) -> dict[str, Any]:
        rows = self.db.fetch_all("SELECT * FROM ability_requirement_nodes WHERE project_id=? AND ability_key=? ORDER BY position", (project_id, ability_key))
        if not rows: return {}
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for row in rows: by_parent.setdefault(row["parent_id"], []).append(row)
        def build(row: dict[str, Any]) -> dict[str, Any]:
            result = {"kind": row["node_kind"], "target": row["target"]}
            for source, target in (("stat_key", "stat_key"), ("comparison", "comparison"), ("item_id", "item_id"), ("tag", "tag"), ("relation", "relation"), ("location_id", "location_id"), ("time_phase_id", "time_phase_id"), ("weather_id", "weather_id"), ("required_ability_key", "ability_key")):
                if row[source] is not None: result[target] = row[source]
            if row["value_json"] and row["value_json"] != '{"legacy": true}': result["value"] = json.loads(row["value_json"])
            children = by_parent.get(row["id"], [])
            if row["node_kind"] == "not": result["child"] = build(children[0])
            elif children: result["children"] = [build(child) for child in children]
            return result
        roots = by_parent.get(None, [])
        return build(roots[0]) if roots else {}

    def save_ability(self, ability: Ability, *, previous_key: str | None = None, available_ability_keys: set[str] | None = None) -> Ability:
        if previous_key and previous_key != ability.ability_key: raise ValueError("ability_key is immutable")
        self._validate_ability(ability, available_ability_keys)
        now = utc_now()
        with self.db._lock, self.db.connect() as connection:
            existing = connection.execute("SELECT created_at FROM ability_definitions WHERE project_id=? AND ability_key=?", (ability.project_id, ability.ability_key)).fetchone()
            data = ability.model_dump(mode="json", exclude={"compatible_owner_kinds", "requirements", "costs", "actions", "passive_triggers", "bullethell_skill_ids"})
            data.update(created_at=existing["created_at"] if existing else now, updated_at=now)
            connection.execute("INSERT INTO ability_definitions(project_id,ability_key,name,description,ability_kind,target_type,icon,enabled,timed_attack_line_count,timed_attack_damage_per_line,created_at,updated_at) VALUES(:project_id,:ability_key,:name,:description,:ability_kind,:target_type,:icon,:enabled,:timed_attack_line_count,:timed_attack_damage_per_line,:created_at,:updated_at) ON CONFLICT(project_id,ability_key) DO UPDATE SET name=excluded.name,description=excluded.description,ability_kind=excluded.ability_kind,target_type=excluded.target_type,icon=excluded.icon,enabled=excluded.enabled,timed_attack_line_count=excluded.timed_attack_line_count,timed_attack_damage_per_line=excluded.timed_attack_damage_per_line,updated_at=excluded.updated_at", data)
            for table in ("ability_owner_kinds", "ability_requirement_nodes", "ability_costs", "ability_actions", "ability_passive_triggers", "ability_bullethell_skills"):
                connection.execute(f"DELETE FROM {table} WHERE project_id=? AND ability_key=?", (ability.project_id, ability.ability_key))
            connection.executemany("INSERT INTO ability_owner_kinds(project_id,ability_key,owner_kind) VALUES(?,?,?)", [(str(ability.project_id), ability.ability_key, str(kind)) for kind in ability.compatible_owner_kinds])
            if ability.requirements.model_dump(exclude_defaults=True, exclude_none=True): self._write_requirement(connection, str(ability.project_id), ability.ability_key, ability.requirements, None, 0)
            connection.executemany("INSERT INTO ability_costs(id,project_id,ability_key,position,cost_kind,stat_key,item_id,amount) VALUES(?,?,?,?,?,?,?,?)", [(new_id(), str(ability.project_id), ability.ability_key, i, str(cost.kind), cost.stat_key, cost.item_id, cost.amount) for i, cost in enumerate(ability.costs)])
            connection.executemany("INSERT INTO ability_actions(id,project_id,ability_key,position,action_kind,target,effect_key,destination_id,entity_kind,entity_name,state_json,fact_id,relation,minutes,noise_id,duration_override,tick_override) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [(new_id(), str(ability.project_id), ability.ability_key, i, str(action.kind), action.target, action.effect_key, action.destination_id, str(action.entity_kind) if action.entity_kind else None, action.entity_name, json.dumps(action.state), action.fact_id, action.relation, action.minutes, action.noise_id, action.duration_override, action.tick_override) for i, action in enumerate(ability.actions)])
            connection.executemany("INSERT INTO ability_passive_triggers(id,project_id,ability_key,trigger_kind,stat_key) VALUES(?,?,?,?,?)", [(new_id(), str(ability.project_id), ability.ability_key, str(trigger.kind), trigger.stat_key) for trigger in ability.passive_triggers])
            connection.executemany("INSERT INTO ability_bullethell_skills(project_id,ability_key,skill_id,position) VALUES(?,?,?,?)", [(str(ability.project_id), ability.ability_key, skill, i) for i, skill in enumerate(ability.bullethell_skill_ids)])
        return self.ability(str(ability.project_id), ability.ability_key)  # type: ignore[return-value]

    def _write_requirement(self, connection: Any, project_id: str, ability_key: str, node: RequirementExpression, parent_id: str | None, position: int) -> None:
        node_id = new_id()
        connection.execute("INSERT INTO ability_requirement_nodes(id,project_id,ability_key,parent_id,position,node_kind,target,stat_key,comparison,value_json,item_id,tag,relation,location_id,time_phase_id,weather_id,required_ability_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (node_id, project_id, ability_key, parent_id, position, str(node.kind) if node.kind else None, node.target, node.stat_key, str(node.comparison), json.dumps(node.value) if node.value is not None else None, node.item_id, node.tag, node.relation, node.location_id, node.time_phase_id, node.weather_id, node.ability_key))
        children = node.children if node.kind in {"and", "or"} else ([node.child] if node.child else [])
        for index, child in enumerate(children): self._write_requirement(connection, project_id, ability_key, child, node_id, index)

    def warnings(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all("SELECT * FROM rule_migration_warnings WHERE project_id=? ORDER BY created_at", (project_id,))
        for row in rows: row["details"] = json.loads(row.pop("details_json")); row["acknowledged"] = bool(row["acknowledged"])
        return rows
