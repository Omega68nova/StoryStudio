from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.world import LocationState, MapGeometry, RequirementExpression
from app.services.spatial import SpatialService, SpatialValidationError, validate_geometry
from app.services.world import WorldEngine


def location(location_id: str, name: str, parent: str | None = None, **state: object) -> dict:
    return {"id": location_id, "kind": "location", "name": name, "state": {"parent_location_id": parent, "enabled": True, "discovered": True, **state}}


def character(location_id: str, **state: object) -> dict:
    return {"id": "hero", "kind": "character", "name": "Hero", "tags": [], "stats": {}, "state": {"current_location_id": location_id, "abilities": [], "inventory": [], **state}}


def projection(*entities: dict, root: str | None = "world") -> dict:
    return {"entities": {item["id"]: item for item in entities}, "relations": {}, "root_location_id": root, "map_anchors": {}, "map_barriers": {}, "travel_connections": {}, "encounter_rules": {}, "travel_itineraries": {}, "branch_sequence": 4}


def test_location_topology_and_occupancy_are_independent() -> None:
    state = LocationState(topology="open", occupancy="child_required", boundary_access="connection_required", spatial_kind="area")
    assert state.topology == "open"
    assert state.occupancy == "child_required"
    assert state.boundary_access == "connection_required"


def test_two_point_area_is_valid_authoring_geometry() -> None:
    geometry = validate_geometry({
        "location_id": "world",
        "kind": "polygon",
        "points": [{"x": 2, "y": 3}, {"x": 8, "y": 9}],
    })
    assert geometry["kind"] == "polygon"
    assert len(geometry["points"]) == 2


def test_overlapping_area_priority_uses_layer_name_then_id() -> None:
    world = location("world", "World", topology="open")
    footprint = {
        "location_id": "world",
        "kind": "polygon",
        "points": [
            {"x": 0, "y": 0}, {"x": 10, "y": 0},
            {"x": 10, "y": 10}, {"x": 0, "y": 10},
        ],
    }
    low_priority = location(
        "z-id", "Zulu", "world", spatial_kind="area",
        priority_layer=4, footprint=footprint,
    )
    high_priority = location(
        "a-id", "Alpha", "world", spatial_kind="area",
        priority_layer=1, footprint=footprint,
    )
    service = SpatialService(projection(world, low_priority, high_priority))
    assert service.resolve_area_at("world", 5, 5)["id"] == "a-id"

    high_priority["state"]["priority_layer"] = 4
    assert service.resolve_area_at("world", 5, 5)["id"] == "a-id"

    high_priority["name"] = "Zulu"
    assert service.resolve_area_at("world", 5, 5)["id"] == "a-id"


def test_geometry_rejects_self_intersecting_polygon() -> None:
    with pytest.raises(SpatialValidationError):
        validate_geometry({"location_id": "world", "kind": "polygon", "points": [{"x": 0, "y": 0}, {"x": 2, "y": 2}, {"x": 0, "y": 2}, {"x": 2, "y": 0}]})


def test_has_ability_requirement_requires_a_key() -> None:
    with pytest.raises(ValidationError):
        RequirementExpression(kind="has_ability")


def test_open_map_resolves_scaled_free_travel() -> None:
    world = location("world", "World", topology="open", occupancy="child_required", minutes_per_unit=2)
    a = location("a", "A", "world", x=0, y=0)
    b = location("b", "B", "world", x=3, y=4)
    view = projection(world, a, b, character("a"))
    result = SpatialService(view).preview("hero", "b", "walk")
    assert result["available"] is True
    assert result["travel_minutes"] == 10


