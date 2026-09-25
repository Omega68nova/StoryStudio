from __future__ import annotations

from app.database import Database, utc_now
from app.services.spatial_repository import SpatialRepository


def _location(location_id: str, name: str, parent_id: str | None, x: float, y: float, *, area: bool = False, priority_layer: float = 0):
    state = {
        "parent_location_id": parent_id,
        "topology": "closed",
        "occupancy": "direct_allowed",
        "boundary_access": "free",
        "spatial_kind": "area" if area else "spot",
        "priority_layer": priority_layer,
        "exposure": "outdoor",
        "x": x,
        "y": y,
        "enabled": True,
        "hidden": False,
        "discovered": True,
        "minutes_per_unit": 1,
        "encounter_rate": 0,
    }
    if area:
        state["footprint"] = {
            "location_id": parent_id or location_id,
            "kind": "polygon",
            "points": [
                {"x": x - 5, "y": y - 5},
                {"x": x + 5, "y": y - 5},
                {"x": x + 5, "y": y + 5},
                {"x": x - 5, "y": y + 5},
            ],
        }
    return {"id": location_id, "kind": "location", "name": name, "aliases": [], "tags": [], "state": state}


def _setup(tmp_path):
    db = Database(tmp_path)
    db.initialize()
    project = db.create_project("Spatial persistence")
    now = utc_now()
    for location_id, name in (("root", "World"), ("a", "A"), ("b", "B")):
        db.execute(
            "INSERT INTO world_entities(id,project_id,kind,canonical_name,aliases_json,tags_json,created_at) "
            "VALUES(?,?, 'location', ?, '[]', '[]', ?)",
            (location_id, project["id"], name, now),
        )
    return db, project["id"]


def test_spatial_repository_materializes_locations_geometry_and_legacy_routes(tmp_path):
    db, project_id = _setup(tmp_path)
    repository = SpatialRepository(db)
    projection = {
        "project_id": project_id,
        "head_node_id": None,
        "root_location_id": "root",
        "entities": {
            "root": _location("root", "World", None, 50, 50, area=True),
            "a": _location("a", "A", "root", 25, 35, priority_layer=2.5),
            "b": _location("b", "B", "root", 70, 60),
        },
        "relations": {
            "legacy-route": {
                "id": "legacy-route",
                "relation": "route",
                "source_id": "a",
                "target_id": "b",
                "travel_minutes": 12,
                "bidirectional": False,
            },
        },
        "map_anchors": {},
        "map_barriers": {},
        "travel_connections": {},
        "encounter_rules": {},
        "travel_itineraries": {},
        "transactions": [],
    }

    state = repository.synchronize(project_id, projection, force=True)
    assert state["root_location_id"] == "root"
    assert repository.counts(project_id) == {
        "locations": 3,
        "anchors": 2,
        "barriers": 0,
        "connections": 1,
        "encounters": 0,
        "itineraries": 0,
    }

    local = repository.local_map(project_id, "root", administrative=True, include_geometry=True)
    assert local["enabled"] is True
    assert {item["id"] for item in local["locations"]} == {"a", "b"}
    assert len(local["anchors"]) == 2
    assert all(item["coordinate_space_id"] == "root" for item in local["anchors"])
    assert local["connections"][0]["id"] == "legacy-route"
    assert local["connections"][0]["travel_minutes"] == 12
    assert local["connections"][0]["bidirectional"] is False

    location_a = next(item for item in local["locations"] if item["id"] == "a")
    assert location_a["priority_layer"] == 2.5
    assert location_a["footprint"]["kind"] == "point"
    assert location_a["footprint"]["points"] == [{"x": 25.0, "y": 35.0}]


def test_spatial_repository_materializes_endpoint_bindings(tmp_path):
    db, project_id = _setup(tmp_path)
    repository = SpatialRepository(db)
    projection = {
        "project_id": project_id,
        "head_node_id": None,
        "root_location_id": "root",
        "entities": {
            "root": _location("root", "World", None, 50, 50, area=True),
            "a": _location("a", "A", "root", 25, 35, area=True),
            "b": _location("b", "B", "root", 70, 60),
        },
        "relations": {},
        "map_anchors": {
            "bound": {
                "id": "bound", "location_id": "a", "coordinate_space_id": "root",
                "binding_kind": "area_border", "binding_target_id": "a",
                "binding_segment_index": 0, "binding_segment_t": 0.5,
                "name": "A border", "kind": "waypoint", "x": 25, "y": 30,
                "discovered": True, "enabled": True,
            },
            "inside": {
                "id": "inside", "location_id": "a", "coordinate_space_id": "root",
                "binding_kind": "area", "binding_target_id": "a",
                "binding_offset_x": 2, "binding_offset_y": -1,
                "name": "A interior", "kind": "waypoint", "x": 27, "y": 34,
                "discovered": True, "enabled": True,
            },
            "spot": {
                "id": "spot", "location_id": "b", "coordinate_space_id": "root",
                "binding_kind": "spot", "binding_target_id": "b",
                "name": "B spot", "kind": "waypoint", "x": 70, "y": 60,
                "discovered": True, "enabled": True,
            },
        },
        "map_barriers": {},
        "travel_connections": {},
        "encounter_rules": {},
        "travel_itineraries": {},
        "transactions": [],
    }
    repository.synchronize(project_id, projection, force=True)
    local = repository.local_map(project_id, "root", administrative=True, include_geometry=True)
    anchor = next(item for item in local["anchors"] if item["id"] == "bound")
    assert anchor["binding_kind"] == "area_border"
    assert anchor["binding_target_id"] == "a"
    assert anchor["binding_segment_index"] == 0
    assert anchor["binding_segment_t"] == 0.5
    assert (anchor["x"], anchor["y"]) == (25.0, 30.0)

    inside = next(item for item in local["anchors"] if item["id"] == "inside")
    assert (inside["x"], inside["y"]) == (27.0, 34.0)
    spot = next(item for item in local["anchors"] if item["id"] == "spot")
    assert (spot["x"], spot["y"]) == (70.0, 60.0)

    projection["entities"]["a"] = _location("a", "A", "root", 40, 50, area=True)
    projection["entities"]["b"] = _location("b", "B", "root", 80, 75)
    repository.synchronize(project_id, projection, force=True)
    moved = repository.local_map(project_id, "root", administrative=True, include_geometry=True)
    moved_border = next(item for item in moved["anchors"] if item["id"] == "bound")
    moved_inside = next(item for item in moved["anchors"] if item["id"] == "inside")
    moved_spot = next(item for item in moved["anchors"] if item["id"] == "spot")
    assert (moved_border["x"], moved_border["y"]) == (40.0, 45.0)
    assert (moved_inside["x"], moved_inside["y"]) == (42.0, 49.0)
    assert (moved_spot["x"], moved_spot["y"]) == (80.0, 75.0)


