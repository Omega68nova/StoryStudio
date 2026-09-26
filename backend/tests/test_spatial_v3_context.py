from app.domain.spatial_v3 import (
    BarrierProperties,
    CorridorProperties,
    LocationNavigationSpace,
    MapFeature,
    NavigationSpace,
    SurfaceProperties,
)
from app.services.spatial_v3 import SpatialV3Service
from app.services.spatial_v3_context import inherited_parent_context
from app.services.spatial_v3_nesting import SpatialV3NestingService


class FakeRepository:
    def __init__(self, spaces, features, bindings):
        self._spaces = spaces
        self._features = features
        self._bindings = bindings

    def location_space(self, project_id, location_id):
        binding = self._bindings.get(location_id)
        return binding.model_dump(mode="json") if binding else None

    def spaces(self, project_id):
        return self._spaces

    def space(self, space_id):
        return next((item for item in self._spaces if item.id == space_id), None)

    def features(self, project_id, navigation_space_id=None):
        items = self._features
        if navigation_space_id:
            items = [item for item in items if item.navigation_space_id == navigation_space_id]
        return items


def surface(feature_id, space_id, location_id, coordinates):
    return MapFeature.model_validate({
        "id": feature_id,
        "project_id": "project",
        "navigation_space_id": space_id,
        "semantic_location_id": location_id,
        "feature_kind": "surface",
        "name": feature_id,
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
        "render_layer": "regions",
        "properties": SurfaceProperties().model_dump(mode="json"),
    })


def corridor(feature_id, space_id, coordinates, width=4):
    return MapFeature.model_validate({
        "id": feature_id,
        "project_id": "project",
        "navigation_space_id": space_id,
        "feature_kind": "corridor",
        "name": feature_id,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "render_layer": "roads",
        "properties": CorridorProperties(width=width).model_dump(mode="json"),
    })


def test_inherited_context_uses_parent_footprint_as_local_boundary_and_clips_context():
    parent = NavigationSpace(
        id="parent-space",
        project_id="project",
        owner_location_id="city",
    )
    child = NavigationSpace(
        id="child-space",
        project_id="project",
        owner_location_id="district",
    )
    district = surface(
        "district-footprint",
        "parent-space",
        "district",
        [(20, 20), (80, 20), (50, 80), (20, 20)],
    )
    road = corridor(
        "main-road",
        "parent-space",
        [(0, 40), (100, 40)],
        width=6,
    )
    repository = FakeRepository(
        [parent, child],
        [district, road],
        {
            "city": LocationNavigationSpace(
                project_id="project",
                location_id="city",
                navigation_space_id="parent-space",
                bounds_mode="independent",
            ),
            "district": LocationNavigationSpace(
                project_id="project",
                location_id="district",
                navigation_space_id="child-space",
                bounds_mode="inherit_parent",
            ),
        },
    )
    projection = {
        "project_id": "project",
        "entities": {
            "district": {
                "id": "district",
                "kind": "location",
                "state": {"parent_location_id": "city"},
            }
        },
    }

    context = inherited_parent_context(
        repository,
        project_id="project",
        space=child,
        projection=projection,
    )

    assert context is not None
    assert context["source_space_id"] == "parent-space"
    assert context["source_feature_ids"] == ["district-footprint"]
    assert context["source_bounds"] == [20.0, 20.0, 80.0, 80.0]
    assert context["target_bounds"] == [0.0, 0.0, 100.0, 100.0]
    assert context["boundary"]["type"] == "Polygon"
    boundary = context["boundary"]["coordinates"][0]
    assert min(point[0] for point in boundary) == 0
    assert max(point[0] for point in boundary) == 100
    assert min(point[1] for point in boundary) == 0
    assert max(point[1] for point in boundary) == 100

    assert len(context["features"]) == 1
    projected_road = context["features"][0]
    assert projected_road["id"] == "inherited:parent-space:main-road"
    assert projected_road["metadata"]["source_feature_id"] == "main-road"
    assert projected_road["geometry"]["type"] == "LineString"
    assert projected_road["properties"]["width"] == 10


def test_independent_binding_has_no_inherited_context():
    child = NavigationSpace(
        id="child-space",
        project_id="project",
        owner_location_id="district",
    )
    repository = FakeRepository(
        [child],
        [],
        {
            "district": LocationNavigationSpace(
                project_id="project",
                location_id="district",
                navigation_space_id="child-space",
                bounds_mode="independent",
            )
        },
    )

    assert inherited_parent_context(
        repository,
        project_id="project",
        space=child,
        projection={"project_id": "project", "entities": {}},
    ) is None