def test_bound_anchor_positions_follow_spots_and_area_walls() -> None:
    world = location("world", "World", topology="open")
    area = location(
        "area", "Area", "world", spatial_kind="area",
        footprint={
            "location_id": "world", "kind": "polygon",
            "points": [
                {"x": 10, "y": 10}, {"x": 30, "y": 10},
                {"x": 30, "y": 30}, {"x": 10, "y": 30},
            ],
        },
    )
    spot = location(
        "spot", "Spot", "world", spatial_kind="spot", x=60, y=70,
        footprint={"location_id": "world", "kind": "point", "points": [{"x": 60, "y": 70}]},
    )
    view = projection(world, area, spot)
    view["map_anchors"] = {
        "inside": {
            "id": "inside", "location_id": "area", "coordinate_space_id": "world",
            "binding_kind": "area", "binding_target_id": "area",
            "binding_offset_x": 3, "binding_offset_y": -2,
            "name": "Inside", "kind": "waypoint", "x": 23, "y": 18,
        },
        "wall": {
            "id": "wall", "location_id": "area", "coordinate_space_id": "world",
            "binding_kind": "area_border", "binding_target_id": "area",
            "binding_segment_index": 1, "binding_segment_t": 0.25,
            "name": "Wall", "kind": "waypoint", "x": 30, "y": 15,
        },
        "spot-anchor": {
            "id": "spot-anchor", "location_id": "spot", "coordinate_space_id": "world",
            "binding_kind": "spot", "binding_target_id": "spot",
            "name": "Spot", "kind": "waypoint", "x": 60, "y": 70,
        },
    }
    service = SpatialService(view)
    inside = service._anchor("inside")
    wall = service._anchor("wall")
    spot_anchor = service._anchor("spot-anchor")
    assert (inside.x, inside.y) == (23, 18)
    assert (wall.x, wall.y) == (30, 15)
    assert (spot_anchor.x, spot_anchor.y) == (60, 70)

    area["state"]["footprint"]["points"] = [
        {"x": 20, "y": 20}, {"x": 40, "y": 20},
        {"x": 40, "y": 40}, {"x": 20, "y": 40},
    ]
    spot["state"]["footprint"]["points"][0] = {"x": 65, "y": 75}
    moved_inside = service._anchor("inside")
    moved_wall = service._anchor("wall")
    moved_spot = service._anchor("spot-anchor")
    assert (moved_inside.x, moved_inside.y) == (33, 28)
    assert (moved_wall.x, moved_wall.y) == (40, 25)
    assert (moved_spot.x, moved_spot.y) == (65, 75)


def test_route_validation_uses_endpoint_coordinate_space() -> None:
    world = location("world", "World", topology="closed", occupancy="direct_allowed")
    area = location("area", "Area", "world", spatial_kind="area")
    spot = location("spot", "Spot", "world", spatial_kind="spot")
    view = projection(world, area, spot)
    view["map_anchors"] = {
        "free": {
            "id": "free", "location_id": "world", "coordinate_space_id": "world",
            "name": "Free", "kind": "waypoint", "x": 20, "y": 20,
        },
        "spot-anchor": {
            "id": "spot-anchor", "location_id": "spot", "coordinate_space_id": "world",
            "binding_kind": "spot", "binding_target_id": "spot",
            "name": "Spot", "kind": "waypoint", "x": 30, "y": 30,
        },
    }
    normalized = SpatialService(view).validate_connection({
        "id": "route", "kind": "route",
        "source_anchor_id": "free", "target_anchor_id": "spot-anchor",
        "travel_minutes": 1, "modes": ["walk"], "bidirectional": True,
    })
    assert normalized["source_anchor_id"] == "free"
    assert normalized["target_anchor_id"] == "spot-anchor"


def test_closed_map_needs_a_connection() -> None:
    world = location("world", "World", topology="closed", occupancy="child_required")
    a = location("a", "A", "world", x=0, y=0)
    b = location("b", "B", "world", x=1, y=0)
    result = SpatialService(projection(world, a, b, character("a"))).preview("hero", "b")
    assert result["available"] is False
    assert "No walk path" in result["blocked_reasons"][0]


def test_connection_required_child_is_not_entered_by_open_travel() -> None:
    world = location("world", "World", topology="open", occupancy="direct_allowed")
    a = location("a", "A", "world", x=0, y=0)
    b = location("b", "B", "world", x=1, y=0, boundary_access="connection_required")
    assert SpatialService(projection(world, a, b, character("a"))).preview("hero", "b")["available"] is False


def test_barrier_requirement_can_be_satisfied_by_ability() -> None:
    world = location("world", "World", topology="open", occupancy="child_required")
    a = location("a", "A", "world", x=0, y=0)
    b = location("b", "B", "world", x=4, y=0)
    view = projection(world, a, b, character("a", abilities=["flight"]))
    view["map_barriers"]["cliff"] = {
        "id": "cliff", "location_id": "world", "name": "Cliff", "blocked_modes": ["walk"],
        "requirements": {"kind": "has_ability", "ability_key": "flight"},
        "geometry": {"location_id": "world", "kind": "polyline", "points": [{"x": 2, "y": -1}, {"x": 2, "y": 1}]},
    }
    assert SpatialService(view).preview("hero", "b")["available"] is True


