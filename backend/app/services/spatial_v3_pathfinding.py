from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any

try:
    from shapely.geometry import LineString, Point
    from shapely.geometry.base import BaseGeometry
except ImportError:  # pragma: no cover
    LineString = Point = None  # type: ignore[assignment]
    BaseGeometry = Any  # type: ignore[misc,assignment]

from app.data.spatialV3Repository import SpatialV3Repository
from app.domain.spatial_v3 import (
    BarrierProperties,
    ConnectorProperties,
    CorridorProperties,
    MapFeature,
    NavigationSpace,
    SurfaceProperties,
)
from app.services.spatial_v3 import SpatialV3Error, SpatialV3Service, _require_geometry


@dataclass(frozen=True)
class _Node:
    space_id: str
    x: float
    y: float

    @property
    def point(self) -> tuple[float, float]:
        return (self.x, self.y)


class SpatialV3Pathfinder:
    """Experimental path planner for Spatial V3.

    It plans ordinary geometric movement inside FREE/ROUTED spaces and uses
    Connector features as explicit graph edges between positions/spaces.

    Requirement payloads are still owned by Requirements V2. A traversal whose
    default is blocked and which only offers conditional options is therefore
    considered unresolved, not guessed to be passable.
    """

    def __init__(self, repository: SpatialV3Repository) -> None:
        self.repository = repository
        self.resolver = SpatialV3Service(repository)

    @staticmethod
    def _feature_policy(feature: MapFeature):
        props = feature.properties
        if isinstance(props, (SurfaceProperties, CorridorProperties, BarrierProperties, ConnectorProperties)):
            return props.traversal
        return None

    @staticmethod
    def _geometry_vertices(geometry: BaseGeometry) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        geom_type = geometry.geom_type
        if geom_type == "Point":
            return [(float(geometry.x), float(geometry.y))]
        if geom_type in {"LineString", "LinearRing"}:
            return [(float(x), float(y)) for x, y in geometry.coords]
        if geom_type == "Polygon":
            points.extend((float(x), float(y)) for x, y in geometry.exterior.coords)
            for ring in geometry.interiors:
                points.extend((float(x), float(y)) for x, y in ring.coords)
            return points
        for part in getattr(geometry, "geoms", []):
            points.extend(SpatialV3Pathfinder._geometry_vertices(part))
        return points

    @staticmethod
    def _intersection_positions(line: BaseGeometry, geometry: BaseGeometry) -> list[float]:
        intersection = line.intersection(geometry)
        if intersection.is_empty:
            return []
        result: list[float] = []
        for x, y in SpatialV3Pathfinder._geometry_vertices(intersection):
            result.append(float(line.project(Point(x, y))))
        return result

    def _space(self, project_id: str, space_id: str) -> NavigationSpace:
        space = self.repository.space(space_id)
        if not space or space.project_id != project_id:
            raise SpatialV3Error(f"Navigation space not found: {space_id}")
        return space

    def _space_features(self, project_id: str, space_id: str) -> list[MapFeature]:
        return [
            feature
            for feature in self.repository.features(project_id, space_id)
            if feature.enabled
        ]

    def _movement_geometries(
        self,
        project_id: str,
        space_id: str,
    ) -> list[tuple[MapFeature, BaseGeometry]]:
        result: list[tuple[MapFeature, BaseGeometry]] = []
        for feature in self._space_features(project_id, space_id):
            if feature.feature_kind in {"surface", "corridor"}:
                result.append((feature, self.resolver._geometry(feature)))
        return result

    def _barriers(
        self,
        project_id: str,
        space_id: str,
    ) -> list[tuple[MapFeature, BaseGeometry]]:
        result: list[tuple[MapFeature, BaseGeometry]] = []
        for feature in self._space_features(project_id, space_id):
            if feature.feature_kind == "barrier":
                result.append((feature, self.resolver._geometry(feature)))
        return result

    def _point_is_occupiable(
        self,
        project_id: str,
        space_id: str,
        point: tuple[float, float],
    ) -> tuple[bool, list[dict[str, Any]]]:
        context = self.resolver.movement_context(
            project_id=project_id,
            navigation_space_id=space_id,
            x=point[0],
            y=point[1],
        )
        movement = context["movement"]
        return bool(movement["default_allowed"]), list(movement["conditional_options"])

    def _barrier_crossing(
        self,
        *,
        project_id: str,
        space_id: str,
        line: BaseGeometry,
    ) -> tuple[bool, list[dict[str, Any]]]:
        unresolved: list[dict[str, Any]] = []
        for feature, geometry in self._barriers(project_id, space_id):
            if line.intersection(geometry).is_empty:
                continue
            policy = self._feature_policy(feature)
            if policy is None or policy.default_allowed:
                continue
            if policy.options:
                unresolved.append({
                    "feature_id": feature.id,
                    "feature_kind": "barrier",
                    "options": [item.model_dump(mode="json") for item in policy.options],
                })
            return True, unresolved
        return False, unresolved

    def _segment_breaks(
        self,
        *,
        project_id: str,
        space_id: str,
        line: BaseGeometry,
    ) -> list[float]:
        length = float(line.length)
        if length <= 1e-12:
            return [0.0]
        positions = [0.0, length]
        for _feature, geometry in self._movement_geometries(project_id, space_id):
            positions.extend(self._intersection_positions(line, geometry.boundary))
        space = self._space(project_id, space_id)
        if space.bounds is not None:
            bounds = self.resolver._geometry(MapFeature(
                id="__bounds__",
                project_id=project_id,
                navigation_space_id=space_id,
                feature_kind="surface",
                geometry=space.bounds,
                properties=SurfaceProperties(),
            ))
            positions.extend(self._intersection_positions(line, bounds.boundary))
        return sorted({
            max(0.0, min(length, round(position, 9)))
            for position in positions
        })

    def _segment_cost(
        self,
        *,
        project_id: str,
        space_id: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]] | None:
        _require_geometry()
        if start == end:
            return 0.0, [], []
        line = LineString([start, end])
        if line.is_empty or not line.is_valid:
            return None

        space = self._space(project_id, space_id)
        if space.bounds is not None:
            bounds_feature = MapFeature(
                id="__bounds__",
                project_id=project_id,
                navigation_space_id=space_id,
                feature_kind="surface",
                geometry=space.bounds,
                properties=SurfaceProperties(),
            )
            bounds_geometry = self.resolver._geometry(bounds_feature)
            if not bounds_geometry.covers(line):
                return None

        blocked, unresolved = self._barrier_crossing(
            project_id=project_id,
            space_id=space_id,
            line=line,
        )
        if blocked:
            return None

        breaks = self._segment_breaks(
            project_id=project_id,
            space_id=space_id,
            line=line,
        )
        if len(breaks) == 1:
            return 0.0, [], unresolved

        parts: list[dict[str, Any]] = []
        total_cost = 0.0
        for left, right in zip(breaks, breaks[1:]):
            if right - left <= 1e-9:
                continue
            middle = (left + right) / 2
            midpoint = line.interpolate(middle)
            context = self.resolver.movement_context(
                project_id=project_id,
                navigation_space_id=space_id,
                x=float(midpoint.x),
                y=float(midpoint.y),
            )
            movement = context["movement"]
            if not movement["default_allowed"]:
                return None
            distance = right - left
            multiplier = float(movement["travel_multiplier"])
            cost = distance * multiplier
            total_cost += cost
            p0 = line.interpolate(left)
            p1 = line.interpolate(right)
            parts.append({
                "kind": "movement",
                "navigation_space_id": space_id,
                "start": [float(p0.x), float(p0.y)],
                "end": [float(p1.x), float(p1.y)],
                "distance": distance,
                "travel_cost": cost,
                "travel_multiplier": multiplier,
                "movement_source_feature_id": movement["source_feature_id"],
                "semantic_location_ids": context["semantic_location_ids"],
                "surface_ids": [item["id"] for item in context["surfaces"]],
                "corridor_ids": [item["id"] for item in context["corridors"]],
            })
        return total_cost, parts, unresolved

    @staticmethod
    def _dedupe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        seen: set[tuple[float, float]] = set()
        result: list[tuple[float, float]] = []
        for x, y in points:
            key = (round(float(x), 7), round(float(y), 7))
            if key in seen:
                continue
            seen.add(key)
            result.append((float(x), float(y)))
        return result

    def _candidate_points(
        self,
        *,
        project_id: str,
        space_id: str,
        extra: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        points = list(extra)
        features = self._space_features(project_id, space_id)
        movement_shapes: list[BaseGeometry] = []
        for feature in features:
            if feature.feature_kind in {"surface", "corridor"}:
                geometry = self.resolver._geometry(feature)
                movement_shapes.append(geometry)
                points.extend(self._geometry_vertices(geometry))
                if feature.feature_kind == "corridor":
                    centerline = shape(feature.geometry.model_dump(mode="json"))
                    points.extend(self._geometry_vertices(centerline))

        # Finite barriers need nearby candidates so FREE maps can route around
        # their endpoints without making the barrier endpoint itself a legal
        # pass-through node.
        extent = 1.0
        all_vertices = [point for geom in movement_shapes for point in self._geometry_vertices(geom)]
        if all_vertices:
            xs = [p[0] for p in all_vertices]
            ys = [p[1] for p in all_vertices]
            extent = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        epsilon = extent * 1e-6
        for feature in features:
            if feature.feature_kind != "barrier":
                continue
            geometry = self.resolver._geometry(feature)
            for x, y in self._geometry_vertices(geometry):
                points.extend([
                    (x - epsilon, y - epsilon),
                    (x - epsilon, y + epsilon),
                    (x + epsilon, y - epsilon),
                    (x + epsilon, y + epsilon),
                ])

        space = self._space(project_id, space_id)
        if space.bounds is not None:
            bounds_feature = MapFeature(
                id="__bounds__",
                project_id=project_id,
                navigation_space_id=space_id,
                feature_kind="surface",
                geometry=space.bounds,
                properties=SurfaceProperties(),
            )
            points.extend(self._geometry_vertices(self.resolver._geometry(bounds_feature)))

        for feature in self.repository.features(project_id):
            if feature.feature_kind != "connector" or not feature.enabled:
                continue
            props = feature.properties
            if not isinstance(props, ConnectorProperties):
                continue
            if props.source.navigation_space_id == space_id:
                points.append(tuple(props.source.point))
            if props.target.navigation_space_id == space_id:
                points.append(tuple(props.target.point))
        return self._dedupe_points(points)

    def _connector_edges(
        self,
        project_id: str,
    ) -> tuple[list[tuple[_Node, _Node, float, dict[str, Any], bool]], list[dict[str, Any]]]:
        edges: list[tuple[_Node, _Node, float, dict[str, Any], bool]] = []
        unresolved: list[dict[str, Any]] = []
        for feature in self.repository.features(project_id):
            if feature.feature_kind != "connector" or not feature.enabled:
                continue
            props = feature.properties
            if not isinstance(props, ConnectorProperties):
                continue
            policy = props.traversal
            if not policy.default_allowed:
                if policy.options:
                    unresolved.append({
                        "feature_id": feature.id,
                        "feature_kind": "connector",
                        "options": [item.model_dump(mode="json") for item in policy.options],
                    })
                continue
            source = _Node(
                props.source.navigation_space_id,
                float(props.source.point[0]),
                float(props.source.point[1]),
            )
            target = _Node(
                props.target.navigation_space_id,
                float(props.target.point[0]),
                float(props.target.point[1]),
            )
            if props.travel_minutes is not None:
                cost = float(props.travel_minutes)
            elif source.space_id == target.space_id:
                cost = math.dist(source.point, target.point) * float(policy.travel_multiplier)
            else:
                # A cross-space connector without an explicit time is treated
                # as an instantaneous transition (appropriate for doors/portals).
                cost = 0.0
            payload = {
                "kind": "connector",
                "feature_id": feature.id,
                "connector_kind": str(props.connector_kind),
                "source_space_id": source.space_id,
                "target_space_id": target.space_id,
                "source": [source.x, source.y],
                "target": [target.x, target.y],
                "travel_cost": cost,
                "travel_minutes": props.travel_minutes,
            }
            edges.append((source, target, cost, payload, bool(props.bidirectional)))
        return edges, unresolved

    def plan(
        self,
        *,
        project_id: str,
        start_space_id: str,
        start: tuple[float, float],
        target_space_id: str,
        target: tuple[float, float],
    ) -> dict[str, Any]:
        _require_geometry()
        self._space(project_id, start_space_id)
        self._space(project_id, target_space_id)

        start_allowed, start_options = self._point_is_occupiable(
            project_id, start_space_id, start
        )
        if not start_allowed:
            raise SpatialV3Error(
                "Start position is not normally traversable"
                + ("; conditional traversal exists but Requirements V2 is unresolved" if start_options else "")
            )
        target_allowed, target_options = self._point_is_occupiable(
            project_id, target_space_id, target
        )
        if not target_allowed:
            raise SpatialV3Error(
                "Target position is not normally traversable"
                + ("; conditional traversal exists but Requirements V2 is unresolved" if target_options else "")
            )

        connector_edges, unresolved = self._connector_edges(project_id)
        connector_points_by_space: dict[str, list[tuple[float, float]]] = {}
        for source, destination, _cost, _payload, _bidirectional in connector_edges:
            connector_points_by_space.setdefault(source.space_id, []).append(source.point)
            connector_points_by_space.setdefault(destination.space_id, []).append(destination.point)

        spaces = {item.id: item for item in self.repository.spaces(project_id)}
        candidates: dict[str, list[tuple[float, float]]] = {}
        for space_id in spaces:
            extra = list(connector_points_by_space.get(space_id, []))
            if space_id == start_space_id:
                extra.append(start)
            if space_id == target_space_id:
                extra.append(target)
            candidates[space_id] = self._candidate_points(
                project_id=project_id,
                space_id=space_id,
                extra=extra,
            )

        adjacency: dict[_Node, list[tuple[_Node, float, list[dict[str, Any]]]]] = {}
        for space_id, points in candidates.items():
            nodes = [_Node(space_id, x, y) for x, y in points]
            for index, left in enumerate(nodes):
                for right in nodes[index + 1:]:
                    resolved = self._segment_cost(
                        project_id=project_id,
                        space_id=space_id,
                        start=left.point,
                        end=right.point,
                    )
                    if resolved is None:
                        continue
                    cost, parts, local_unresolved = resolved
                    unresolved.extend(local_unresolved)
                    adjacency.setdefault(left, []).append((right, cost, parts))
                    reverse_parts = [
                        {
                            **part,
                            "start": part["end"],
                            "end": part["start"],
                        }
                        for part in reversed(parts)
                    ]
                    adjacency.setdefault(right, []).append((left, cost, reverse_parts))

        for source, destination, cost, payload, bidirectional in connector_edges:
            adjacency.setdefault(source, []).append((destination, cost, [payload]))
            if bidirectional:
                reverse_payload = {
                    **payload,
                    "source_space_id": payload["target_space_id"],
                    "target_space_id": payload["source_space_id"],
                    "source": payload["target"],
                    "target": payload["source"],
                }
                adjacency.setdefault(destination, []).append((source, cost, [reverse_payload]))

        start_node = _Node(start_space_id, float(start[0]), float(start[1]))
        target_node = _Node(target_space_id, float(target[0]), float(target[1]))
        heap: list[tuple[float, int, _Node, list[dict[str, Any]]]] = [(0.0, 0, start_node, [])]
        best: dict[_Node, float] = {}
        serial = 0
        while heap:
            cost, _serial, node, path = heapq.heappop(heap)
            if cost > best.get(node, float("inf")):
                continue
            best[node] = cost
            if node == target_node:
                distance = sum(float(step.get("distance") or 0) for step in path)
                deduped_unresolved = {
                    (item["feature_id"], item["feature_kind"]): item
                    for item in unresolved
                }
                return {
                    "project_id": project_id,
                    "start": {
                        "navigation_space_id": start_space_id,
                        "point": [float(start[0]), float(start[1])],
                    },
                    "target": {
                        "navigation_space_id": target_space_id,
                        "point": [float(target[0]), float(target[1])],
                    },
                    "total_distance": distance,
                    "total_travel_cost": cost,
                    "steps": path,
                    "spaces_visited": list(dict.fromkeys(
                        step.get("navigation_space_id")
                        or step.get("source_space_id")
                        for step in path
                        if step.get("navigation_space_id") or step.get("source_space_id")
                    )),
                    "unresolved_conditional_traversals": list(deduped_unresolved.values()),
                }
            for neighbor, edge_cost, steps in adjacency.get(node, []):
                next_cost = cost + edge_cost
                if next_cost + 1e-9 >= best.get(neighbor, float("inf")):
                    continue
                best[neighbor] = next_cost
                serial += 1
                heapq.heappush(heap, (next_cost, serial, neighbor, [*path, *steps]))

        raise SpatialV3Error(
            "No unconditional Spatial V3 path exists between the requested positions"
        )
