from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.database import Database, utc_now
from app.data import DataProvider
from app.domain.spatial_v3 import (
    BarrierProperties,
    CorridorProperties,
    EncounterCandidate,
    EncounterPolicy,
    MapFeature,
    MultiPolygonGeometry,
    NavigationLayer,
    NavigationMode,
    NavigationSpace,
    PolygonGeometry,
    SurfaceProperties,
    TraversalOption,
    TraversalPolicy,
)
from app.services.spatial_v3 import SpatialV3Service
from app.services.spatial_v3_migration import SpatialV3Migration


def test_polygon_supports_holes() -> None:
    geometry = PolygonGeometry(
        coordinates=[
            [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)],
            [(5, 5), (15, 5), (15, 15), (5, 15), (5, 5)],
        ]
    )
    assert len(geometry.coordinates) == 2


def test_multipolygon_supports_disconnected_regions() -> None:
    geometry = MultiPolygonGeometry(
        coordinates=[
            [[(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)]],
            [[(10, 10), (14, 10), (14, 14), (10, 14), (10, 10)]],
        ]
    )
    assert len(geometry.coordinates) == 2


def test_polygon_rings_must_be_closed() -> None:
    with pytest.raises(ValidationError, match="closed"):
        PolygonGeometry(
            coordinates=[[(0, 0), (10, 0), (10, 10), (0, 10)]]
        )


def test_corridor_is_centerline_plus_width() -> None:
    feature = MapFeature(
        id="road",
        project_id="project",
        navigation_space_id="city",
        feature_kind="corridor",
        name="Main road",
        geometry={
            "type": "LineString",
            "coordinates": [(0, 5), (20, 5), (35, 12)],
        },
        render_layer="roads",
        movement_priority=20,
        properties=CorridorProperties(
            width=4,
            traversal=TraversalPolicy(
                default_allowed=True,
                travel_multiplier=0.65,
            ),
        ),
    )
    assert feature.properties.width == 4
    assert feature.properties.traversal.travel_multiplier == 0.65


def test_surface_geometry_can_reference_semantic_location() -> None:
    feature = MapFeature(
        id="district-shape",
        project_id="project",
        navigation_space_id="city",
        semantic_location_id="market-district",
        feature_kind="surface",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                (0, 0), (10, 0), (10, 10), (0, 10), (0, 0),
            ]],
        },
        render_layer="regions",
        properties=SurfaceProperties(encounter_rate=0.15),
    )
    assert feature.semantic_location_id == "market-district"
    assert feature.properties.encounter_rate == 0.15


def test_barrier_defaults_to_blocked_crossing() -> None:
    properties = BarrierProperties()
    assert properties.traversal.default_allowed is False


def test_barrier_payload_parses_as_barrier_properties() -> None:
    feature = MapFeature.model_validate({
        "id": "wall",
        "project_id": "project",
        "navigation_space_id": "space",
        "feature_kind": "barrier",
        "geometry": {
            "type": "LineString",
            "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]],
        },
        "properties": {
            "traversal": {
                "default_allowed": False,
                "travel_multiplier": 1,
                "options": [],
            },
        },
    })
    assert isinstance(feature.properties, BarrierProperties)
    assert feature.geometry.coordinates[0] == (0.0, 0.0)
    assert feature.geometry.coordinates[-1] == (0.0, 0.0)


def test_barrier_can_offer_conditional_crossings() -> None:
    properties = BarrierProperties(
        traversal=TraversalPolicy(
            default_allowed=False,
            options=[
                TraversalOption(
                    key="fly",
                    label="Fly over",
                    requirements={
                        "schema_version": 2,
                        "kind": "has_ability",
                        "ability_key": "fly",
                    },
                    travel_multiplier=1,
                ),
                TraversalOption(
                    key="climb",
                    label="Climb wall",
                    requirements={
                        "schema_version": 2,
                        "kind": "has_item",
                        "item_key": "climbing_gear",
                    },
                    travel_multiplier=3,
                ),
            ],
        )
    )
    assert [option.key for option in properties.traversal.options] == ["fly", "climb"]


def test_routed_and_free_navigation_spaces_are_explicit() -> None:
    city = NavigationSpace(
        id="city-map",
        project_id="project",
        owner_location_id="city",
        navigation_mode=NavigationMode.FREE,
    )
    building = NavigationSpace(
        id="inn-map",
        project_id="project",
        owner_location_id="inn",
        navigation_mode=NavigationMode.ROUTED,
    )
    assert city.navigation_mode == "free"
    assert building.navigation_mode == "routed"


