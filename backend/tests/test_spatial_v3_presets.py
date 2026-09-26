from __future__ import annotations

from app.database import Database, utc_now
from app.data import DataProvider
from app.domain.spatial_v3 import NavigationSpace
from app.services.spatial_v3_presets import build_spatial_v3_preset, public_spatial_v3_presets


def setup_space(tmp_path):
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("presets")
    db.execute(
        "INSERT INTO world_entities(id,project_id,kind,canonical_name,aliases_json,tags_json,created_at) VALUES(?,?,?,?,?,?,?)",
        ("world", project["id"], "location", "world", "[]", "[]", utc_now()),
    )
    data.spatial_v3.save_space(NavigationSpace(
        id="world-space",
        project_id=project["id"],
        owner_location_id="world",
        navigation_mode="free",
    ))
    return db, data, project["id"]


def test_catalog_contains_expected_v3_presets() -> None:
    keys = {item["key"] for item in public_spatial_v3_presets()}
    assert {"open_region", "road", "river", "city", "walled_city", "building", "routed_room", "portal"} <= keys


def test_walled_city_generates_surface_roads_and_segmented_barrier(tmp_path) -> None:
    _db, data, project_id = setup_space(tmp_path)
    rows = build_spatial_v3_preset(
        data.spatial_v3, project_id, "walled_city",
        {"navigation_space_id": "world-space", "semantic_location_id": "city", "width": 60, "height": 50},
    )
    features = [row["arguments"] for row in rows if row["tool"] == "upsertSpatialV3Feature"]
    assert any(item["feature_kind"] == "surface" for item in features)
    assert len([item for item in features if item["feature_kind"] == "corridor"]) == 2
    wall = next(item for item in features if item["feature_kind"] == "barrier")
    assert wall["geometry"]["type"] == "MultiLineString"
    assert len(wall["geometry"]["coordinates"]) == 8


def test_building_generates_child_routed_space_binding_floor_and_door(tmp_path) -> None:
    _db, data, project_id = setup_space(tmp_path)
    rows = build_spatial_v3_preset(
        data.spatial_v3, project_id, "building",
        {"navigation_space_id": "world-space", "semantic_location_id": "house", "name": "House", "width": 20, "height": 15},
    )
    child = next(row["arguments"] for row in rows if row["tool"] == "upsertSpatialV3Space")
    assert child["navigation_mode"] == "routed"
    binding = next(row["arguments"] for row in rows if row["tool"] == "bindSpatialV3LocationSpace")
    assert binding["location_id"] == "house"
    assert binding["navigation_space_id"] == child["id"]
    door = next(row["arguments"] for row in rows if row["tool"] == "upsertSpatialV3Feature" and row["arguments"]["feature_kind"] == "connector")
    assert door["properties"]["connector_kind"] == "door"
    assert door["properties"]["target"]["navigation_space_id"] == child["id"]


def test_portal_targets_existing_space(tmp_path) -> None:
    _db, data, project_id = setup_space(tmp_path)
    data.spatial_v3.save_space(NavigationSpace(id="other", project_id=project_id, navigation_mode="free"))
    rows = build_spatial_v3_preset(
        data.spatial_v3, project_id, "portal",
        {"navigation_space_id": "world-space", "target_space_id": "other"},
    )
    portal = next(row["arguments"] for row in rows if row["tool"] == "upsertSpatialV3Feature")
    assert portal["feature_kind"] == "connector"
    assert portal["properties"]["connector_kind"] == "portal"
    assert portal["properties"]["target"]["navigation_space_id"] == "other"
