from __future__ import annotations

from dataclasses import dataclass
import secrets
import math
from typing import Any, Callable, Literal

from app.domain.adapters import entity_from_projection, relationship_from_projection
from app.domain.world import Ability, AbilityAction, AbilityCostKind, Character, ComparisonOperator, DomainReference, EffectDefinition, EffectTarget, FormulaNode, Item, Location, Relationship, RequirementExpression, Stat, resolve_stat_bounds
from app.domain.rules_v2 import (
    ConditionEvaluator,
    RuleEvaluationContext,
    RuleEvaluationError,
    RuleObjectResolver,
    RuleObjectSnapshot,
    ValueExpressionEvaluator,
    condition_expression_from_requirement,
    value_expression_from_formula,
)


class DomainOperationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    reference: DomainReference
    scope: str
    container: Any

    @property
    def id(self) -> str:
        return str(self.reference.id)


class TargetResolver:
    """Resolve semantic selectors to concrete canonical IDs before commit."""

    ALLIES = {"ally", "allied", "friend", "companion", "party", "member", "follower"}
    ENEMIES = {"enemy", "hostile", "rival", "opponent"}

    @staticmethod
    def _entity(projection: dict[str, Any], entity_id: str, kind: str) -> ResolvedTarget:
        raw = projection.get("entities", {}).get(entity_id)
        if not raw:
            raise DomainOperationError(f"Unknown entity: {entity_id}")
        value = entity_from_projection(raw)
        expected = Character if kind == "character" else Location
        if not isinstance(value, expected):
            raise DomainOperationError(f"Entity '{value.name}' is not a {kind}")
        return ResolvedTarget(value.reference, kind, value)  # type: ignore[arg-type]

    @staticmethod
    def _relationship(projection: dict[str, Any], relation_id: str) -> ResolvedTarget:
        raw = projection.get("relations", {}).get(relation_id)
        if not raw:
            raise DomainOperationError("Ability relationship target is unavailable")
        value = relationship_from_projection(raw)
        return ResolvedTarget(value.reference, "relationship", value)

    def resolve_ability_target(self, projection: dict[str, Any], actor: Character, ability: Ability, requested_target_id: str | None) -> ResolvedTarget:
        kind = str(ability.target_type)
        if kind == "self":
            if requested_target_id and requested_target_id != actor.id:
                raise DomainOperationError("This ability can target only its actor")
            return self._entity(projection, str(actor.id), "character")
        if kind in {"character", "choice"}:
            if not requested_target_id:
                raise DomainOperationError("This ability requires a character target")
            return self._entity(projection, requested_target_id, "character")
        if kind == "relationship":
            if not requested_target_id:
                raise DomainOperationError("This ability requires a relationship target")
            return self._relationship(projection, requested_target_id)
        if kind == "location":
            location_id = requested_target_id or actor.state.current_location_id
            if not location_id:
                raise DomainOperationError("This ability requires a location target")
            return self._entity(projection, str(location_id), "location")
        return self._entity(projection, str(actor.id), "character")

    def _related(self, projection: dict[str, Any], actor: Character, names: set[str]) -> list[ResolvedTarget]:
        ids: set[str] = set()
        for relation in projection.get("relations", {}).values():
            if str(relation.get("relation", "")).casefold() not in names:
                continue
            source, target = str(relation.get("source_id", "")), str(relation.get("target_id", ""))
            if source == actor.id:
                ids.add(target)
            elif target == actor.id and relation.get("bidirectional", True):
                ids.add(source)
        return [self._entity(projection, item, "character") for item in sorted(ids)
                if projection.get("entities", {}).get(item, {}).get("kind") == "character"]

    def _local(self, projection: dict[str, Any], actor: Character) -> list[ResolvedTarget]:
        location = actor.state.current_location_id
        return [self._entity(projection, key, "character") for key, raw in sorted(projection.get("entities", {}).items())
                if raw.get("kind") == "character" and raw.get("state", {}).get("current_location_id") == location
                and not raw.get("state", {}).get("archived")]

    def resolve_effect_targets(self, projection: dict[str, Any], actor: Character, primary: ResolvedTarget, ability: Ability, action: AbilityAction) -> list[ResolvedTarget]:
        selector = str(action.target or EffectTarget.TARGET)
        if selector == "actor": return [self._entity(projection, str(actor.id), "character")]
        if selector == "location":
            location_id = primary.id if primary.scope == "location" else actor.state.current_location_id
            if not location_id: raise DomainOperationError("Effect requires a current location")
            return [self._entity(projection, str(location_id), "location")]
        if selector == "relationship_target":
            if not isinstance(primary.container, Relationship): raise DomainOperationError("Effect requires a relationship target")
            other = primary.container.target_id if primary.container.source_id == actor.id else primary.container.source_id
            return [self._entity(projection, str(other), "character")]
        if selector in {"allies", "party"}:
            found = {item.id: item for item in self._related(projection, actor, self.ALLIES)}
            for item in getattr(actor.state, "party_ids", []) or []:
                if projection.get("entities", {}).get(str(item), {}).get("kind") == "character":
                    found[str(item)] = self._entity(projection, str(item), "character")
            found.setdefault(str(actor.id), self._entity(projection, str(actor.id), "character"))
            return list(found.values())
        if selector in {"enemies", "nearby_enemies"}:
            found = self._related(projection, actor, self.ENEMIES)
            return [item for item in found if selector == "enemies" or item.container.state.current_location_id == actor.state.current_location_id]
        if selector == "faction_members":
            factions = set(actor.state.faction_ids)
            return [item for item in self._local(projection, actor) if factions.intersection(item.container.state.faction_ids)]
        if selector == "all": return self._local(projection, actor)
        if selector == "random":
            candidates = [item for item in self._local(projection, actor) if item.id != actor.id]
            return [secrets.choice(candidates)] if candidates else []
        if selector == "target" and str(ability.target_type) in {"all", "party", "allies", "enemies", "nearby_enemies", "faction_members", "random"}:
            return self.resolve_effect_targets(projection, actor, primary, ability, action.model_copy(update={"target": str(ability.target_type)}))
        return [primary]

    def resolve_stat_target(self, projection: dict[str, Any], *, entity_id: Any = None, relation_id: Any = None) -> ResolvedTarget:
        try:
            if relation_id:
                return self._relationship(projection, str(relation_id))
            raw = projection.get("entities", {}).get(str(entity_id))
            if not raw: raise DomainOperationError("Stat target is not available")
            value = entity_from_projection(raw)
            return ResolvedTarget(value.reference, str(value.kind), value)
        except DomainOperationError as exc:
            raise DomainOperationError("Stat target is not available") from exc


