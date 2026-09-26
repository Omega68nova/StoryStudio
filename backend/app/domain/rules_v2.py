from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Callable

from pydantic import Field, model_validator

from app.domain.world import (
    ComparisonOperator,
    DomainModel,
    FormulaNode,
    RequirementExpression,
)


class RuleEvaluationError(ValueError):
    pass


class RuleSelectorKind(StrEnum):
    ACTOR = "actor"
    SOURCE = "source"
    TARGET = "target"
    CURRENT_LOCATION = "current_location"
    ABILITY = "ability"
    EXPLICIT = "explicit"
    RELATIONSHIP_TARGET = "relationship_target"


class RuleObjectSelector(DomainModel):
    """A stable description of where a rule obtains an object.

    Selectors intentionally describe *roles* rather than embedding a concrete
    runtime object. Runtime contexts bind those roles to object snapshots.
    """

    kind: RuleSelectorKind
    object_id: str | None = None
    object_kind: str | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> "RuleObjectSelector":
        if self.kind == RuleSelectorKind.EXPLICIT and not self.object_id:
            raise ValueError("explicit object selector requires object_id")
        if self.kind != RuleSelectorKind.EXPLICIT and (
            self.object_id is not None or self.object_kind is not None
        ):
            raise ValueError("only explicit selectors may contain object_id/object_kind")
        return self


class RuleObjectSnapshot(DomainModel):
    """Rule-safe view of an object.

    The evaluator needs only identity, kind, effective stats, tags and state.
    Keeping this small prevents rule evaluation from depending on concrete
    Pydantic entity classes.
    """

    id: str
    kind: str
    stats: dict[str, float] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class RuleEvaluationContext(DomainModel):
    bindings: dict[str, RuleObjectSnapshot] = Field(default_factory=dict)
    projection: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)


class ValueExpressionKind(StrEnum):
    CONSTANT = "constant"
    STAT = "stat"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    NEGATE = "negate"


class ValueExpression(DomainModel):
    kind: ValueExpressionKind
    value: float | None = None
    selector: RuleObjectSelector | None = None
    stat_key: str | None = None
    children: list["ValueExpression"] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> "ValueExpression":
        if self.kind == ValueExpressionKind.CONSTANT:
            if self.value is None or self.selector or self.stat_key or self.children:
                raise ValueError("constant value expressions contain only value")
        elif self.kind == ValueExpressionKind.STAT:
            if not self.selector or not self.stat_key or self.value is not None or self.children:
                raise ValueError("stat value expressions need selector and stat_key")
        else:
            expected = 1 if self.kind == ValueExpressionKind.NEGATE else 2
            if len(self.children) != expected or self.value is not None or self.selector or self.stat_key:
                raise ValueError(f"{self.kind} value expressions need {expected} children")
        return self


class ConditionKind(StrEnum):
    AND = "and"
    OR = "or"
    NOT = "not"
    COMPARE = "compare"
    EXISTS = "exists"
    HAS_TAG = "has_tag"
    HAS_ITEM = "has_item"
    HAS_ABILITY = "has_ability"
    RELATIONSHIP = "relationship"
    LOCATION = "location"
    TIME = "time"
    WEATHER = "weather"


class ConditionExpression(DomainModel):
    kind: ConditionKind
    children: list["ConditionExpression"] = Field(default_factory=list)
    child: "ConditionExpression | None" = None
    left: ValueExpression | None = None
    right: ValueExpression | None = None
    comparison: ComparisonOperator = ComparisonOperator.GTE
    selector: RuleObjectSelector | None = None
    tag: str | None = None
    item_id: str | None = None
    ability_key: str | None = None
    relation: str | None = None
    location_id: str | None = None
    time_phase_id: str | None = None
    weather_id: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ConditionExpression":
        if self.kind in {ConditionKind.AND, ConditionKind.OR} and not self.children:
            raise ValueError("and/or conditions require children")
        if self.kind == ConditionKind.NOT and self.child is None:
            raise ValueError("not condition requires child")
        if self.kind == ConditionKind.COMPARE and (self.left is None or self.right is None):
            raise ValueError("compare condition requires left and right values")
        if self.kind in {
            ConditionKind.EXISTS,
            ConditionKind.HAS_TAG,
            ConditionKind.HAS_ITEM,
            ConditionKind.HAS_ABILITY,
            ConditionKind.RELATIONSHIP,
            ConditionKind.LOCATION,
        } and self.selector is None:
            raise ValueError(f"{self.kind} condition requires selector")
        required = {
            ConditionKind.HAS_TAG: self.tag,
            ConditionKind.HAS_ITEM: self.item_id,
            ConditionKind.HAS_ABILITY: self.ability_key,
            ConditionKind.RELATIONSHIP: self.relation,
            ConditionKind.LOCATION: self.location_id,
            ConditionKind.TIME: self.time_phase_id,
            ConditionKind.WEATHER: self.weather_id,
        }
        if self.kind in required and not required[self.kind]:
            raise ValueError(f"{self.kind} condition is missing its reference")
        return self


StatDefinitionLookup = Callable[[str, str], Any]


