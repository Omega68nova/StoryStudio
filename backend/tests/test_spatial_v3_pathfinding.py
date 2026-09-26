from __future__ import annotations

import pytest

from app.database import Database, utc_now
from app.data import DataProvider
from app.domain.spatial_v3 import (
    BarrierProperties,
    ConnectorEndpoint,
    ConnectorProperties,
    CorridorProperties,
    MapFeature,
    NavigationSpace,
    SurfaceProperties,
    TraversalOption,
    TraversalPolicy,
)
from app.services.spatial_v3_pathfinding import SpatialV3Pathfinder


def _location(db: Database, project_id: str, location_id: str) -> None:
    db.execute(
        """
        INSERT INTO world_entities(
          id,project_id,kind,canonical_name,aliases_json,tags_json,created_at
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (location_id, project_id, "location", location_id, "[]", "[]", utc_now()),
    )


def test_free_path_routes_around_barrier(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("free barrier")
    _location(db, project["id"], "world")
    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
        navigation_mode="free",
        bounds={
            "type": "Polygon",
            "coordinates": [[(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]],
        },
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="wall",
        project_id=project["id"],
        navigation_space_id="space",
        feature_kind="barrier",
        geometry={"type": "LineString", "coordinates": [(10, 5), (10, 15)]},
        properties=BarrierProperties(),
    ))

    route = SpatialV3Pathfinder(data.spatial_v3).plan(
        project_id=project["id"],
        start_space_id="space",
        start=(2, 10),
        target_space_id="space",
        target=(18, 10),
    )
    assert route["total_distance"] > 16
    assert route["steps"]
    assert all(step["kind"] == "movement" for step in route["steps"])


def test_road_overrides_blocked_river_during_pathfinding(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("road over river")
    _location(db, project["id"], "world")
    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
        navigation_mode="free",
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="river",
        project_id=project["id"],
        navigation_space_id="space",
        feature_kind="surface",
        geometry={
            "type": "Polygon",
            "coordinates": [[(8, 0), (12, 0), (12, 20), (8, 20), (8, 0)]],
        },
        movement_priority=10,
        properties=SurfaceProperties(
            traversal=TraversalPolicy(default_allowed=False),
        ),
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="bridge-road",
        project_id=project["id"],
        navigation_space_id="space",
        feature_kind="corridor",
        geometry={"type": "LineString", "coordinates": [(0, 10), (20, 10)]},
        movement_priority=30,
        properties=CorridorProperties(
            width=2,
            traversal=TraversalPolicy(default_allowed=True, travel_multiplier=0.5),
        ),
    ))

    route = SpatialV3Pathfinder(data.spatial_v3).plan(
        project_id=project["id"],
        start_space_id="space",
        start=(1, 10),
        target_space_id="space",
        target=(19, 10),
    )
    assert route["total_distance"] == pytest.approx(18)
    assert any(step.get("movement_source_feature_id") == "bridge-road" for step in route["steps"])
    assert route["total_travel_cost"] == pytest.approx(9)


def test_routed_space_rejects_void_and_uses_authored_geometry(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("routed rooms")
    _location(db, project["id"], "building")
    data.spatial_v3.save_space(NavigationSpace(
        id="inside",
        project_id=project["id"],
        owner_location_id="building",
        navigation_mode="routed",
    ))
    for feature_id, geometry in (
        ("left-room", {"type": "Polygon", "coordinates": [[(0, 0), (5, 0), (5, 5), (0, 5), (0, 0)]]}),
        ("hall", {"type": "LineString", "coordinates": [(5, 2.5), (10, 2.5)]}),
        ("right-room", {"type": "Polygon", "coordinates": [[(10, 0), (15, 0), (15, 5), (10, 5), (10, 0)]]}),
    ):
        if geometry["type"] == "LineString":
            feature = MapFeature(
                id=feature_id,
                project_id=project["id"],
                navigation_space_id="inside",
                feature_kind="corridor",
                geometry=geometry,
                properties=CorridorProperties(width=2),
            )
        else:
            feature = MapFeature(
                id=feature_id,
                project_id=project["id"],
                navigation_space_id="inside",
                feature_kind="surface",
                geometry=geometry,
                properties=SurfaceProperties(),
            )
        data.spatial_v3.save_feature(feature)

    route = SpatialV3Pathfinder(data.spatial_v3).plan(
        project_id=project["id"],
        start_space_id="inside",
        start=(2, 2.5),
        target_space_id="inside",
        target=(13, 2.5),
    )
    assert route["total_distance"] == pytest.approx(11)
    assert any("hall" in step.get("corridor_ids", []) for step in route["steps"])


def test_connector_can_cross_navigation_spaces(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("cross-space door")
    _location(db, project["id"], "outside")
    _location(db, project["id"], "inside")
    data.spatial_v3.save_space(NavigationSpace(
        id="outside-space",
        project_id=project["id"],
        owner_location_id="outside",
        navigation_mode="free",
    ))
    data.spatial_v3.save_space(NavigationSpace(
        id="inside-space",
        project_id=project["id"],
        owner_location_id="inside",
        navigation_mode="routed",
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="room",
        project_id=project["id"],
        navigation_space_id="inside-space",
        feature_kind="surface",
        geometry={
            "type": "Polygon",
            "coordinates": [[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]],
        },
        properties=SurfaceProperties(),
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="door",
        project_id=project["id"],
        navigation_space_id="outside-space",
        feature_kind="connector",
        geometry={"type": "Point", "coordinates": (5, 5)},
        properties=ConnectorProperties(
            connector_kind="door",
            source=ConnectorEndpoint(
                navigation_space_id="outside-space",
                point=(5, 5),
            ),
            target=ConnectorEndpoint(
                navigation_space_id="inside-space",
                point=(0.5, 5),
            ),
            travel_minutes=1,
        ),
    ))

    route = SpatialV3Pathfinder(data.spatial_v3).plan(
        project_id=project["id"],
        start_space_id="outside-space",
        start=(1, 5),
        target_space_id="inside-space",
        target=(5, 5),
    )
    connectors = [step for step in route["steps"] if step["kind"] == "connector"]
    assert len(connectors) == 1
    assert connectors[0]["feature_id"] == "door"
    assert route["total_travel_cost"] == pytest.approx(9.5)


def test_conditional_connector_is_not_guessed_passable(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("conditional portal")
    _location(db, project["id"], "a")
    _location(db, project["id"], "b")
    data.spatial_v3.save_space(NavigationSpace(id="a-space", project_id=project["id"], owner_location_id="a"))
    data.spatial_v3.save_space(NavigationSpace(id="b-space", project_id=project["id"], owner_location_id="b"))
    data.spatial_v3.save_feature(MapFeature(
        id="portal",
        project_id=project["id"],
        navigation_space_id="a-space",
        feature_kind="connector",
        geometry={"type": "Point", "coordinates": (0, 0)},
        properties=ConnectorProperties(
            connector_kind="portal",
            source=ConnectorEndpoint(navigation_space_id="a-space", point=(0, 0)),
            target=ConnectorEndpoint(navigation_space_id="b-space", point=(0, 0)),
            traversal=TraversalPolicy(
                default_allowed=False,
                options=[{
                    "key": "key",
                    "label": "Use portal key",
                    "requirements": {"schema_version": 2, "kind": "has_item", "item_key": "portal_key"},
                }],
            ),
        ),
    ))

    with pytest.raises(ValueError, match="No unconditional"):
        SpatialV3Pathfinder(data.spatial_v3).plan(
            project_id=project["id"],
            start_space_id="a-space",
            start=(1, 0),
            target_space_id="b-space",
            target=(1, 0),
        )


def test_conditional_connector_uses_supplied_rules_evaluator(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("conditional connector evaluator")
    _location(db, project["id"], "a")
    _location(db, project["id"], "b")
    data.spatial_v3.save_space(NavigationSpace(id="a-space", project_id=project["id"], owner_location_id="a"))
    data.spatial_v3.save_space(NavigationSpace(id="b-space", project_id=project["id"], owner_location_id="b"))
    data.spatial_v3.save_feature(MapFeature(
        id="locked-door",
        project_id=project["id"],
        navigation_space_id="a-space",
        feature_kind="connector",
        geometry={"type": "Point", "coordinates": (0, 0)},
        properties=ConnectorProperties(
            connector_kind="door",
            source=ConnectorEndpoint(navigation_space_id="a-space", point=(0, 0)),
            target=ConnectorEndpoint(navigation_space_id="b-space", point=(0, 0)),
            traversal=TraversalPolicy(
                default_allowed=False,
                options=[TraversalOption(
                    key="strong",
                    label="Force the door",
                    requirements={
                        "schema_version": 2,
                        "kind": "compare",
                        "target": "actor",
                        "stat_key": "strength",
                        "comparison": "gte",
                        "value": 10,
                    },
                    fixed_minutes=2,
                )],
            ),
        ),
    ))

    evaluated = []
    route = SpatialV3Pathfinder(
        data.spatial_v3,
        condition_evaluator=lambda payload: evaluated.append(payload) is None or True,
    ).plan(
        project_id=project["id"],
        start_space_id="a-space",
        start=(1, 0),
        target_space_id="b-space",
        target=(1, 0),
    )
    connector = next(step for step in route["steps"] if step["kind"] == "connector")
    assert evaluated
    assert connector["conditional_option_key"] == "strong"
    assert connector["travel_cost"] == 2