StatLookup = Callable[..., Stat]
EffectiveStats = Callable[[Any], dict[str, float]]


class RequirementEvaluator:
    @staticmethod
    def _snapshot(value: Any, effective_stats: EffectiveStats) -> RuleObjectSnapshot:
        raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)
        kind = "relationship" if isinstance(value, Relationship) else str(raw.get("kind") or "object")
        return RuleObjectResolver.snapshot(raw, kind=kind, stats=effective_stats(value))

    def ensure_satisfied(self, actor: Character, ability: Ability, *, projection: dict[str, Any], primary_target: ResolvedTarget | None, stat_lookup: StatLookup, effective_stats: EffectiveStats) -> None:
        root = ability.requirements
        if not set(root.tags).issubset(set(actor.tags)):
            raise DomainOperationError(f"{actor.name} does not meet the ability requirements")
        stats = effective_stats(actor)
        for key, minimum in root.min_stats.items():
            definition = stat_lookup(key, "character")
            if float(stats.get(key, definition.default_value)) < float(minimum):
                raise DomainOperationError(f"{actor.name} does not meet the {definition.label} requirement")
        if not root.kind:
            return

        bindings = {
            "actor": self._snapshot(actor, effective_stats),
        }
        if primary_target is not None:
            bindings["target"] = self._snapshot(primary_target.container, effective_stats)
        context = RuleEvaluationContext(
            bindings=bindings,
            projection=projection,
            variables={
                "current_time_phase_id": projection.get("current_time_phase_id"),
                "current_weather_id": projection.get("current_weather_id"),
            },
        )
        try:
            condition = condition_expression_from_requirement(root)
            if not ConditionEvaluator().evaluate(condition, context, stat_lookup=stat_lookup):
                raise DomainOperationError(f"{actor.name} does not meet the ability requirements")
        except RuleEvaluationError as exc:
            raise DomainOperationError(str(exc)) from exc


@dataclass(slots=True)
class EffectExecution:
    costs: list[dict[str, Any]]
    effects: list[dict[str, Any]]


