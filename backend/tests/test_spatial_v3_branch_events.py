from __future__ import annotations

import pytest

from app.database import Database
from app.data import DataProvider
from app.services.spatial_v3_projection import SpatialV3ProjectionMaterializer
from app.services.world import WorldEngine, WorldValidationError


def _commit_author(world: WorldEngine, project_id: str, raw: list[dict]) -> None:
    mutations = world.normalize_mutations(
        project_id,
        None,
        raw,
        provenance="author",
    )
    world.commit_root(
        project_id,
        mutations,
        provenance="author",
        summary="Spatial V3 test",
    )


def test_spatial_v3_is_replayed_from_world_events(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 branch events")
    world = WorldEngine(db, data_provider=data)

    _commit_author(world, project["id"], [
        {
            "tool": "createEntity",
            "arguments": {
                "entity_id": "world-location",
                "kind": "location",
                "name": "World",
                "state": {},
            },
        },
        {
            "tool": "upsertSpatialV3Space",
            "arguments": {
                "id": "world-space",
                "project_id": project["id"],
                "owner_location_id": "world-location",
                "navigation_mode": "free",
                "base_travel_multiplier": 1,
                "bounds": None,
                "revision": 1,
            },
        },
        {
            "tool": "bindSpatialV3LocationSpace",
            "arguments": {
                "project_id": project["id"],
                "location_id": "world-location",
                "navigation_space_id": "world-space",
                "entrance_policy": "open",
                "bounds_mode": "independent",
            },
        },
    ])

    projection = world.projection(project["id"], use_cache=False)
    assert projection["spatial_v3"]["spaces"]["world-space"]["owner_location_id"] == "world-location"
    assert projection["spatial_v3"]["location_space_bindings"]["world-location"]["navigation_space_id"] == "world-space"

    rows = db.fetch_all(
        "SELECT event_type FROM world_events ORDER BY created_at, ordinal"
    )
    assert "spatial_v3.space_upserted" in {row["event_type"] for row in rows}
    assert "spatial_v3.location_space_bound" in {row["event_type"] for row in rows}


def test_spatial_v3_materialized_tables_rebuild_from_projection(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 projection materialization")
    world = WorldEngine(db, data_provider=data)

    _commit_author(world, project["id"], [
        {
            "tool": "createEntity",
            "arguments": {
                "entity_id": "city",
                "kind": "location",
                "name": "City",
                "state": {},
            },
        },
        {
            "tool": "upsertSpatialV3Space",
            "arguments": {
                "id": "city-space",
                "project_id": project["id"],
                "owner_location_id": "city",
                "navigation_mode": "free",
            },
        },
        {
            "tool": "upsertSpatialV3Feature",
            "arguments": {
                "id": "city-region",
                "project_id": project["id"],
                "navigation_space_id": "city-space",
                "semantic_location_id": "city",
                "feature_kind": "surface",
                "name": "City",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
                "properties": {
                    "traversal": {
                        "default_allowed": True,
                        "travel_multiplier": 1,
                        "options": [],
                    },
                    "ambience_tags": [],
                    "environment_tags": [],
                },
            },
        },
    ])

    assert data.spatial_v3.spaces(project["id"]) == []
    projection = world.projection(project["id"], use_cache=False)
    counts = SpatialV3ProjectionMaterializer(data.spatial_v3).synchronize(
        project["id"],
        projection,
    )
    assert counts["spaces"] == 1
    assert counts["features"] == 1
    assert data.spatial_v3.space("city-space") is not None
    assert data.spatial_v3.feature("city-region") is not None


def test_removing_space_cascades_v3_projection_children(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 cascade")
    world = WorldEngine(db, data_provider=data)

    _commit_author(world, project["id"], [
        {
            "tool": "createEntity",
            "arguments": {
                "entity_id": "place",
                "kind": "location",
                "name": "Place",
                "state": {},
            },
        },
        {
            "tool": "upsertSpatialV3Space",
            "arguments": {
                "id": "space",
                "project_id": project["id"],
                "owner_location_id": "place",
            },
        },
        {
            "tool": "upsertSpatialV3Feature",
            "arguments": {
                "id": "spot",
                "project_id": project["id"],
                "navigation_space_id": "space",
                "semantic_location_id": "place",
                "feature_kind": "spot",
                "geometry": {"type": "Point", "coordinates": [1, 2]},
                "properties": {"interaction_kind": "generic"},
            },
        },
    ])
    _commit_author(world, project["id"], [
        {"tool": "removeSpatialV3Space", "arguments": {"id": "space"}},
    ])

    projection = world.projection(project["id"], use_cache=False)
    assert projection["spatial_v3"]["spaces"] == {}
    assert projection["spatial_v3"]["features"] == {}


def test_ai_cannot_author_spatial_v3_yet(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 AI guard")
    world = WorldEngine(db, data_provider=data)

    with pytest.raises(WorldValidationError, match="not exposed to AI"):
        world.normalize_mutations(
            project["id"],
            None,
            [{
                "tool": "upsertSpatialV3Space",
                "arguments": {
                    "id": "space",
                    "project_id": project["id"],
                },
            }],
            provenance="ai",
        )