class RuleObjectResolver:
    @staticmethod
    def snapshot(raw: dict[str, Any], *, kind: str | None = None, stats: dict[str, Any] | None = None) -> RuleObjectSnapshot:
        resolved_kind = kind or str(raw.get("kind") or ("relationship" if "source_id" in raw and "target_id" in raw else "object"))
        return RuleObjectSnapshot(
            id=str(raw.get("id") or ""),
            kind=resolved_kind,
            stats={key: float(value) for key, value in (stats if stats is not None else raw.get("stats", {})).items()},
            tags=[str(value) for value in raw.get("tags", [])],
            state=dict(raw.get("state") or {}),
            raw=dict(raw),
        )

    def resolve(self, selector: RuleObjectSelector, context: RuleEvaluationContext) -> RuleObjectSnapshot | None:
        kind = str(selector.kind)
        if kind in {"actor", "source", "target", "ability"}:
            return context.bindings.get(kind)
        if kind == "explicit":
            object_id = str(selector.object_id or "")
            if selector.object_kind == "relationship":
                raw = context.projection.get("relations", {}).get(object_id)
                return self.snapshot(raw, kind="relationship") if raw else None
            raw = context.projection.get("entities", {}).get(object_id)
            if raw and (not selector.object_kind or str(raw.get("kind")) == selector.object_kind):
                return self.snapshot(raw)
            raw = context.projection.get("relations", {}).get(object_id)
            if raw and (not selector.object_kind or selector.object_kind == "relationship"):
                return self.snapshot(raw, kind="relationship")
            return None
        if kind == "current_location":
            actor = context.bindings.get("actor")
            if not actor:
                return None
            location_id = actor.state.get("current_location_id")
            if not location_id:
                return None
            raw = context.projection.get("entities", {}).get(str(location_id))
            return self.snapshot(raw) if raw else None
        if kind == "relationship_target":
            target = context.bindings.get("target")
            actor = context.bindings.get("actor")
            if not target or target.kind != "relationship" or not actor:
                return None
            source_id = str(target.raw.get("source_id") or "")
            target_id = str(target.raw.get("target_id") or "")
            other_id = target_id if source_id == actor.id else source_id
            raw = context.projection.get("entities", {}).get(other_id)
            return self.snapshot(raw) if raw else None
        raise RuleEvaluationError(f"Unsupported rule object selector: {kind}")


class ValueExpressionEvaluator:
    MAX_DEPTH = 12
    MAX_NODES = 64

    def __init__(self, resolver: RuleObjectResolver | None = None) -> None:
        self.resolver = resolver or RuleObjectResolver()

    def evaluate(
        self,
        expression: ValueExpression,
        context: RuleEvaluationContext,
        *,
        stat_lookup: StatDefinitionLookup | None = None,
    ) -> tuple[float, dict[str, float]]:
        inputs: dict[str, float] = {}
        count = 0

        def visit(node: ValueExpression, depth: int) -> float:
            nonlocal count
            count += 1
            if depth > self.MAX_DEPTH or count > self.MAX_NODES:
                raise RuleEvaluationError("Value expression exceeds complexity limits")
            kind = str(node.kind)
            if kind == "constant":
                result = float(node.value)
            elif kind == "stat":
                owner = self.resolver.resolve(node.selector, context)  # type: ignore[arg-type]
                label = str(node.selector.kind)  # type: ignore[union-attr]
                if owner is None:
                    raise RuleEvaluationError(f"{label} object is unavailable")
                if stat_lookup is not None:
                    definition = stat_lookup(str(node.stat_key), owner.kind)
                    if definition is None:
                        raise RuleEvaluationError(f"{owner.kind} is incompatible with stat {node.stat_key}")
                if str(node.stat_key) not in owner.stats:
                    raise RuleEvaluationError(f"{label} is missing stat {node.stat_key}")
                result = float(owner.stats[str(node.stat_key)])
                inputs[f"{label}.{node.stat_key}"] = result
            else:
                values = [visit(child, depth + 1) for child in node.children]
                if kind == "negate":
                    result = -values[0]
                elif kind == "add":
                    result = values[0] + values[1]
                elif kind == "subtract":
                    result = values[0] - values[1]
                elif kind == "multiply":
                    result = values[0] * values[1]
                elif kind == "divide":
                    if values[1] == 0:
                        raise RuleEvaluationError("Value expression divides by zero")
                    result = values[0] / values[1]
                elif kind == "minimum":
                    result = min(values)
                elif kind == "maximum":
                    result = max(values)
                else:
                    raise RuleEvaluationError(f"Unknown value expression node: {kind}")
            if not math.isfinite(result):
                raise RuleEvaluationError("Value expression produced a non-finite result")
            return result

        return visit(expression, 1), inputs


