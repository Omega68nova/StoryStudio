from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from app.domain.world import (
    Ability,
    Character,
    EntityKind,
    Fact,
    Faction,
    GenericWorldEntity,
    Item,
    Location,
    LoreSystem,
    Outfit,
    PlotBeat,
    Relationship,
    Stat,
    TypedWorldEntity,
    Weather,
)


class DomainAdapterError(ValueError):
    pass


def _record(value: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(value))


def _json_field(
    record: dict[str, Any],
    field: str,
    expected: type[dict[Any, Any]] | type[list[Any]],
) -> Any:
    raw = record.pop(field, None)
    if raw is None:
        return expected()
    if not isinstance(raw, str):
        raise DomainAdapterError(f"{field} must contain JSON text")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DomainAdapterError(f"{field} contains malformed JSON") from exc
    if not isinstance(parsed, expected):
        label = "object" if expected is dict else "array"
        raise DomainAdapterError(f"{field} must contain a JSON {label}")
    return parsed


def _dump(model: Any) -> dict[str, Any]:
    return copy.deepcopy(
        model.model_dump(
            mode="json",
            exclude_unset=True,
        )
    )


def entity_from_projection(value: Mapping[str, Any]) -> TypedWorldEntity:
    raw = _record(value)
    kind = raw.get("kind")
    if kind == EntityKind.CHARACTER:
        return Character.model_validate(raw)
    if kind == EntityKind.LOCATION:
        return Location.model_validate(raw)
    if kind == EntityKind.FACTION:
        return Faction.model_validate(raw)
    if kind == EntityKind.ITEM:
        return Item.model_validate(raw)
    if kind == EntityKind.LORE_SYSTEM:
        return LoreSystem.model_validate(raw)
    if kind == EntityKind.FACT:
        return Fact.model_validate(raw)
    if kind == EntityKind.PLOT_BEAT:
        return PlotBeat.model_validate(raw)
    return GenericWorldEntity.model_validate(raw)


def entity_to_projection(entity: TypedWorldEntity) -> dict[str, Any]:
    return _dump(entity)


def relationship_from_projection(
    value: Mapping[str, Any],
) -> Relationship:
    return Relationship.model_validate(_record(value))


def relationship_to_projection(
    relationship: Relationship,
) -> dict[str, Any]:
    return _dump(relationship)


def outfit_from_record(value: Mapping[str, Any]) -> Outfit:
    raw = _record(value)
    legacy_appearance = raw.pop("appearance", None)
    if "imagegen_description" not in raw:
        raw["imagegen_description"] = legacy_appearance or ""
    raw["equipment"] = _json_field(raw, "equipment_json", list)
    return Outfit.model_validate(raw)


def outfit_to_record(outfit: Outfit) -> dict[str, Any]:
    raw = _dump(outfit)
    raw["equipment_json"] = json.dumps(raw.pop("equipment", []))
    return raw


def weather_from_record(value: Mapping[str, Any]) -> Weather:
    raw = _record(value)
    raw["tags"] = _json_field(raw, "tags_json", list)
    raw["image_tags"] = _json_field(raw, "image_tags_json", list)
    if "enabled" in raw:
        raw["enabled"] = bool(raw["enabled"])
    return Weather.model_validate(raw)


def weather_to_record(weather: Weather) -> dict[str, Any]:
    raw = _dump(weather)
    raw["tags_json"] = json.dumps(raw.pop("tags", []))
    raw["image_tags_json"] = json.dumps(raw.pop("image_tags", []))
    if "enabled" in raw:
        raw["enabled"] = int(raw["enabled"])
    return raw


def stat_from_record(value: Mapping[str, Any]) -> Stat:
    raw = _record(value)
    if "integer_only" in raw:
        raw["integer_only"] = bool(raw["integer_only"])
    return Stat.model_validate(raw)


def stat_to_record(stat: Stat) -> dict[str, Any]:
    raw = _dump(stat)
    if "integer_only" in raw:
        raw["integer_only"] = int(raw["integer_only"])
    return raw


def ability_from_record(value: Mapping[str, Any]) -> Ability:
    raw = _record(value)
    raw["requirements"] = _json_field(raw, "requirements_json", dict)
    raw["costs"] = _json_field(raw, "costs_json", dict)
    raw["effects"] = _json_field(raw, "effects_json", list)
    raw["minigame_profile"] = _json_field(
        raw,
        "minigame_profile_json",
        dict,
    )
    return Ability.model_validate(raw)


def ability_to_record(ability: Ability) -> dict[str, Any]:
    raw = _dump(ability)
    raw["requirements_json"] = json.dumps(raw.pop("requirements", {}))
    raw["costs_json"] = json.dumps(raw.pop("costs", {}))
    raw["effects_json"] = json.dumps(raw.pop("effects", []))
    raw["minigame_profile_json"] = json.dumps(
        raw.pop("minigame_profile", {})
    )
    return raw
