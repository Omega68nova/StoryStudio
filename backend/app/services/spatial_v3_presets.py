from __future__ import annotations

from typing import Any

from app.database import new_id
from app.data.spatialV3Repository import SpatialV3Repository


class SpatialV3PresetError(ValueError):
    pass


_PRESETS: list[dict[str, Any]] = [
    {
        "key": "open_region",
        "label": "Open region",
        "description": "FREE navigation space with a full-area semantic surface.",
        "parameters": ["semantic_location_id", "name"],
    },
    {
        "key": "road",
        "label": "Road / route",
        "description": "Thick horizontal traversable corridor through the current space.",
        "parameters": ["name", "center_y", "width"],
    },
    {
        "key": "river",
        "label": "River",
        "description": "Thick water corridor with a higher travel multiplier.",
        "parameters": ["name", "center_y", "width"],
    },
    {
        "key": "city",
        "label": "City",
        "description": "City surface plus two crossing roads in a FREE space.",
        "parameters": ["semantic_location_id", "name", "center_x", "center_y", "width", "height"],
    },
    {
        "key": "walled_city",
        "label": "Walled city",
        "description": "City surface, crossing roads, and segmented walls with road openings.",
        "parameters": ["semantic_location_id", "name", "center_x", "center_y", "width", "height"],
    },
    {
        "key": "building",
        "label": "Building + interior",
        "description": "Building footprint in the current map, a ROUTED child space, floor surface, binding, and door connector.",
        "parameters": ["semantic_location_id", "name", "center_x", "center_y", "width", "height"],
        "requires_semantic_location": True,
    },
    {
        "key": "routed_room",
        "label": "Routed room / interior",
        "description": "Converts the current space to ROUTED and adds an inset floor surface.",
        "parameters": ["semantic_location_id", "name"],
    },
    {
        "key": "portal",
        "label": "Portal connection",
        "description": "Bidirectional portal connector from the current space to another navigation space.",
        "parameters": ["name", "target_space_id", "center_x", "center_y", "target_x", "target_y"],
        "requires_target_space": True,
    },
]


def public_spatial_v3_presets() -> list[dict[str, Any]]:
    return [dict(item) for item in _PRESETS]


