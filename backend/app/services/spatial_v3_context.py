from __future__ import annotations

from typing import Any

try:
    from shapely import affinity
    from shapely.geometry import GeometryCollection, box, mapping, shape
    from shapely.ops import unary_union
except ImportError:  # pragma: no cover
    affinity = GeometryCollection = box = mapping = shape = unary_union = None  # type: ignore[assignment]

from app.data.spatialV3Repository import SpatialV3Repository
from app.domain.spatial_v3 import CorridorProperties, MapFeature, NavigationSpace


class SpatialV3ContextError(ValueError):
    pass


def _require_geometry() -> None:
    if any(item is None for item in (affinity, box, mapping, shape, unary_union)):
        raise SpatialV3ContextError(
            "Spatial V3 inherited context requires Shapely; install backend requirements and restart StoryStudio"
        )


def _target_box(space: NavigationSpace) -> tuple[float, float, float, float]:
    if space.bounds is None:
        return 0.0, 0.0, 100.0, 100.0
    geom = shape(space.bounds.model_dump(mode="json"))
    if geom.is_empty:
        return 0.0, 0.0, 100.0, 100.0
    return tuple(float(value) for value in geom.bounds)  # type: ignore[return-value]


def _transform_geometry(geometry: Any, source_bounds: tuple[float, float, float, float], target_bounds: tuple[float, float, float, float]) -> Any:
    source_min_x, source_min_y, source_max_x, source_max_y = source_bounds
    target_min_x, target_min_y, target_max_x, target_max_y = target_bounds
    source_width = max(source_max_x - source_min_x, 1e-9)
    source_height = max(source_max_y - source_min_y, 1e-9)
    x_scale = (target_max_x - target_min_x) / source_width
    y_scale = (target_max_y - target_min_y) / source_height
    moved = affinity.translate(geometry, xoff=-source_min_x, yoff=-source_min_y)
    moved = affinity.scale(moved, xfact=x_scale, yfact=y_scale, origin=(0, 0))
    return affinity.translate(moved, xoff=target_min_x, yoff=target_min_y)


def _compatible_geometry(feature: MapFeature, geometry: Any) -> Any | None:
    if geometry.is_empty:
        return None
    kind = str(feature.feature_kind)
    if kind == "surface":
        if geometry.geom_type in {"Polygon", "MultiPolygon"}:
            return geometry
        polygons = [part for part in getattr(geometry, "geoms", []) if part.geom_type in {"Polygon", "MultiPolygon"}]
        return unary_union(polygons) if polygons else None
    if kind in {"corridor", "barrier"}:
        if geometry.geom_type in {"LineString", "MultiLineString"}:
            return geometry
        lines = [part for part in getattr(geometry, "geoms", []) if part.geom_type in {"LineString", "MultiLineString"}]
        return unary_union(lines) if lines else None
    if kind in {"spot", "connector"}:
        if geometry.geom_type == "Point":
            return geometry
        points = [part for part in getattr(geometry, "geoms", []) if part.geom_type == "Point"]
        return points[0] if points else None
    return None


def inherited_parent_context(
    repository: SpatialV3Repository,
    *,
    project_id: str,
    space: NavigationSpace,
    projection: dict[str, Any],
) -> dict[str, Any] | None:
    """Project a location's parent-space footprint/context into its own space.

    The result is derived, never persisted. Editing parent geometry therefore
    updates inherited child context immediately on the next read.
    """
    _require_geometry()
    owner_location_id = space.owner_location_id
    if not owner_location_id:
        return None

    binding = repository.location_space(project_id, owner_location_id)
    if not binding or str(binding.get("bounds_mode") or "") != "inherit_parent":
        return None

    entities = projection.get("entities") or {}
    owner = entities.get(owner_location_id) or {}
    parent_location_id = (owner.get("state") or {}).get("parent_location_id")

    all_spaces = repository.spaces(project_id)
    candidate_parent_space_ids: list[str] = []
    if parent_location_id:
        parent_binding = repository.location_space(project_id, str(parent_location_id))
        if parent_binding:
            candidate_parent_space_ids.append(str(parent_binding["navigation_space_id"]))
        candidate_parent_space_ids.extend(
            item.id for item in all_spaces
            if item.owner_location_id == parent_location_id and item.id not in candidate_parent_space_ids
        )

    foreign_features = [
        item for item in repository.features(project_id)
        if item.navigation_space_id != space.id
    ]
    owner_surfaces = [
        item for item in foreign_features
        if item.feature_kind == "surface" and item.semantic_location_id == owner_location_id
    ]
    if candidate_parent_space_ids:
        preferred = [
            item for item in owner_surfaces
            if item.navigation_space_id in candidate_parent_space_ids
        ]
        if preferred:
            owner_surfaces = preferred
    if not owner_surfaces:
        return None

    source_space_id = owner_surfaces[0].navigation_space_id
    owner_surfaces = [
        item for item in owner_surfaces
        if item.navigation_space_id == source_space_id
    ]
    owner_shape = unary_union([
        shape(item.geometry.model_dump(mode="json")) for item in owner_surfaces
    ])
    if owner_shape.is_empty or not owner_shape.is_valid:
        raise SpatialV3ContextError(
            f"Location {owner_location_id} has invalid parent-space footprint geometry"
        )

    source_bounds = tuple(float(value) for value in owner_shape.bounds)
    target_bounds = _target_box(space)
    projected_boundary = _transform_geometry(owner_shape, source_bounds, target_bounds)

    context_features: list[dict[str, Any]] = []
    for feature in repository.features(project_id, source_space_id):
        if feature.id in {item.id for item in owner_surfaces}:
            continue
        source_geometry = shape(feature.geometry.model_dump(mode="json"))

        if feature.feature_kind in {"surface", "corridor", "barrier"}:
            clipped = source_geometry.intersection(owner_shape)
        elif feature.feature_kind in {"spot", "connector"}:
            clipped = source_geometry if owner_shape.covers(source_geometry) else GeometryCollection()
        else:
            continue

        clipped = _compatible_geometry(feature, clipped)
        if clipped is None:
            continue
        projected = _transform_geometry(clipped, source_bounds, target_bounds)
        projected = _compatible_geometry(feature, projected)
        if projected is None:
            continue

        payload = feature.model_dump(mode="json")
        payload["id"] = f"inherited:{source_space_id}:{feature.id}"
        payload["navigation_space_id"] = space.id
        payload["geometry"] = mapping(projected)
        payload["metadata"] = {
            **payload.get("metadata", {}),
            "inherited_parent_context": True,
            "source_space_id": source_space_id,
            "source_feature_id": feature.id,
        }
        if feature.feature_kind == "corridor" and isinstance(feature.properties, CorridorProperties):
            source_width = max(source_bounds[2] - source_bounds[0], 1e-9)
            target_width = max(target_bounds[2] - target_bounds[0], 1e-9)
            scale = target_width / source_width
            payload["properties"] = {
                **payload["properties"],
                "width": max(0.01, float(feature.properties.width) * scale),
            }
        context_features.append(payload)

    return {
        "bounds_mode": "inherit_parent",
        "source_space_id": source_space_id,
        "source_location_id": owner_location_id,
        "source_feature_ids": [item.id for item in owner_surfaces],
        "boundary": mapping(projected_boundary),
        "features": context_features,
    }
