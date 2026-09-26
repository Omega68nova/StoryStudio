from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.spatial_v3 import (
    BarrierProperties,
    CorridorProperties,
    MapFeature,
    MultiPolygonGeometry,
    NavigationMode,
    NavigationSpace,
    PolygonGeometry,
    SurfaceProperties,
    TraversalOption,
    TraversalPolicy,
)


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
