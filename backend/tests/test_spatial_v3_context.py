from app.domain.spatial_v3 import (
    CorridorProperties,
    LocationNavigationSpace,
    MapFeature,
    NavigationSpace,
    SurfaceProperties,
)
from app.services.spatial_v3 import SpatialV3Service
from app.services.spatial_v3_context import inherited_parent_context


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