class ConditionEvaluator:
    def __init__(
        self,
        resolver: RuleObjectResolver | None = None,
        values: ValueExpressionEvaluator | None = None,
    ) -> None:
        self.resolver = resolver or RuleObjectResolver()
        self.values = values or ValueExpressionEvaluator(self.resolver)

    @staticmethod
    def _compare(left: Any, operation: str, right: Any) -> bool:
        if operation == "eq":
            return left == right
        if operation == "ne":
            return left != right
        try:
            left_value, right_value = float(left), float(right)
        except (TypeError, ValueError):
            return False
        return {
            "lt": left_value < right_value,
            "lte": left_value <= right_value,
            "gt": left_value > right_value,
            "gte": left_value >= right_value,
        }.get(operation, False)

    def evaluate(
        self,
        condition: ConditionExpression,
        context: RuleEvaluationContext,
        *,
        stat_lookup: StatDefinitionLookup | None = None,
    ) -> bool:
        kind = str(condition.kind)
        if kind == "and":
            return all(self.evaluate(item, context, stat_lookup=stat_lookup) for item in condition.children)
        if kind == "or":
            return any(self.evaluate(item, context, stat_lookup=stat_lookup) for item in condition.children)
        if kind == "not":
            return not self.evaluate(condition.child, context, stat_lookup=stat_lookup)  # type: ignore[arg-type]
        if kind == "compare":
            left, _ = self.values.evaluate(condition.left, context, stat_lookup=stat_lookup)  # type: ignore[arg-type]
            right, _ = self.values.evaluate(condition.right, context, stat_lookup=stat_lookup)  # type: ignore[arg-type]
            return self._compare(left, str(condition.comparison), right)
        if kind == "time":
            return str(context.variables.get("current_time_phase_id") or "") == str(condition.time_phase_id)
        if kind == "weather":
            return str(context.variables.get("current_weather_id") or "") == str(condition.weather_id)

        owner = self.resolver.resolve(condition.selector, context)  # type: ignore[arg-type]
        if kind == "exists":
            return owner is not None
        if owner is None:
            return False
        if kind == "has_tag":
            return str(condition.tag) in set(owner.tags)
        if kind == "has_item":
            return any(
                str(item.get("item_id") if isinstance(item, dict) else getattr(item, "item_id", "")) == str(condition.item_id)
                and int(item.get("quantity", 0) if isinstance(item, dict) else getattr(item, "quantity", 0)) > 0
                for item in owner.state.get("inventory", [])
            )
        if kind == "has_ability":
            return str(condition.ability_key) in {str(value) for value in owner.state.get("abilities", [])}
        if kind == "location":
            if owner.kind == "location":
                return owner.id == str(condition.location_id)
            return str(owner.state.get("current_location_id") or "") == str(condition.location_id)
        if kind == "relationship":
            relation_name = str(condition.relation or "").casefold()
            if owner.kind == "relationship":
                return str(owner.raw.get("relation") or "").casefold() == relation_name
            return any(
                str(row.get("relation") or "").casefold() == relation_name
                and owner.id in {str(row.get("source_id") or ""), str(row.get("target_id") or "")}
                for row in context.projection.get("relations", {}).values()
            )
        raise RuleEvaluationError(f"Unsupported condition node: {kind}")


def value_expression_from_formula(node: FormulaNode) -> ValueExpression:
    kind = str(node.kind)
    if kind == "constant":
        return ValueExpression(kind="constant", value=float(node.value))
    if kind == "stat":
        return ValueExpression(
            kind="stat",
            selector=RuleObjectSelector(kind=str(node.participant)),
            stat_key=str(node.stat_key),
        )
    return ValueExpression(
        kind=kind,
        children=[value_expression_from_formula(child) for child in node.children],
    )


def _legacy_target_selector(target: str | None) -> RuleObjectSelector:
    return RuleObjectSelector(kind="actor" if str(target or "actor") == "actor" else "target")


def condition_expression_from_requirement(node: RequirementExpression) -> ConditionExpression:
    kind = str(node.kind)
    if kind in {"and", "or"}:
        return ConditionExpression(
            kind=kind,
            children=[condition_expression_from_requirement(child) for child in node.children],
        )
    if kind == "not":
        return ConditionExpression(
            kind="not",
            child=condition_expression_from_requirement(node.child),  # type: ignore[arg-type]
        )
    selector = _legacy_target_selector(str(node.target))
    if kind == "compare":
        return ConditionExpression(
            kind="compare",
            comparison=node.comparison,
            left=ValueExpression(kind="stat", selector=selector, stat_key=str(node.stat_key)),
            right=ValueExpression(kind="constant", value=float(node.value)),  # type: ignore[arg-type]
        )
    if kind == "has_tag":
        return ConditionExpression(kind="has_tag", selector=selector, tag=node.tag)
    if kind == "has_item":
        return ConditionExpression(kind="has_item", selector=selector, item_id=str(node.item_id))
    if kind == "has_ability":
        return ConditionExpression(kind="has_ability", selector=selector, ability_key=node.ability_key)
    if kind == "relationship":
        return ConditionExpression(kind="relationship", selector=selector, relation=node.relation)
    if kind == "location":
        return ConditionExpression(kind="location", selector=selector, location_id=str(node.location_id))
    if kind == "time":
        return ConditionExpression(kind="time", time_phase_id=str(node.time_phase_id))
    if kind == "weather":
        return ConditionExpression(kind="weather", weather_id=str(node.weather_id))
    raise RuleEvaluationError(f"Unsupported legacy requirement kind: {kind}")
