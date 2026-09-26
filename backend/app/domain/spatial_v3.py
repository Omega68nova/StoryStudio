from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpatialV3Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True, validate_default=True)


class NavigationMode(StrEnum):
    FREE = "free"
    ROUTED = "routed"


class FeatureKind(StrEnum):
    SURFACE = "surface"
    CORRIDOR = "corridor"
    BARRIER = "barrier"
    CONNECTOR = "connector"
    SPOT = "spot"


class RenderLayer(StrEnum):
    TOPOLOGY = "topology"
    REGIONS = "regions"
    ROADS = "roads"
    PLACES = "places"
    BARRIERS = "barriers"
    CONNECTIONS = "connections"


class ConnectorKind(StrEnum):
    GENERIC = "generic"
    DOOR = "door"
    GATE = "gate"
    STAIRS = "stairs"
    LADDER = "ladder"
    BRIDGE = "bridge"
    CLIMB = "climb"
    PORTAL = "portal"


class LabelsMode(StrEnum):
    HIDDEN = "hidden"
    IMPORTANT = "important"
    ALL = "all"


class BoundsMode(StrEnum):
    INHERIT_PARENT = "inherit_parent"
    INDEPENDENT = "independent"


class EntrancePolicy(StrEnum):
    CONNECTORS = "connectors"
    OPEN = "open"


class EncounterMode(StrEnum):
    AUGMENT = "augment"
    REPLACE = "replace"
    DISABLED = "disabled"


class EncounterTrigger(StrEnum):
    DISTANCE = "distance"
    TRANSITION = "transition"


Position: TypeAlias = tuple[float, float]


class PointGeometry(SpatialV3Model):
    type: Literal["Point"] = "Point"
    coordinates: Position


class LineStringGeometry(SpatialV3Model):
    type: Literal["LineString"] = "LineString"
    coordinates: list[Position] = Field(min_length=2)


