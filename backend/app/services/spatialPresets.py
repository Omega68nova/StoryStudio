from __future__ import annotations

from typing import Any


SPATIAL_PRESETS: dict[str, dict[str, Any]] = {
    "house": {"object": "location", "state": {"topology": "closed", "occupancy": "child_required", "boundary_access": "connection_required", "spatial_kind": "area", "exposure": "indoor"}},
    "locked_house": {"object": "location", "state": {"topology": "closed", "occupancy": "child_required", "boundary_access": "connection_required", "spatial_kind": "area", "exposure": "indoor"}, "suggested_connection": {"kind": "door", "lock": {"locked": True, "minigame_key": "lockpicking", "difficulty": 1, "success_behavior": "persistent"}}},
    "open_district": {"object": "location", "state": {"topology": "open", "occupancy": "direct_allowed", "boundary_access": "free", "spatial_kind": "area", "exposure": "outdoor"}},
    "routed_map": {"object": "location", "state": {"topology": "closed", "occupancy": "direct_allowed", "boundary_access": "free", "spatial_kind": "area", "exposure": "outdoor"}},
    "forest": {"object": "location", "state": {"topology": "open", "occupancy": "direct_allowed", "boundary_access": "free", "spatial_kind": "area", "exposure": "outdoor", "minutes_per_unit": 1.0}},
    "obstacle": {"object": "barrier", "defaults": {"blocked_modes": ["walk"], "hidden": False, "discovered": True}},
    "door": {"object": "connection", "defaults": {"kind": "door", "travel_minutes": 0, "modes": ["walk"], "bidirectional": True}},
    "portal": {"object": "connection", "defaults": {"kind": "portal", "travel_minutes": 0, "modes": ["walk"], "bidirectional": True}},
}


def public_spatial_presets() -> list[dict[str, Any]]:
    return [{"key": key, **value} for key, value in SPATIAL_PRESETS.items()]