def test_spatial_repository_replaces_active_branch_atomically(tmp_path):
    db, project_id = _setup(tmp_path)
    repository = SpatialRepository(db)
    base = {
        "project_id": project_id,
        "head_node_id": None,
        "root_location_id": "root",
        "entities": {
            "root": _location("root", "World", None, 50, 50, area=True),
            "a": _location("a", "A", "root", 20, 20),
            "b": _location("b", "B", "root", 80, 80),
        },
        "relations": {},
        "map_anchors": {},
        "map_barriers": {},
        "travel_connections": {},
        "encounter_rules": {},
        "travel_itineraries": {},
        "transactions": [],
    }
    first = repository.synchronize(project_id, base, force=True)
    changed = dict(base)
    changed["entities"] = dict(base["entities"])
    changed["entities"]["a"] = _location("a", "A", "root", 42, 43)
    second = repository.synchronize(project_id, changed, force=True)

    assert second["revision"] == first["revision"] + 1
    row = db.fetch_one("SELECT x,y FROM spatial_locations WHERE location_id='a'")
    assert row == {"x": 42.0, "y": 43.0}
    vertices = db.fetch_all(
        "SELECT x,y FROM spatial_location_vertices WHERE location_id='a' AND geometry_role='footprint' ORDER BY position"
    )
    assert vertices == [{"x": 42.0, "y": 43.0}]


def test_spatial_repository_hides_geometry_from_non_admin_map_reads(tmp_path):
    db, project_id = _setup(tmp_path)
    repository = SpatialRepository(db)
    projection = {
        "project_id": project_id,
        "head_node_id": None,
        "root_location_id": "root",
        "entities": {
            "root": _location("root", "World", None, 50, 50, area=True),
            "a": _location("a", "A", "root", 20, 20),
            "b": _location("b", "B", "root", 80, 80),
        },
        "relations": {},
        "map_anchors": {},
        "map_barriers": {},
        "travel_connections": {},
        "encounter_rules": {},
        "travel_itineraries": {},
        "transactions": [],
    }
    repository.synchronize(project_id, projection, force=True)

    public = repository.local_map(project_id, "root", administrative=False, include_geometry=False)
    assert "x" not in public["locations"][0]
    assert "footprint" not in public["locations"][0]



def test_cross_layer_portal_is_visible_from_its_source_coordinate_space(tmp_path):
    db, project_id = _setup(tmp_path)
    repository = SpatialRepository(db)
    root = _location("root", "World", None, 50, 50, area=True)
    a = _location("a", "A", "root", 20, 20, area=True)
    b = _location("b", "B", "root", 80, 80, area=True)
    projection = {
        "project_id": project_id,
        "head_node_id": None,
        "root_location_id": "root",
        "entities": {"root": root, "a": a, "b": b},
        "relations": {},
        "map_anchors": {
            "portal-source": {
                "id": "portal-source",
                "location_id": "a",
                "coordinate_space_id": "root",
                "name": "Portal in A",
                "kind": "waypoint",
                "x": 30,
                "y": 30,
                "discovered": True,
                "enabled": True,
            },
            "portal-target": {
                "id": "portal-target",
                "location_id": "b",
                "coordinate_space_id": "b",
                "name": "Portal destination",
                "kind": "waypoint",
                "x": 50,
                "y": 50,
                "discovered": True,
                "enabled": True,
            },
        },
        "map_barriers": {},
        "travel_connections": {
            "portal": {
                "id": "portal",
                "kind": "portal",
                "source_anchor_id": "portal-source",
                "target_anchor_id": "portal-target",
                "travel_minutes": 0,
                "modes": ["walk"],
                "bidirectional": True,
                "discovered": True,
                "enabled": True,
            },
        },
        "encounter_rules": {},
        "travel_itineraries": {},
        "transactions": [],
    }

    repository.synchronize(project_id, projection, force=True)
    local = repository.local_map(project_id, "root", administrative=True, include_geometry=True)
    assert {item["id"] for item in local["anchors"]} == {"portal-source"}
    assert [item["id"] for item in local["connections"]] == ["portal"]
    assert local["connections"][0]["source_location_id"] == "a"
    assert local["connections"][0]["target_location_id"] == "b"
    assert local["connections"][0]["target_coordinate_space_id"] == "b"