def test_hidden_barrier_stops_coordinate_travel_and_is_discovered() -> None:
    world = location("world", "World", topology="open", occupancy="direct_allowed", local_bounds={"location_id": "world", "kind": "polygon", "points": [{"x": -1, "y": -1}, {"x": 5, "y": -1}, {"x": 5, "y": 2}, {"x": -1, "y": 2}]})
    view = projection(world, character("world", current_x=0, current_y=0))
    view["map_barriers"]["cliff"] = {"id": "cliff", "location_id": "world", "name": "Cliff", "hidden": True, "discovered": False, "blocked_modes": ["walk"], "geometry": {"location_id": "world", "kind": "polyline", "points": [{"x": 2, "y": -1}, {"x": 2, "y": 1}]}}
    result = SpatialService(view).coordinate_itinerary("hero", 4, 0)
    assert result["itinerary"]["status"] == "paused"
    assert result["itinerary"]["interruption"]["kind"] == "barrier"
    assert result["discoveries"] == [{"kind": "barrier", "id": "cliff"}]


def test_child_required_location_is_not_a_valid_destination() -> None:
    world = location("world", "World", topology="closed", occupancy="child_required")
    city = location("city", "City", "world", occupancy="child_required")
    hero = character("world")
    result = SpatialService(projection(world, city, hero)).preview("hero", "city")
    assert result["available"] is False
    assert "child locations" in result["blocked_reasons"][0]


def test_rootless_projects_keep_spatial_travel_disabled() -> None:
    forest = location("forest", "Forest", topology="open")
    view = projection(forest, character("forest"), root=None)
    view["entities"]["other"] = location("other", "Other")
    result = SpatialService(view).preview("hero", "other")
    assert result == {"available": False, "blocked_reasons": ["Location mapping is disabled until a world root is configured"]}


def test_root_replacement_reparents_previous_root_atomically() -> None:
    old = location("old", "Old World")
    new = location("new", "Expanded World", "old")
    view = projection(old, new, root="old")
    WorldEngine.apply_event(view, "world.root_set", {"root_location_id": "new", "reparent_previous": True, "reparent_location_ids": []}, "new")
    assert view["root_location_id"] == "new"
    assert view["entities"]["new"]["state"]["parent_location_id"] is None
    assert view["entities"]["old"]["state"]["parent_location_id"] == "new"


def test_locked_door_pauses_at_source_with_minigame_metadata() -> None:
    world = location("world", "World", topology="closed", occupancy="child_required")
    outside = location("outside", "Outside", "world")
    room = location("room", "Room", "world")
    view = projection(world, outside, room, character("outside"))
    view["map_anchors"] = {
        "out": {"id": "out", "location_id": "outside", "name": "Outside door", "kind": "entrance"},
        "in": {"id": "in", "location_id": "room", "name": "Inside door", "kind": "exit"},
    }
    view["travel_connections"]["door"] = {"id": "door", "kind": "door", "source_anchor_id": "out", "target_anchor_id": "in", "travel_minutes": 1, "modes": ["walk"], "lock": {"locked": True, "minigame_key": "lockpicking", "difficulty": 4, "success_behavior": "one_pass"}}
    result = SpatialService(view).itinerary("hero", "room")
    assert result["reached_location_id"] == "outside"
    assert result["itinerary"]["status"] == "paused"
    assert result["itinerary"]["interruption"] == {"kind": "lock", "connection_id": "door", "source_location_id": "outside", "minigame_key": "lockpicking", "difficulty": 4, "success_behavior": "one_pass"}


def test_encounter_roll_and_selection_are_retry_stable() -> None:
    world = location("world", "World", topology="closed", occupancy="child_required")
    outside = location("outside", "Outside", "world")
    room = location("room", "Room", "world")
    ambush = location("ambush", "Ambush", "world", random_encounter=True, discovered=False)
    view = projection(world, outside, room, ambush, character("outside"))
    view["map_anchors"] = {"a": {"id": "a", "location_id": "outside", "name": "A"}, "b": {"id": "b", "location_id": "room", "name": "B"}}
    view["travel_connections"]["road"] = {"id": "road", "kind": "route", "source_anchor_id": "a", "target_anchor_id": "b", "travel_minutes": 5, "modes": ["walk"]}
    view["encounter_rules"]["rule"] = {"id": "rule", "connection_id": "road", "probability": 1, "candidates": [{"location_id": "ambush", "weight": 1}]}
    first = SpatialService(view).itinerary("hero", "room")
    second = SpatialService(view).itinerary("hero", "room")
    assert first["itinerary"]["interruption"] == second["itinerary"]["interruption"]
    assert first["reached_location_id"] == "ambush"