def test_feature_kind_rejects_wrong_geometry_family() -> None:
    with pytest.raises(ValidationError, match="do not accept"):
        MapFeature(
            id="bad-road",
            project_id="project",
            navigation_space_id="city",
            feature_kind="corridor",
            geometry={
                "type": "Polygon",
                "coordinates": [[
                    (0, 0), (10, 0), (10, 10), (0, 10), (0, 0),
                ]],
            },
            properties=CorridorProperties(width=3),
        )



def _insert_location(db: Database, project_id: str, location_id: str, name: str) -> None:
    db.execute(
        """
        INSERT INTO world_entities(
          id,project_id,kind,canonical_name,aliases_json,tags_json,created_at
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (location_id, project_id, "location", name, "[]", "[]", utc_now()),
    )


def test_navigation_layer_editor_controls_persist(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 layer controls")
    _insert_location(db, project["id"], "world", "World")
    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
    ))
    data.spatial_v3.save_layer(NavigationLayer(
        navigation_space_id="space",
        layer_key="roads",
        label="Roads",
        visible=True,
        textured=False,
        editable=False,
        labels_mode="hidden",
    ))
    layer = data.spatial_v3.layers("space")[0]
    assert layer.textured is False
    assert layer.editable is False
    assert layer.labels_mode == "hidden"


def test_v3_overlap_keeps_city_and_road_while_road_controls_movement(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 overlap")
    _insert_location(db, project["id"], "world", "World")
    _insert_location(db, project["id"], "city", "City")

    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
        navigation_mode="free",
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="city-shape",
        project_id=project["id"],
        navigation_space_id="space",
        semantic_location_id="city",
        feature_kind="surface",
        name="City",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                (0, 0), (100, 0), (100, 100), (0, 100), (0, 0),
            ]],
        },
        render_layer="regions",
        movement_priority=0,
        properties=SurfaceProperties(
            traversal=TraversalPolicy(
                default_allowed=True,
                travel_multiplier=1,
            )
        ),
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="main-road",
        project_id=project["id"],
        navigation_space_id="space",
        feature_kind="corridor",
        name="Main Road",
        geometry={
            "type": "LineString",
            "coordinates": [(0, 50), (100, 50)],
        },
        render_layer="roads",
        movement_priority=20,
        properties=CorridorProperties(
            width=10,
            traversal=TraversalPolicy(
                default_allowed=True,
                travel_multiplier=0.5,
            ),
        ),
    ))

    context = SpatialV3Service(data.spatial_v3).movement_context(
        project_id=project["id"],
        navigation_space_id="space",
        x=50,
        y=50,
    )
    assert [item["id"] for item in context["surfaces"]] == ["city-shape"]
    assert [item["id"] for item in context["corridors"]] == ["main-road"]
    assert context["semantic_location_ids"] == ["city"]
    assert context["movement"]["source_feature_id"] == "main-road"
    assert context["movement"]["travel_multiplier"] == 0.5


def test_v3_distance_encounters_compose_from_space_and_region(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 encounters")
    _insert_location(db, project["id"], "world", "World")
    _insert_location(db, project["id"], "forest", "Forest")
    _insert_location(db, project["id"], "wolf", "Wolf encounter")
    _insert_location(db, project["id"], "bandits", "Bandit encounter")

    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
        navigation_mode="free",
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="forest-shape",
        project_id=project["id"],
        navigation_space_id="space",
        semantic_location_id="forest",
        feature_kind="surface",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                (0, 0), (100, 0), (100, 100), (0, 100), (0, 0),
            ]],
        },
        properties=SurfaceProperties(),
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="world-encounters",
        project_id=project["id"],
        navigation_space_id="space",
        rate_per_100_units=2,
        candidates=[EncounterCandidate(location_id="bandits", weight=1)],
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="forest-encounters",
        project_id=project["id"],
        feature_id="forest-shape",
        priority=10,
        rate_per_100_units=8,
        candidates=[EncounterCandidate(location_id="wolf", weight=3)],
    ))

    result = SpatialV3Service(data.spatial_v3).encounter_context(
        project_id=project["id"],
        navigation_space_id="space",
        x=20,
        y=20,
        distance=10,
    )
    assert result["rate_per_100_units"] == 10
    assert result["probability"] == pytest.approx(1 - math.exp(-1), rel=1e-6)
    assert {item["location_id"] for item in result["candidates"]} == {"wolf", "bandits"}


def test_v3_replace_encounter_policy_overrides_base_pool(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("V3 encounter override")
    _insert_location(db, project["id"], "world", "World")
    _insert_location(db, project["id"], "district", "District")
    _insert_location(db, project["id"], "global-event", "Global")
    _insert_location(db, project["id"], "district-event", "District Event")

    data.spatial_v3.save_space(NavigationSpace(
        id="space",
        project_id=project["id"],
        owner_location_id="world",
    ))
    data.spatial_v3.save_feature(MapFeature(
        id="district-shape",
        project_id=project["id"],
        navigation_space_id="space",
        semantic_location_id="district",
        feature_kind="surface",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                (0, 0), (10, 0), (10, 10), (0, 10), (0, 0),
            ]],
        },
        properties=SurfaceProperties(),
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="base",
        project_id=project["id"],
        navigation_space_id="space",
        rate_per_100_units=5,
        candidates=[EncounterCandidate(location_id="global-event")],
    ))
    data.spatial_v3.save_encounter_policy(EncounterPolicy(
        id="district-only",
        project_id=project["id"],
        feature_id="district-shape",
        mode="replace",
        priority=20,
        rate_per_100_units=4,
        candidates=[EncounterCandidate(location_id="district-event")],
    ))

    result = SpatialV3Service(data.spatial_v3).encounter_context(
        project_id=project["id"],
        navigation_space_id="space",
        x=5,
        y=5,
        distance=25,
    )
    assert result["rate_per_100_units"] == 4
    assert [item["location_id"] for item in result["candidates"]] == ["district-event"]


def test_legacy_spatial_migration_preserves_transition_encounters(tmp_path) -> None:
    db = Database(tmp_path)
    db.initialize()
    data = DataProvider(db)
    project = db.create_project("Legacy migration")
    for location_id, name in (
        ("world", "World"),
        ("town", "Town"),
        ("outside", "Outside"),
        ("ambush", "Ambush"),
    ):
        _insert_location(db, project["id"], location_id, name)

    projection = {
        "root_location_id": "world",
        "entities": {
            "world": {
                "id": "world",
                "kind": "location",
                "name": "World",
                "state": {
                    "topology": "open",
                    "occupancy": "child_required",
                    "enabled": True,
                    "discovered": True,
                },
            },
            "town": {
                "id": "town",
                "kind": "location",
                "name": "Town",
                "state": {
                    "parent_location_id": "world",
                    "spatial_kind": "area",
                    "boundary_access": "free",
                    "enabled": True,
                    "discovered": True,
                    "footprint": {
                        "kind": "polygon",
                        "points": [
                            {"x": 0, "y": 0},
                            {"x": 20, "y": 0},
                            {"x": 20, "y": 20},
                            {"x": 0, "y": 20},
                        ],
                    },
                },
            },
            "outside": {
                "id": "outside",
                "kind": "location",
                "name": "Outside",
                "state": {
                    "parent_location_id": "world",
                    "spatial_kind": "spot",
                    "x": 30,
                    "y": 10,
                    "enabled": True,
                    "discovered": True,
                },
            },
            "ambush": {
                "id": "ambush",
                "kind": "location",
                "name": "Ambush",
                "state": {
                    "parent_location_id": "world",
                    "spatial_kind": "spot",
                    "x": 50,
                    "y": 10,
                    "random_encounter": True,
                    "enabled": True,
                    "discovered": False,
                },
            },
        },
        "map_anchors": {
            "a": {
                "id": "a",
                "location_id": "town",
                "coordinate_space_id": "world",
                "x": 10,
                "y": 10,
            },
            "b": {
                "id": "b",
                "location_id": "outside",
                "coordinate_space_id": "world",
                "x": 30,
                "y": 10,
            },
        },
        "map_barriers": {},
        "travel_connections": {
            "road": {
                "id": "road",
                "kind": "route",
                "source_anchor_id": "a",
                "target_anchor_id": "b",
                "travel_minutes": 5,
                "modes": ["walk"],
                "bidirectional": True,
                "enabled": True,
            },
        },
        "encounter_rules": {
            "road-roll": {
                "id": "road-roll",
                "connection_id": "road",
                "probability": 0.35,
                "candidates": [{"location_id": "ambush", "weight": 1}],
                "enabled": True,
            },
        },
    }

    migration = SpatialV3Migration(data.spatial_v3)
    result = migration.materialize(project["id"], projection)
    assert result["counts"]["spaces"] == 1
    assert any(item["kind"] == "route" for item in result["warnings"])

    connector = data.spatial_v3.feature("v3-connection:road")
    assert connector is not None
    encounter = SpatialV3Service(data.spatial_v3).transition_encounter_context(
        project_id=project["id"],
        navigation_space_id="v3-space:world",
        feature_id=connector.id,
    )
    assert encounter["probability"] == pytest.approx(0.35)
    assert encounter["candidates"][0]["location_id"] == "ambush"
