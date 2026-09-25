from __future__ import annotations

import hashlib
import heapq
import itertools
import math
import random
from typing import Any

from pydantic import ValidationError
try:
    from shapely import LineString, Point, Polygon
    from shapely.geometry.base import BaseGeometry
except ImportError:  # Map reads remain available before dependencies are refreshed.
    LineString = Point = Polygon = None  # type: ignore[assignment]
    BaseGeometry = Any  # type: ignore[misc,assignment]

from app.database import new_id
from app.domain.world import (
    Barrier,
    MapAnchor,
    MapGeometry,
    RequirementExpression,
    TravelConnection,
    TravelItinerary,
    TravelSegment,
)


class SpatialValidationError(ValueError):
    pass


def _require_geometry() -> None:
    if LineString is None or Point is None or Polygon is None:
        raise SpatialValidationError(
            "Geometry-dependent mapping requires Shapely; install the backend requirements and restart StoryStudio"
        )


def _geometry(value: MapGeometry) -> BaseGeometry:
    _require_geometry()
    points = [(float(item.x), float(item.y)) for item in value.points]
    if value.kind == "point":
        result: BaseGeometry = Point(points[0])
    elif value.kind == "polyline":
        result = LineString(points)
    else:
        # A two-point area is a supported authoring state. It has no interior
        # yet, but remains editable and participates as a border segment until
        # a third point is added.
        result = LineString(points) if len(points) == 2 else Polygon(points)
    if result.is_empty or not result.is_valid:
        raise SpatialValidationError("Geometry must be non-empty and valid; self-intersecting polygons are not supported")
    return result


def validate_geometry(value: dict[str, Any]) -> dict[str, Any]:
    try:
        model = MapGeometry.model_validate(value)
        _geometry(model)
    except (ValidationError, ValueError) as exc:
        raise SpatialValidationError(str(exc)) from exc
    return model.model_dump(mode="json")