class EffectExecutor:
    def __init__(self, target_resolver: TargetResolver | None = None) -> None: self.targets = target_resolver or TargetResolver()

    @staticmethod
    def _bounded_value(
        definition: Stat,
        current: float,
        operation: str,
        amount: float,
        *,
        values: dict[str, float] | None = None,
        stat_lookup: StatLookup | None = None,
    ) -> int | float:
        value = (
            amount
            if operation == "set"
            else current * amount
            if operation == "multiply"
            else current + amount * (1 if operation == "add" else -1)
        )
        bounds = resolve_stat_bounds(
            definition,
            values or {},
            stat_lookup,
        )
        value = max(
            float(bounds.minimum),
            min(float(bounds.maximum), value),
        )
        return int(round(value)) if definition.integer_only else value

    def normalize(self, *, projection: dict[str, Any], actor: Character, primary_target: ResolvedTarget, ability: Ability, next_sequence: int, elapsed_minutes: int, stat_lookup: StatLookup, effective_stats: EffectiveStats, id_factory: Callable[[], str] | None = None) -> EffectExecution:
        working: dict[tuple[str, str, str], float] = {}
        actor_values = effective_stats(actor)
        def base(target: ResolvedTarget, definition: Stat) -> float:
            key = (target.scope, target.id, definition.stat_key)
            initial = actor_values.get(definition.stat_key, definition.default_value) if target.id == actor.id else target.container.stats.get(definition.stat_key, definition.default_value)
            working.setdefault(key, float(initial))
            return working[key]
        actor_target = self.targets._entity(projection, str(actor.id), "character")
        costs: list[dict[str, Any]] = []
        for ability_cost in ability.costs:
            if str(ability_cost.kind) != AbilityCostKind.STAT:
                continue
            key, cost = str(ability_cost.stat_key), float(ability_cost.amount)
            definition = stat_lookup(key, "character")
            current = base(actor_target, definition)
            if cost < 0: raise DomainOperationError("Ability costs cannot be negative")
            if current < cost: raise DomainOperationError(f"{actor.name} lacks enough {definition.label}")
            value = self._bounded_value(
                definition,
                current,
                "subtract",
                cost,
                values={**actor_values, key: current},
                stat_lookup=stat_lookup,
            )
            working[("character", str(actor.id), key)] = float(value)
            costs.append({"entity_id": str(actor.id), "stat_key": key, "value": value, "previous_value": current})
        return EffectExecution(costs, [])


class FormulaEvaluator:
    MAX_DEPTH = 12
    MAX_NODES = 64

    def evaluate(self, formula: FormulaNode, participants: dict[str, Any]) -> tuple[float, dict[str, float]]:
        bindings: dict[str, RuleObjectSnapshot] = {}
        for name, raw in participants.items():
            if isinstance(raw, RuleObjectSnapshot):
                bindings[name] = raw
                continue
            if hasattr(raw, "model_dump"):
                raw = raw.model_dump(mode="json")
            raw = dict(raw)
            bindings[name] = RuleObjectResolver.snapshot(
                raw,
                kind=str(raw.get("kind") or name),
                stats=raw.get("stats", {}),
            )
        try:
            return ValueExpressionEvaluator().evaluate(
                value_expression_from_formula(formula),
                RuleEvaluationContext(bindings=bindings),
            )
        except RuleEvaluationError as exc:
            message = str(exc)
            if "Value expression divides by zero" in message:
                message = "Effect formula divides by zero"
            elif "Value expression" in message:
                message = message.replace("Value expression", "Effect formula")
            raise DomainOperationError(message) from exc


class StatAdjustmentExecutor:
    def __init__(self, target_resolver: TargetResolver | None = None) -> None: self.targets = target_resolver or TargetResolver()
    def normalize(self, *, projection: dict[str, Any], entity_id: Any = None, relation_id: Any = None, stat_key: str, operation: str, amount: Any, stat_lookup: StatLookup, effective_values: Callable[[ResolvedTarget], dict[str, float]] | None = None) -> dict[str, Any]:
        target = self.targets.resolve_stat_target(projection, entity_id=entity_id, relation_id=relation_id)
        definition = stat_lookup(stat_key, target.scope)
        current, numeric = float(target.container.stats.get(definition.stat_key, definition.default_value)), float(amount)
        if operation not in {"add", "subtract", "set", "multiply"}: raise DomainOperationError("Stat operation must be add, subtract, set, or multiply")
        value = EffectExecutor._bounded_value(
            definition,
            current,
            operation,
            numeric,
            values=effective_values(target) if effective_values else {
                key: float(value) for key, value in target.container.stats.items()
            },
            stat_lookup=stat_lookup,
        )
        return {"relation_id" if target.scope == "relationship" else "entity_id": target.id, "stat_key": definition.stat_key, "value": value, "previous_value": current}