def _num(params: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _rect(cx: float, cy: float, width: float, height: float) -> list[list[float]]:
    half_w, half_h = max(1.0, width) / 2, max(1.0, height) / 2
    left, right = _clamp(cx - half_w), _clamp(cx + half_w)
    top, bottom = _clamp(cy - half_h), _clamp(cy + half_h)
    return [[left, top], [right, top], [right, bottom], [left, bottom], [left, top]]


def _space_update(space: Any, mode: str) -> dict[str, Any]:
    payload = space.model_dump(mode="json")
    payload["navigation_mode"] = mode
    return {"tool": "upsertSpatialV3Space", "arguments": payload}


def _standard_layers(space_id: str) -> list[dict[str, Any]]:
    layers = [
        ("topology", "Topology", 0),
        ("regions", "Regions", 10),
        ("roads", "Roads / corridors", 20),
        ("places", "Places", 30),
        ("barriers", "Barriers", 40),
        ("connections", "Connections", 50),
    ]
    return [
        {
            "tool": "updateSpatialV3Layer",
            "arguments": {
                "navigation_space_id": space_id,
                "layer_key": key,
                "label": label,
                "position": position,
                "visible": True,
                "labels_mode": "important",
            },
        }
        for key, label, position in layers
    ]


def _surface(
    project_id: str,
    space_id: str,
    *,
    name: str,
    ring: list[list[float]],
    semantic_location_id: str | None,
    movement_priority: float = 0,
    environment_tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tool": "upsertSpatialV3Feature",
        "arguments": {
            "id": new_id(),
            "project_id": project_id,
            "navigation_space_id": space_id,
            "semantic_location_id": semantic_location_id,
            "feature_kind": "surface",
            "name": name,
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "render_layer": "regions",
            "render_order": 0,
            "movement_priority": movement_priority,
            "hidden": False,
            "discovered": True,
            "enabled": True,
            "metadata": {"preset_generated": True},
            "properties": {
                "traversal": {"default_allowed": True, "travel_multiplier": 1, "options": []},
                "ambience_tags": [],
                "environment_tags": environment_tags or [],
            },
        },
    }


def _corridor(
    project_id: str,
    space_id: str,
    *,
    name: str,
    points: list[list[float]],
    width: float,
    multiplier: float = 1,
    ambience_tags: list[str] | None = None,
    movement_priority: float = 10,
) -> dict[str, Any]:
    return {
        "tool": "upsertSpatialV3Feature",
        "arguments": {
            "id": new_id(),
            "project_id": project_id,
            "navigation_space_id": space_id,
            "semantic_location_id": None,
            "feature_kind": "corridor",
            "name": name,
            "geometry": {"type": "LineString", "coordinates": points},
            "render_layer": "roads",
            "render_order": 0,
            "movement_priority": movement_priority,
            "hidden": False,
            "discovered": True,
            "enabled": True,
            "metadata": {"preset_generated": True},
            "properties": {
                "width": max(0.1, width),
                "traversal": {"default_allowed": True, "travel_multiplier": max(0.01, multiplier), "options": []},
                "ambience_tags": ambience_tags or [],
            },
        },
    }


def _barrier(
    project_id: str,
    space_id: str,
    *,
    name: str,
    lines: list[list[list[float]]],
) -> dict[str, Any]:
    return {
        "tool": "upsertSpatialV3Feature",
        "arguments": {
            "id": new_id(),
            "project_id": project_id,
            "navigation_space_id": space_id,
            "semantic_location_id": None,
            "feature_kind": "barrier",
            "name": name,
            "geometry": {"type": "MultiLineString", "coordinates": lines},
            "render_layer": "barriers",
            "render_order": 0,
            "movement_priority": 100,
            "hidden": False,
            "discovered": True,
            "enabled": True,
            "metadata": {"preset_generated": True},
            "properties": {
                "traversal": {"default_allowed": False, "travel_multiplier": 1, "options": []},
            },
        },
    }


def _connector(
    project_id: str,
    space_id: str,
    *,
    name: str,
    kind: str,
    source: list[float],
    target_space_id: str,
    target: list[float],
    travel_minutes: float | None = None,
) -> dict[str, Any]:
    return {
        "tool": "upsertSpatialV3Feature",
        "arguments": {
            "id": new_id(),
            "project_id": project_id,
            "navigation_space_id": space_id,
            "semantic_location_id": None,
            "feature_kind": "connector",
            "name": name,
            "geometry": {"type": "Point", "coordinates": source},
            "render_layer": "connections",
            "render_order": 0,
            "movement_priority": 100,
            "hidden": False,
            "discovered": True,
            "enabled": True,
            "metadata": {"preset_generated": True},
            "properties": {
                "connector_kind": kind,
                "source": {"navigation_space_id": space_id, "point": source},
                "target": {"navigation_space_id": target_space_id, "point": target},
                "traversal": {"default_allowed": True, "travel_multiplier": 1, "options": []},
                "travel_minutes": travel_minutes,
                "bidirectional": True,
            },
        },
    }


def build_spatial_v3_preset(
    repository: SpatialV3Repository,
    project_id: str,
    preset_key: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    space_id = str(params.get("navigation_space_id") or "").strip()
    if not space_id:
        raise SpatialV3PresetError("Preset requires navigation_space_id")
    space = repository.space(space_id)
    if not space or space.project_id != project_id:
        raise SpatialV3PresetError("Navigation space not found")

    cx, cy = _num(params, "center_x", 50), _num(params, "center_y", 50)
    width, height = _num(params, "width", 60), _num(params, "height", 60)
    feature_width = _num(params, "width", 6)
    semantic_id = str(params.get("semantic_location_id") or "").strip() or space.owner_location_id
    name = str(params.get("name") or "").strip()
    rows: list[dict[str, Any]] = [*_standard_layers(space_id)]

    if preset_key == "open_region":
        rows.insert(0, _space_update(space, "free"))
        rows.append(_surface(
            project_id, space_id,
            name=name or "Open region",
            ring=_rect(50, 50, 100, 100),
            semantic_location_id=semantic_id,
            environment_tags=["outdoor", "region"],
        ))
        return rows

    if preset_key == "road":
        rows.append(_corridor(
            project_id, space_id,
            name=name or "Road",
            points=[[0, _clamp(cy)], [100, _clamp(cy)]],
            width=feature_width,
        ))
        return rows

    if preset_key == "river":
        rows.append(_corridor(
            project_id, space_id,
            name=name or "River",
            points=[[0, _clamp(cy - 8)], [50, _clamp(cy + 5)], [100, _clamp(cy - 3)]],
            width=max(2, feature_width),
            multiplier=1.5,
            ambience_tags=["water", "river"],
            movement_priority=8,
        ))
        return rows

    if preset_key in {"city", "walled_city"}:
        ring = _rect(cx, cy, width, height)
        rows.insert(0, _space_update(space, "free"))
        rows.append(_surface(
            project_id, space_id,
            name=name or ("Walled city" if preset_key == "walled_city" else "City"),
            ring=ring,
            semantic_location_id=semantic_id,
            movement_priority=1,
            environment_tags=["city", "outdoor"],
        ))
        road_width = max(2, min(width, height) * 0.08)
        rows.append(_corridor(
            project_id, space_id, name="Main road",
            points=[[ring[0][0], cy], [ring[1][0], cy]], width=road_width, movement_priority=20,
        ))
        rows.append(_corridor(
            project_id, space_id, name="Cross road",
            points=[[cx, ring[0][1]], [cx, ring[2][1]]], width=road_width, movement_priority=20,
        ))
        if preset_key == "walled_city":
            left, top = ring[0]
            right, bottom = ring[2]
            gap = max(2, road_width * 0.7)
            lines = [
                [[left, top], [cx - gap, top]], [[cx + gap, top], [right, top]],
                [[left, bottom], [cx - gap, bottom]], [[cx + gap, bottom], [right, bottom]],
                [[left, top], [left, cy - gap]], [[left, cy + gap], [left, bottom]],
                [[right, top], [right, cy - gap]], [[right, cy + gap], [right, bottom]],
            ]
            rows.append(_barrier(project_id, space_id, name="City walls", lines=lines))
        return rows

    if preset_key == "routed_room":
        rows.insert(0, _space_update(space, "routed"))
        rows.append(_surface(
            project_id, space_id,
            name=name or "Room floor",
            ring=_rect(50, 50, 88, 88),
            semantic_location_id=semantic_id,
            movement_priority=1,
            environment_tags=["indoor", "room"],
        ))
        return rows

    if preset_key == "building":
        semantic_location_id = str(params.get("semantic_location_id") or "").strip()
        if not semantic_location_id:
            raise SpatialV3PresetError("Building preset requires semantic_location_id")
        if repository.location_space(project_id, semantic_location_id):
            raise SpatialV3PresetError("That location already owns a navigation space")
        child_space_id = new_id()
        footprint = _rect(cx, cy, max(8, width), max(8, height))
        rows.append(_surface(
            project_id, space_id,
            name=name or "Building",
            ring=footprint,
            semantic_location_id=semantic_location_id,
            movement_priority=5,
            environment_tags=["building"],
        ))
        rows.append({
            "tool": "upsertSpatialV3Space",
            "arguments": {
                "id": child_space_id,
                "project_id": project_id,
                "owner_location_id": semantic_location_id,
                "navigation_mode": "routed",
                "base_travel_multiplier": 1,
                "bounds": None,
                "revision": 1,
            },
        })
        rows.append({
            "tool": "bindSpatialV3LocationSpace",
            "arguments": {
                "project_id": project_id,
                "location_id": semantic_location_id,
                "navigation_space_id": child_space_id,
                "entrance_policy": "connectors",
                "bounds_mode": "independent",
            },
        })
        rows.extend(_standard_layers(child_space_id))
        rows.append(_surface(
            project_id, child_space_id,
            name=f"{name or 'Building'} interior",
            ring=_rect(50, 50, 90, 90),
            semantic_location_id=semantic_location_id,
            movement_priority=1,
            environment_tags=["indoor", "building"],
        ))
        source = [cx, _clamp(cy + max(8, height) / 2)]
        rows.append(_connector(
            project_id, space_id,
            name=f"{name or 'Building'} door",
            kind="door",
            source=source,
            target_space_id=child_space_id,
            target=[50, 95],
        ))
        return rows

    if preset_key == "portal":
        target_space_id = str(params.get("target_space_id") or "").strip()
        target_space = repository.space(target_space_id) if target_space_id else None
        if not target_space or target_space.project_id != project_id:
            raise SpatialV3PresetError("Portal preset requires a valid target_space_id")
        rows.append(_connector(
            project_id, space_id,
            name=name or "Portal",
            kind="portal",
            source=[_clamp(cx), _clamp(cy)],
            target_space_id=target_space_id,
            target=[_clamp(_num(params, "target_x", 50)), _clamp(_num(params, "target_y", 50))],
        ))
        return rows

    raise SpatialV3PresetError(f"Unknown Spatial V3 preset: {preset_key}")