def test_movement_resolver_treats_inherited_shape_as_real_bounds():
    parent = NavigationSpace(
        id="parent-space",
        project_id="project",
        owner_location_id="city",
    )
    child = NavigationSpace(
        id="child-space",
        project_id="project",
        owner_location_id="district",
    )
    district = surface(
        "district-footprint",
        "parent-space",
        "district",
        [(20, 20), (80, 20), (50, 80), (20, 20)],
    )
    repository = FakeRepository(
        [parent, child],
        [district],
        {
            "district": LocationNavigationSpace(
                project_id="project",
                location_id="district",
                navigation_space_id="child-space",
                bounds_mode="inherit_parent",
            )
        },
    )
    service = SpatialV3Service(repository)

    inside = service.movement_context(
        project_id="project",
        navigation_space_id="child-space",
        x=50,
        y=50,
    )
    outside = service.movement_context(
        project_id="project",
        navigation_space_id="child-space",
        x=0,
        y=100,
    )

    assert inside["movement"]["within_bounds"] is True
    assert inside["movement"]["default_allowed"] is True
    assert outside["movement"]["within_bounds"] is False
    assert outside["movement"]["default_allowed"] is False



def test_open_nested_space_descends_and_ascends_at_matching_coordinates():
    parent = NavigationSpace(
        id="parent-space",
        project_id="project",
        owner_location_id="city",
    )
    child = NavigationSpace(
        id="child-space",
        project_id="project",
        owner_location_id="district",
    )
    district = surface(
        "district-footprint",
        "parent-space",
        "district",
        [(20, 20), (80, 20), (80, 80), (20, 80), (20, 20)],
    )
    repository = FakeRepository(
        [parent, child],
        [district],
        {
            "district": LocationNavigationSpace(
                project_id="project",
                location_id="district",
                navigation_space_id="child-space",
                entrance_policy="open",
                bounds_mode="inherit_parent",
            )
        },
    )
    service = SpatialV3NestingService(repository)

    entered = service.resolve_step(
        project_id="project",
        space_id="parent-space",
        current=(19, 50),
        candidate=(21, 50),
    )
    assert entered["allowed"] is True
    assert entered["transition"]["kind"] == "descend"
    assert entered["space_id"] == "child-space"
    assert entered["point"][0] == pytest.approx(1.6666667)
    assert entered["point"][1] == pytest.approx(50)

    exited = service.resolve_step(
        project_id="project",
        space_id="child-space",
        current=(1, 50),
        candidate=(-2, 50),
    )
    assert exited["allowed"] is True
    assert exited["transition"]["kind"] == "ascend"
    assert exited["space_id"] == "parent-space"
    assert exited["point"][0] == pytest.approx(18.8)
    assert exited["point"][1] == pytest.approx(50)


def test_connector_only_child_does_not_auto_descend():
    parent = NavigationSpace(
        id="parent-space",
        project_id="project",
        owner_location_id="city",
    )
    child = NavigationSpace(
        id="child-space",
        project_id="project",
        owner_location_id="building",
    )
    building = surface(
        "building-footprint",
        "parent-space",
        "building",
        [(20, 20), (80, 20), (80, 80), (20, 80), (20, 20)],
    )
    repository = FakeRepository(
        [parent, child],
        [building],
        {
            "building": LocationNavigationSpace(
                project_id="project",
                location_id="building",
                navigation_space_id="child-space",
                entrance_policy="connectors",
                bounds_mode="inherit_parent",
            )
        },
    )

    result = SpatialV3NestingService(repository).resolve_step(
        project_id="project",
        space_id="parent-space",
        current=(19, 50),
        candidate=(21, 50),
    )
    assert result["allowed"] is True
    assert result["transition"] is None
    assert result["space_id"] == "parent-space"


def test_parent_barrier_blocks_walking_out_of_open_child():
    parent = NavigationSpace(
        id="parent-space",
        project_id="project",
        owner_location_id="city",
    )
    child = NavigationSpace(
        id="child-space",
        project_id="project",
        owner_location_id="district",
    )
    district = surface(
        "district-footprint",
        "parent-space",
        "district",
        [(20, 20), (80, 20), (80, 80), (20, 80), (20, 20)],
    )
    wall = MapFeature.model_validate({
        "id": "west-wall",
        "project_id": "project",
        "navigation_space_id": "parent-space",
        "feature_kind": "barrier",
        "name": "West wall",
        "geometry": {"type": "LineString", "coordinates": [(20, 20), (20, 80)]},
        "render_layer": "barriers",
        "properties": BarrierProperties().model_dump(mode="json"),
    })
    repository = FakeRepository(
        [parent, child],
        [district, wall],
        {
            "district": LocationNavigationSpace(
                project_id="project",
                location_id="district",
                navigation_space_id="child-space",
                entrance_policy="open",
                bounds_mode="inherit_parent",
            )
        },
    )

    result = SpatialV3NestingService(repository).resolve_step(
        project_id="project",
        space_id="child-space",
        current=(1, 50),
        candidate=(-2, 50),
    )
    assert result["allowed"] is False
    assert result["reason"] == "parent_blocked"