class SpatialService:
    """Branch-projection spatial resolver. Persistence remains WorldEngine events."""

    def __init__(self, projection: dict[str, Any]) -> None:
        self.projection = projection
        self.entities = projection.get("entities", {})
        self.anchors = projection.get("map_anchors", {})
        self.barriers = projection.get("map_barriers", {})
        self.connections = projection.get("travel_connections", {})
        self.encounters = projection.get("encounter_rules", {})
        self.itineraries = projection.get("travel_itineraries", {})

    def locations(self) -> dict[str, dict[str, Any]]:
        return {
            key: value for key, value in self.entities.items()
            if value.get("kind") == "location" and not value.get("state", {}).get("archived")
        }

    @staticmethod
    def area_priority_key(item: dict[str, Any]) -> tuple[float, str, str]:
        state = item.get("state", {})
        return (
            float(state.get("priority_layer", 0) or 0),
            str(item.get("name") or ""),
            str(item.get("id") or ""),
        )

    def resolve_area_at(self, coordinate_space_id: str, x: float, y: float) -> dict[str, Any] | None:
        """Return the winning colliding area using Map V2 priority semantics."""
        _require_geometry()
        point = Point(float(x), float(y))
        candidates: list[dict[str, Any]] = []
        for item in self.locations().values():
            state = item.get("state", {})
            if state.get("parent_location_id") != coordinate_space_id or state.get("spatial_kind") != "area":
                continue
            footprint = state.get("footprint")
            if not isinstance(footprint, dict) or footprint.get("kind") != "polygon":
                continue
            try:
                shape = _geometry(MapGeometry.model_validate(footprint))
            except (ValidationError, ValueError, SpatialValidationError):
                continue
            # Degenerate two-point authoring areas have no interior.
            if shape.geom_type == "Polygon" and shape.covers(point):
                candidates.append(item)
        return min(candidates, key=self.area_priority_key) if candidates else None

    def root_id(self) -> str | None:
        explicit = self.projection.get("root_location_id")
        if explicit in self.locations():
            return str(explicit)
        roots = [
            item["id"] for item in self.locations().values()
            if not item.get("state", {}).get("parent_location_id")
        ]
        return str(roots[0]) if len(roots) == 1 else None

    def ancestors(self, location_id: str) -> list[str]:
        result, seen = [], set()
        current = self.locations().get(location_id)
        while current and current["id"] not in seen:
            seen.add(current["id"])
            result.append(str(current["id"]))
            current = self.locations().get(current.get("state", {}).get("parent_location_id"))
        return result

    def validate_hierarchy(self) -> None:
        locations, root_id = self.locations(), self.root_id()
        if not root_id:
            return
        for location in locations.values():
            if root_id not in self.ancestors(str(location["id"])):
                raise SpatialValidationError(f"Active location '{location['name']}' is outside the world root")

    def _anchor(self, anchor_id: str) -> MapAnchor:
        raw = self.anchors.get(anchor_id)
        if not raw:
            raise SpatialValidationError(f"Unknown map anchor: {anchor_id}")
        return MapAnchor.model_validate(raw)

    def validate_connection(self, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            connection = TravelConnection.model_validate(raw)
            source, target = self._anchor(str(connection.source_anchor_id)), self._anchor(str(connection.target_anchor_id))
        except (ValidationError, ValueError) as exc:
            raise SpatialValidationError(str(exc)) from exc
        source_location, target_location = str(source.location_id), str(target.location_id)
        if connection.kind == "route" and not raw.get("legacy_migration"):
            source_owner = self.locations()[source_location]
            target_owner = self.locations()[target_location]
            source_space = str(
                source.coordinate_space_id
                or source_owner.get("state", {}).get("parent_location_id")
                or source_location
            )
            target_space = str(
                target.coordinate_space_id
                or target_owner.get("state", {}).get("parent_location_id")
                or target_location
            )
            if source_space != target_space:
                raise SpatialValidationError("Routes must keep both endpoints in the same map coordinate space")
        elif connection.kind == "door":
            source_parent = self.locations()[source_location].get("state", {}).get("parent_location_id")
            target_parent = self.locations()[target_location].get("state", {}).get("parent_location_id")
            if source_parent != target_location and target_parent != source_location and source_parent != target_parent:
                raise SpatialValidationError("Doors may connect only parent/child or sibling locations")
        return connection.model_dump(mode="json")

    @staticmethod
    def _requirements_pass(raw: dict[str, Any] | None, character: dict[str, Any], projection: dict[str, Any]) -> bool:
        if not raw:
            return True
        node = RequirementExpression.model_validate(raw)
        state = character.get("state", {})
        kind = str(node.kind or "")
        if kind == "and": return all(SpatialService._requirements_pass(item.model_dump(mode="json"), character, projection) for item in node.children)
        if kind == "or": return any(SpatialService._requirements_pass(item.model_dump(mode="json"), character, projection) for item in node.children)
        if kind == "not": return not SpatialService._requirements_pass(node.child.model_dump(mode="json"), character, projection)  # type: ignore[union-attr]
        if kind == "has_ability": return str(node.ability_key) in set(state.get("abilities", []))
        if kind == "has_tag": return str(node.tag) in set(character.get("tags", []))
        if kind == "has_item": return any(str(item.get("item_id")) == str(node.item_id) and int(item.get("quantity", 0)) > 0 for item in state.get("inventory", []))
        if kind == "location": return str(state.get("current_location_id")) == str(node.location_id)
        if kind == "time": return str(projection.get("current_time_phase_id")) == str(node.time_phase_id)
        if kind == "weather": return str(projection.get("current_weather_id")) == str(node.weather_id)
        if kind == "relationship":
            return any(str(item.get("relation", "")).casefold() == str(node.relation or "").casefold() and character.get("id") in {item.get("source_id"), item.get("target_id")} for item in projection.get("relations", {}).values())
        if kind == "compare":
            current, expected = character.get("stats", {}).get(str(node.stat_key), 0), node.value
            try: left, right = float(current), float(expected)  # type: ignore[arg-type]
            except (TypeError, ValueError): return False
            return {"eq": left == right, "ne": left != right, "lt": left < right, "lte": left <= right, "gt": left > right, "gte": left >= right}.get(str(node.comparison), False)
        return not kind

    def _barrier_reason(self, location_id: str, start: tuple[float, float], end: tuple[float, float], mode: str, character: dict[str, Any]) -> tuple[str | None, str | None]:
        _require_geometry()
        line = LineString([start, end])
        for raw in self.barriers.values():
            if raw.get("location_id") != location_id or not raw.get("enabled", True) or mode not in raw.get("blocked_modes", []):
                continue
            barrier = Barrier.model_validate(raw)
            if barrier.geometry is None:
                continue
            crossing_allowed = bool(raw.get("requirements")) and self._requirements_pass(raw.get("requirements"), character, self.projection)
            if line.intersects(_geometry(barrier.geometry)) and not crossing_allowed:
                return (f"Blocked by {barrier.name}" if barrier.discovered else "An undiscovered barrier blocks the way", str(barrier.id))
        return None, None

    def _geometric_path(self, location_id: str, start: tuple[float, float], end: tuple[float, float], mode: str, character: dict[str, Any]) -> list[tuple[float, float]] | None:
        _require_geometry()
        obstacles: list[BaseGeometry] = []
        candidates = [start, end]
        for raw in self.barriers.values():
            if raw.get("location_id") != location_id or not raw.get("enabled", True) or mode not in raw.get("blocked_modes", []):
                continue
            if raw.get("requirements") and self._requirements_pass(raw["requirements"], character, self.projection):
                continue
            barrier = Barrier.model_validate(raw)
            if barrier.geometry is None:
                continue
            shape = _geometry(barrier.geometry)
            obstacles.append(shape)
            if shape.geom_type == "Polygon":
                candidates.extend((float(x), float(y)) for x, y in list(shape.exterior.coords)[:-1])
            elif shape.geom_type == "LineString":
                candidates.extend((float(x), float(y)) for x, y in shape.coords)
        bounds_raw = self.locations().get(location_id, {}).get("state", {}).get("local_bounds")
        bounds = _geometry(MapGeometry.model_validate(bounds_raw)) if bounds_raw else None

        def clear(a: tuple[float, float], b: tuple[float, float]) -> bool:
            line = LineString([a, b])
            if bounds is not None and not bounds.covers(line):
                return False
            for obstacle in obstacles:
                if obstacle.geom_type == "Polygon":
                    if line.crosses(obstacle) or line.within(obstacle) or obstacle.contains(line.interpolate(.5, normalized=True)):
                        return False
                else:
                    intersection = line.intersection(obstacle)
                    if intersection.is_empty:
                        continue
                    allowed_touch = intersection.geom_type == "Point" and any(intersection.equals(Point(point)) for point in (a, b))
                    if not allowed_touch:
                        return False
            return True

        adjacency: dict[int, list[tuple[int, float]]] = {}
        for left in range(len(candidates)):
            for right in range(left + 1, len(candidates)):
                if clear(candidates[left], candidates[right]):
                    distance = math.dist(candidates[left], candidates[right])
                    adjacency.setdefault(left, []).append((right, distance))
                    adjacency.setdefault(right, []).append((left, distance))
        heap: list[tuple[float, int, list[int]]] = [(0, 0, [0])]
        best: dict[int, float] = {}
        while heap:
            distance, node, path = heapq.heappop(heap)
            if node in best and best[node] <= distance: continue
            best[node] = distance
            if node == 1: return [candidates[index] for index in path]
            for neighbor, cost in adjacency.get(node, []):
                heapq.heappush(heap, (distance + cost, neighbor, [*path, neighbor]))
        return None

    def _discoveries_near(self, location_id: str, point: tuple[float, float], character: dict[str, Any]) -> list[dict[str, str]]:
        location = self.locations().get(location_id, {})
        radius = location.get("state", {}).get("base_visibility_units")
        if radius is None:
            return []
        _require_geometry()
        visibility = self.projection.get("spatial_visibility", {})
        radius = float(radius) * float(visibility.get("weather_multiplier", 1)) * float(visibility.get("time_multiplier", 1))
        perception_key = visibility.get("perception_stat_key")
        if perception_key:
            radius *= max(0, 1 + float(character.get("stats", {}).get(perception_key, 0)) / 100)
        origin, found = Point(point), []
        for anchor in self.anchors.values():
            if anchor.get("location_id") == location_id and not anchor.get("discovered", True) and anchor.get("x") is not None and anchor.get("y") is not None and origin.distance(Point(float(anchor["x"]), float(anchor["y"]))) <= radius:
                found.append({"kind": "anchor", "id": str(anchor["id"])})
        for barrier in self.barriers.values():
            if barrier.get("location_id") == location_id and not barrier.get("discovered", True) and barrier.get("geometry"):
                if origin.distance(_geometry(MapGeometry.model_validate(barrier["geometry"]))) <= radius:
                    found.append({"kind": "barrier", "id": str(barrier["id"])})
        for child in self.locations().values():
            state = child.get("state", {})
            if state.get("parent_location_id") != location_id or state.get("discovered", True):
                continue
            footprint = state.get("footprint")
            if footprint and origin.distance(_geometry(MapGeometry.model_validate(footprint))) <= radius:
                found.append({"kind": "location", "id": str(child["id"])})
        return found

    def _legacy_connections(self) -> list[dict[str, Any]]:
        rows = []
        for relation in self.projection.get("relations", {}).values():
            if relation.get("relation") != "route":
                continue
            if relation.get("id") in self.connections:
                continue
            rows.append({
                "id": relation["id"], "kind": "route", "source_location_id": relation["source_id"],
                "target_location_id": relation["target_id"], "travel_minutes": max(0, int(relation.get("travel_minutes", 0))),
                "modes": relation.get("modes", ["walk"]), "bidirectional": relation.get("bidirectional", True),
                "enabled": not relation.get("blocked", False), "discovered": relation.get("discovered", True),
            })
        return rows

    def _connection_edges(self, character: dict[str, Any], mode: str) -> tuple[list[dict[str, Any]], list[str]]:
        edges, blocked = self._legacy_connections(), []
        for raw in self.connections.values():
            connection = TravelConnection.model_validate(raw)
            source, target = self._anchor(str(connection.source_anchor_id)), self._anchor(str(connection.target_anchor_id))
            row = {**raw, "source_location_id": str(source.location_id), "target_location_id": str(target.location_id)}
            edges.append(row)
        available = []
        for edge in edges:
            if not edge.get("enabled", True) or mode not in edge.get("modes", ["walk"]):
                continue
            if not self._requirements_pass(edge.get("requirements"), character, self.projection):
                blocked.append(f"Requirements are not met for {edge.get('id')}")
                continue
            lock = edge.get("lock") or {}
            if lock.get("locked"):
                edge = {**edge, "locked": True}
                blocked.append(f"Connection {edge.get('id')} is locked")
            available.append(edge)
        return available, blocked

    def _free_edges(self, character: dict[str, Any], mode: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        locations, edges, discoveries = self.locations(), [], []
        by_parent: dict[str, list[dict[str, Any]]] = {}
        for location in locations.values():
            parent = location.get("state", {}).get("parent_location_id")
            if parent:
                by_parent.setdefault(str(parent), []).append(location)
        for parent_id, children in by_parent.items():
            parent = locations.get(parent_id)
            if not parent or parent.get("state", {}).get("topology", "closed") != "open":
                continue
            scale = float(parent.get("state", {}).get("minutes_per_unit", 1))
            for source in children:
                for target in children:
                    if source["id"] == target["id"] or target.get("state", {}).get("boundary_access", "free") != "free":
                        continue
                    sx, sy = source.get("state", {}).get("x"), source.get("state", {}).get("y")
                    tx, ty = target.get("state", {}).get("x"), target.get("state", {}).get("y")
                    if None in {sx, sy, tx, ty}:
                        continue
                    start, end = (float(sx), float(sy)), (float(tx), float(ty))
                    reason, barrier_id = self._barrier_reason(parent_id, start, end, mode, character)
                    if reason and barrier_id and not self.barriers[barrier_id].get("discovered", True):
                        discoveries.append({"kind": "barrier", "id": barrier_id})
                        line = LineString([start, end])
                        barrier_geometry = Barrier.model_validate(self.barriers[barrier_id]).geometry
                        if barrier_geometry is not None:
                            intersection = line.intersection(_geometry(barrier_geometry))
                            distance = max(0, line.project(intersection.centroid) - 1e-6)
                            edges.append({"id": f"blocked:{source['id']}:{target['id']}", "kind": "geometric", "source_location_id": source["id"], "target_location_id": target["id"], "travel_minutes": distance * scale, "hidden_barrier_id": barrier_id, "bidirectional": False})
                        continue
                    path = self._geometric_path(parent_id, start, end, mode, character)
                    if not path:
                        continue
                    distance = sum(math.dist(path[index-1], path[index]) for index in range(1, len(path)))
                    edges.append({"id": f"free:{source['id']}:{target['id']}", "kind": "geometric", "source_location_id": source["id"], "target_location_id": target["id"], "travel_minutes": distance * scale, "points": [{"x": x, "y": y} for x, y in path], "bidirectional": False})
            if character.get("state", {}).get("current_location_id") == parent_id:
                start = (float(character.get("state", {}).get("current_x") or 0), float(character.get("state", {}).get("current_y") or 0))
                for target in children:
                    state = target.get("state", {})
                    if state.get("boundary_access", "free") != "free" or state.get("occupancy", "direct_allowed") == "child_required" or state.get("x") is None or state.get("y") is None:
                        continue
                    end = (float(state["x"]), float(state["y"]))
                    path = self._geometric_path(parent_id, start, end, mode, character)
                    if not path:
                        continue
                    distance = sum(math.dist(path[index-1], path[index]) for index in range(1, len(path)))
                    edges.append({"id": f"enter:{parent_id}:{target['id']}", "kind": "geometric", "source_location_id": parent_id, "target_location_id": target["id"], "travel_minutes": distance * scale, "points": [{"x": x, "y": y} for x, y in path], "bidirectional": False})
            if parent.get("state", {}).get("occupancy", "direct_allowed") == "direct_allowed":
                for source in children:
                    if source.get("state", {}).get("boundary_access", "free") == "free":
                        edges.append({"id": f"exit:{source['id']}:{parent_id}", "kind": "geometric", "source_location_id": source["id"], "target_location_id": parent_id, "travel_minutes": 0, "bidirectional": False})
        return edges, discoveries

    def preview(self, character_id: str, destination_location_id: str, mode: str = "walk") -> dict[str, Any]:
        root_id = self.root_id()
        if not root_id:
            return {"available": False, "blocked_reasons": ["Location mapping is disabled until a world root is configured"]}
        character = self.entities.get(character_id)
        destination = self.locations().get(destination_location_id)
        if not character or character.get("kind") != "character": raise SpatialValidationError("Character is unavailable")
        if not destination: raise SpatialValidationError("Destination location is unavailable")
        if not destination.get("state", {}).get("enabled", True): return {"available": False, "blocked_reasons": ["Destination is disabled"]}
        if not destination.get("state", {}).get("discovered", True): return {"available": False, "blocked_reasons": ["Destination has not been discovered"]}
        if destination.get("state", {}).get("occupancy", "direct_allowed") == "child_required":
            return {"available": False, "blocked_reasons": ["Destination requires occupancy of one of its child locations"]}
        source_id = character.get("state", {}).get("current_location_id")
        if not source_id: return {"available": False, "blocked_reasons": ["Character has no current location"]}
        if source_id == destination_location_id:
            return {"available": True, "travel_minutes": 0, "location_ids": [source_id], "segments": [], "blocked_reasons": []}
        explicit, blocked = self._connection_edges(character, mode)
        free, discoveries = self._free_edges(character, mode)
        adjacency: dict[str, list[tuple[str, float, dict[str, Any]]]] = {}
        for edge in [*explicit, *free]:
            source, target, weight = str(edge["source_location_id"]), str(edge["target_location_id"]), float(edge.get("travel_minutes", 0))
            adjacency.setdefault(source, []).append((target, weight, edge))
            if edge.get("bidirectional", True): adjacency.setdefault(target, []).append((source, weight, edge))
        order = itertools.count()
        heap: list[tuple[float, int, str, list[str], list[dict[str, Any]]]] = [(0, next(order), str(source_id), [str(source_id)], [])]
        best: dict[str, float] = {}
        while heap:
            total, _, current, locations, segments = heapq.heappop(heap)
            if current in best and best[current] <= total: continue
            best[current] = total
            if current == destination_location_id:
                return {"available": True, "travel_minutes": total, "location_ids": locations, "segments": segments, "blocked_reasons": [], "discoveries": discoveries}
            for neighbor, weight, edge in adjacency.get(current, []):
                segment = {"kind": "geometric" if edge.get("kind") == "geometric" else "connection", "source_location_id": current, "target_location_id": neighbor, "minutes": weight}
                if edge.get("points"):
                    segment["points"] = edge["points"]
                if edge.get("hidden_barrier_id"):
                    segment["hidden_barrier_id"] = edge["hidden_barrier_id"]
                if edge.get("kind") != "geometric": segment["connection_id"] = edge["id"]
                if edge.get("locked"): segment["locked"] = True
                heapq.heappush(heap, (total + weight, next(order), neighbor, [*locations, neighbor], [*segments, segment]))
        return {"available": False, "blocked_reasons": blocked or [f"No {mode} path reaches the destination"]}

    def itinerary(self, character_id: str, destination_location_id: str, mode: str = "walk", minutes: float | None = None, skip_encounter_rule_id: str | None = None) -> dict[str, Any]:
        preview = self.preview(character_id, destination_location_id, mode)
        if not preview.get("available"):
            raise SpatialValidationError("; ".join(preview.get("blocked_reasons", [])))
        total = float(preview["travel_minutes"])
        allotted = total if minutes is None else max(0, min(total, float(minutes)))
        completed = allotted >= total
        interruption: dict[str, Any] | None = None
        traversable_minutes = allotted
        reached_id = str(preview["location_ids"][0])
        consumed = 0.0
        seed_text = f"{character_id}:{destination_location_id}:{self.projection.get('branch_sequence', 0)}"
        for segment in preview["segments"]:
            if consumed + float(segment["minutes"]) > allotted + 1e-9:
                break
            if segment.get("hidden_barrier_id"):
                interruption = {"kind": "barrier", "barrier_id": segment["hidden_barrier_id"], "reason": "An undiscovered barrier blocks the way"}
                traversable_minutes = consumed + float(segment["minutes"])
                completed = False
                break
            connection = self.connections.get(str(segment.get("connection_id") or ""), {})
            if segment.get("locked"):
                lock = connection.get("lock") or {}
                interruption = {"kind": "lock", "connection_id": segment.get("connection_id"), "source_location_id": segment["source_location_id"], "minigame_key": lock.get("minigame_key"), "difficulty": lock.get("difficulty", 1), "success_behavior": lock.get("success_behavior", "persistent")}
                traversable_minutes = consumed
                completed = False
                break
            encounter = next((rule for rule in self.encounters.values() if rule.get("enabled", True) and rule.get("connection_id") == segment.get("connection_id") and rule.get("id") != skip_encounter_rule_id), None)
            if not encounter and segment.get("kind") == "geometric":
                source = self.locations().get(str(segment["source_location_id"]), {})
                map_id = source.get("state", {}).get("parent_location_id")
                encounter = next((rule for rule in self.encounters.values() if rule.get("enabled", True) and rule.get("location_id") == map_id and rule.get("id") != skip_encounter_rule_id), None)
                if not encounter and map_id:
                    map_location = self.locations().get(str(map_id), {})
                    rate = float(map_location.get("state", {}).get("encounter_rate", 0))
                    candidates = [
                        {"location_id": item["id"], "weight": float(item.get("state", {}).get("encounter_weight", 1))}
                        for item in self.locations().values()
                        if item.get("state", {}).get("parent_location_id") == map_id and item.get("state", {}).get("random_encounter")
                    ]
                    if rate and candidates:
                        encounter = {"id": f"legacy-open:{map_id}", "location_id": map_id, "probability": rate, "candidates": candidates}
            if encounter:
                roll = random.Random(f"{seed_text}:{encounter['id']}").random()
                if roll < float(encounter.get("probability", 0)):
                    candidates = encounter.get("candidates") or []
                    if candidates:
                        rng = random.Random(f"{seed_text}:{encounter['id']}:candidate")
                        chosen = rng.choices(candidates, weights=[float(item.get("weight", 1)) for item in candidates], k=1)[0]
                        interruption = {"kind": "encounter", "rule_id": encounter["id"], "location_id": chosen["location_id"], "connection_id": segment.get("connection_id"), "roll": roll}
                        reached_id = str(chosen["location_id"])
                        traversable_minutes = consumed
                        completed = False
                        break
            consumed += float(segment["minutes"])
            reached_id = str(segment["target_location_id"])
        itinerary = TravelItinerary(
            id=new_id(), character_id=character_id, destination_location_id=destination_location_id,
            mode=mode, segments=[TravelSegment.model_validate(item) for item in preview["segments"]],
            current_segment=len(preview["segments"]) if completed else 0,
            remaining_minutes=max(0, total-traversable_minutes), status="completed" if completed else "paused",
            interruption=interruption or (None if completed else {"kind": "time_limit"}),
            traversal_seed=hashlib.sha256(seed_text.encode()).hexdigest()[:24],
        )
        if completed:
            reached_id = destination_location_id
        discoveries = list(preview.get("discoveries", []))
        reached = self.locations().get(reached_id, {})
        parent_id = reached.get("state", {}).get("parent_location_id")
        if parent_id and reached.get("state", {}).get("x") is not None and reached.get("state", {}).get("y") is not None:
            discoveries.extend(self._discoveries_near(str(parent_id), (float(reached["state"]["x"]), float(reached["state"]["y"])), self.entities[character_id]))
        return {"itinerary": itinerary.model_dump(mode="json"), "reached_location_id": reached_id, "elapsed_minutes": traversable_minutes, "discoveries": list({(item['kind'], item['id']): item for item in discoveries}.values())}

    def coordinate_itinerary(self, character_id: str, x: float, y: float, mode: str = "walk", minutes: float | None = None) -> dict[str, Any]:
        _require_geometry()
        if not self.root_id():
            raise SpatialValidationError("Location mapping is disabled until a world root is configured")
        character = self.entities.get(character_id)
        if not character or character.get("kind") != "character": raise SpatialValidationError("Character is unavailable")
        location_id = str(character.get("state", {}).get("current_location_id") or "")
        location = self.locations().get(location_id)
        if not location or location.get("state", {}).get("topology", "closed") != "open":
            raise SpatialValidationError("Coordinate travel requires an open current location")
        start = (float(character.get("state", {}).get("current_x") or 0), float(character.get("state", {}).get("current_y") or 0))
        end = (float(x), float(y))
        bounds = location.get("state", {}).get("local_bounds")
        if bounds and not _geometry(MapGeometry.model_validate(bounds)).covers(Point(end)):
            raise SpatialValidationError("Destination is outside the location bounds")
        reason, barrier_id = self._barrier_reason(location_id, start, end, mode, character)
        scale = float(location.get("state", {}).get("minutes_per_unit", 1))
        path = [start, end]
        if reason and barrier_id and self.barriers[barrier_id].get("discovered", True):
            resolved_path = self._geometric_path(location_id, start, end, mode, character)
            if not resolved_path:
                raise SpatialValidationError(reason)
            path, reason, barrier_id = resolved_path, None, None
        total = sum(math.dist(path[index-1], path[index]) for index in range(1, len(path))) * scale
        allotted = total if minutes is None else min(total, max(0, float(minutes)))
        barrier_interruption = None
        if reason and barrier_id:
            line = LineString([start, end])
            barrier_geometry = Barrier.model_validate(self.barriers[barrier_id]).geometry
            if barrier_geometry is None:
                raise SpatialValidationError("Barrier geometry requires map review")
            intersection = line.intersection(_geometry(barrier_geometry))
            distance_fraction = 0 if line.length == 0 else max(0, line.project(intersection.centroid) / line.length - 1e-6)
            allotted = min(allotted, total * distance_fraction)
            barrier_interruption = {"kind": "barrier", "barrier_id": barrier_id, "reason": reason}
        remaining_distance = allotted / scale
        reached = start
        for index in range(1, len(path)):
            leg = math.dist(path[index-1], path[index])
            if remaining_distance >= leg:
                reached, remaining_distance = path[index], remaining_distance - leg
                continue
            ratio = 0 if leg == 0 else remaining_distance / leg
            reached = (path[index-1][0] + (path[index][0]-path[index-1][0])*ratio, path[index-1][1] + (path[index][1]-path[index-1][1])*ratio)
            break
        reached_location_id = location_id
        if allotted >= total:
            containing = []
            for child in self.locations().values():
                state = child.get("state", {})
                footprint = state.get("footprint")
                if state.get("parent_location_id") != location_id or state.get("boundary_access", "free") != "free" or not footprint:
                    continue
                if _geometry(MapGeometry.model_validate(footprint)).covers(Point(end)):
                    containing.append(child)
            if containing:
                child = containing[-1]
                if child.get("state", {}).get("occupancy", "direct_allowed") == "child_required":
                    raise SpatialValidationError(f"{child['name']} requires occupancy of one of its child locations")
                reached_location_id = str(child["id"])
        segment = TravelSegment(kind="geometric", source_location_id=location_id, target_location_id=location_id, minutes=total, points=[{"x": px, "y": py} for px, py in path])
        itinerary = TravelItinerary(
            id=new_id(), character_id=character_id, destination_location_id=location_id,
            destination_x=x, destination_y=y, mode=mode, segments=[segment],
            current_segment=1 if allotted >= total else 0, remaining_minutes=max(0, total-allotted),
            status="completed" if allotted >= total and not barrier_interruption else "paused",
            interruption=barrier_interruption or (None if allotted >= total else {"kind": "time_limit"}),
            traversal_seed=hashlib.sha256(f"{character_id}:{location_id}:{x}:{y}:{self.projection.get('branch_sequence', 0)}".encode()).hexdigest()[:24],
        )
        discoveries = [{"kind": "barrier", "id": barrier_id}] if barrier_id else []
        discoveries.extend(self._discoveries_near(location_id, reached, character))
        return {"itinerary": itinerary.model_dump(mode="json"), "reached_location_id": reached_location_id, "x": reached[0], "y": reached[1], "elapsed_minutes": allotted, "discoveries": discoveries}

    def explore(self, character_id: str, minutes: float, mode: str = "walk", direction: str | None = None) -> dict[str, Any]:
        character = self.entities.get(character_id, {})
        source_id = character.get("state", {}).get("current_location_id")
        source = self.locations().get(source_id)
        if not source: raise SpatialValidationError("Character has no current location")
        parent_id = source.get("state", {}).get("parent_location_id")
        candidates = [item for item in self.locations().values() if item.get("state", {}).get("parent_location_id") == parent_id and item["id"] != source_id and item.get("state", {}).get("discovered", True)]
        vectors = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}
        vector = vectors.get(direction or "")
        if vector:
            sx, sy = float(source.get("state", {}).get("x", 0)), float(source.get("state", {}).get("y", 0))
            candidates = [item for item in candidates if (float(item.get("state", {}).get("x", 0))-sx)*vector[0] + (float(item.get("state", {}).get("y", 0))-sy)*vector[1] > 0]
        seed = f"{character_id}:{source_id}:{minutes}:{mode}:{direction}:{self.projection.get('branch_sequence', 0)}"
        random.Random(seed).shuffle(candidates)
        for candidate in candidates:
            preview = self.preview(character_id, str(candidate["id"]), mode)
            if preview.get("available"):
                return self.itinerary(character_id, str(candidate["id"]), mode, minutes)
        raise SpatialValidationError("No reachable exploration frontier is available")

    def local_map(self, location_id: str | None, *, administrative: bool = False, include_geometry: bool = False) -> dict[str, Any]:
        root_id = self.root_id()
        if not root_id:
            return {"enabled": False, "root_location_id": None, "blocked_reason": "missing_root", "locations": [], "anchors": [], "connections": [], "barriers": []}
        focus = self.locations().get(location_id or root_id, self.locations()[root_id])
        parent_id = focus["id"]
        def visible(item: dict[str, Any]) -> bool: return administrative or (item.get("discovered", True) and not item.get("hidden", False))
        locations = [{"id": item["id"], "name": item["name"], **{key: item.get("state", {}).get(key) for key in ("parent_location_id", "topology", "occupancy", "boundary_access", "spatial_kind", "x", "y", "hidden", "discovered")}} for item in self.locations().values() if item.get("state", {}).get("parent_location_id") == parent_id and (administrative or (item.get("state", {}).get("discovered", True) and not item.get("state", {}).get("hidden", False)))]
        ids = {item["id"] for item in locations}
        anchors = [item for item in self.anchors.values() if item.get("location_id") in {*ids, parent_id} and visible(item)]
        if not include_geometry:
            locations = [{key: value for key, value in item.items() if key not in {"x", "y", "footprint", "local_bounds"}} for item in locations]
            anchors = [{key: value for key, value in item.items() if key not in {"x", "y"}} for item in anchors]
        anchor_ids = {item["id"] for item in anchors}
        connections = [{key: item.get(key) for key in ("id", "kind", "source_anchor_id", "target_anchor_id", "travel_minutes", "modes", "bidirectional", "discovered", "lock")} for item in self.connections.values() if visible(item) and item.get("source_anchor_id") in anchor_ids and item.get("target_anchor_id") in anchor_ids]
        barriers = [({**item} if administrative and include_geometry else {key: item.get(key) for key in ("id", "name", "location_id", "discovered", "hidden", "blocked_modes", "requirements")}) for item in self.barriers.values() if item.get("location_id") == parent_id and visible(item)]
        return {"enabled": True, "root_location_id": root_id, "location_id": parent_id, "topology": self.locations()[parent_id].get("state", {}).get("topology", "closed"), "locations": locations, "anchors": anchors, "connections": connections, "barriers": barriers}