class MultiLineStringGeometry(SpatialV3Model):
    type: Literal["MultiLineString"] = "MultiLineString"
    coordinates: list[list[Position]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lines(self) -> "MultiLineStringGeometry":
        if any(len(line) < 2 for line in self.coordinates):
            raise ValueError("Every MultiLineString part needs at least two points")
        return self


class PolygonGeometry(SpatialV3Model):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rings(self) -> "PolygonGeometry":
        for ring in self.coordinates:
            if len(ring) < 4:
                raise ValueError("Polygon rings require at least four positions including closure")
            if ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be closed")
        return self


class MultiPolygonGeometry(SpatialV3Model):
    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: list[list[list[Position]]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_polygons(self) -> "MultiPolygonGeometry":
        for polygon in self.coordinates:
            if not polygon:
                raise ValueError("MultiPolygon parts require an outer ring")
            for ring in polygon:
                if len(ring) < 4:
                    raise ValueError("Polygon rings require at least four positions including closure")
                if ring[0] != ring[-1]:
                    raise ValueError("Polygon rings must be closed")
        return self


GeoJSONGeometry: TypeAlias = Annotated[
    PointGeometry
    | LineStringGeometry
    | MultiLineStringGeometry
    | PolygonGeometry
    | MultiPolygonGeometry,
    Field(discriminator="type"),
]


class TraversalOption(SpatialV3Model):
    """One alternative way an actor may traverse/cross a feature.

    requirements is intentionally an opaque versioned rule payload until the
    shared ValueExpression/Requirements V2 slice lands. Spatial V3 must not
    freeze the legacy stat-vs-literal requirement shape.
    """

    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    requirements: dict[str, Any] | None = None
    travel_multiplier: float = Field(default=1, gt=0)
    fixed_minutes: float | None = Field(default=None, ge=0)


class TraversalPolicy(SpatialV3Model):
    default_allowed: bool = True
    travel_multiplier: float = Field(default=1, gt=0)
    options: list[TraversalOption] = Field(default_factory=list)


class NavigationSpace(SpatialV3Model):
    id: str
    project_id: str
    owner_location_id: str | None = None
    navigation_mode: NavigationMode = NavigationMode.FREE
    base_travel_multiplier: float = Field(default=1, gt=0)
    bounds: PolygonGeometry | MultiPolygonGeometry | None = None
    revision: int = Field(default=1, gt=0)


class SurfaceProperties(SpatialV3Model):
    traversal: TraversalPolicy = Field(default_factory=TraversalPolicy)
    ambience_tags: list[str] = Field(default_factory=list)
    environment_tags: list[str] = Field(default_factory=list)


class CorridorProperties(SpatialV3Model):
    width: float = Field(gt=0)
    traversal: TraversalPolicy = Field(default_factory=TraversalPolicy)
    ambience_tags: list[str] = Field(default_factory=list)


class BarrierProperties(SpatialV3Model):
    traversal: TraversalPolicy = Field(
        default_factory=lambda: TraversalPolicy(default_allowed=False)
    )


class ConnectorEndpoint(SpatialV3Model):
    navigation_space_id: str
    point: Position


class ConnectorProperties(SpatialV3Model):
    connector_kind: ConnectorKind = ConnectorKind.GENERIC
    source: ConnectorEndpoint
    target: ConnectorEndpoint
    traversal: TraversalPolicy = Field(default_factory=TraversalPolicy)
    travel_minutes: float | None = Field(default=None, ge=0)
    bidirectional: bool = True


class SpotProperties(SpatialV3Model):
    interaction_kind: str = "generic"


FeatureProperties: TypeAlias = (
    SurfaceProperties
    | CorridorProperties
    | BarrierProperties
    | ConnectorProperties
    | SpotProperties
)


class MapFeature(SpatialV3Model):
    @model_validator(mode="before")
    @classmethod
    def parse_properties_for_kind(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        kind = str(value.get("feature_kind") or "")
        raw = value.get("properties")
        if not isinstance(raw, dict):
            return value
        property_models: dict[str, type[SpatialV3Model]] = {
            "surface": SurfaceProperties,
            "corridor": CorridorProperties,
            "barrier": BarrierProperties,
            "connector": ConnectorProperties,
            "spot": SpotProperties,
        }
        model = property_models.get(kind)
        if model is None:
            return value
        parsed = dict(value)
        parsed["properties"] = model.model_validate(raw)
        return parsed

    id: str
    project_id: str
    navigation_space_id: str
    semantic_location_id: str | None = None
    feature_kind: FeatureKind
    name: str = ""
    geometry: GeoJSONGeometry
    render_layer: RenderLayer = RenderLayer.REGIONS
    render_order: float = 0
    movement_priority: float = 0
    hidden: bool = False
    discovered: bool = True
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    properties: FeatureProperties

    @model_validator(mode="after")
    def validate_feature_shape(self) -> "MapFeature":
        geometry_type = self.geometry.type
        properties = self.properties
        expected_properties: dict[str, type[SpatialV3Model]] = {
            "surface": SurfaceProperties,
            "corridor": CorridorProperties,
            "barrier": BarrierProperties,
            "connector": ConnectorProperties,
            "spot": SpotProperties,
        }
        expected = expected_properties[str(self.feature_kind)]
        if not isinstance(properties, expected):
            raise ValueError(
                f"{self.feature_kind} features require {expected.__name__}"
            )

        allowed_geometry = {
            "surface": {"Polygon", "MultiPolygon"},
            "corridor": {"LineString", "MultiLineString"},
            "barrier": {"LineString", "MultiLineString"},
            "connector": {"Point", "LineString"},
            "spot": {"Point"},
        }[str(self.feature_kind)]
        if geometry_type not in allowed_geometry:
            raise ValueError(
                f"{self.feature_kind} features do not accept {geometry_type} geometry"
            )
        return self


class LocationNavigationSpace(SpatialV3Model):
    project_id: str
    location_id: str
    navigation_space_id: str
    entrance_policy: EntrancePolicy = EntrancePolicy.CONNECTORS
    bounds_mode: BoundsMode = BoundsMode.INHERIT_PARENT


class EncounterCandidate(SpatialV3Model):
    location_id: str
    weight: float = Field(default=1, gt=0)
    requirements: dict[str, Any] | None = None


class EncounterPolicy(SpatialV3Model):
    id: str
    project_id: str
    navigation_space_id: str | None = None
    feature_id: str | None = None
    mode: EncounterMode = EncounterMode.AUGMENT
    priority: float = 0
    trigger_kind: EncounterTrigger = EncounterTrigger.DISTANCE
    rate_per_100_units: float = Field(default=0, ge=0)
    probability_per_transition: float | None = Field(default=None, ge=0, le=1)
    minimum_distance: float = Field(default=0, ge=0)
    candidates: list[EncounterCandidate] = Field(default_factory=list)
    conditions: dict[str, Any] | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_owner(self) -> "EncounterPolicy":
        if (self.navigation_space_id is None) == (self.feature_id is None):
            raise ValueError("Encounter policy must target exactly one navigation space or feature")
        if self.trigger_kind == "transition" and self.probability_per_transition is None:
            raise ValueError("Transition encounter policies require probability_per_transition")
        return self


class NavigationLayer(SpatialV3Model):
    navigation_space_id: str
    layer_key: str
    label: str
    position: int = 0
    visible: bool = True
    textured: bool = True
    editable: bool = True
    labels_mode: LabelsMode = LabelsMode.IMPORTANT