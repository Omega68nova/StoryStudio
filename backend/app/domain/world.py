from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, NewType, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _non_blank_identifier(value: str) -> str:
    if not value.strip():
        raise ValueError("domain id must not be blank")
    return value


DomainIdValue = NewType("DomainId", str)
DomainId: TypeAlias = Annotated[
    DomainIdValue,
    AfterValidator(_non_blank_identifier),
]
Number: TypeAlias = int | float


class EntityKind(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    FACTION = "faction"
    ITEM = "item"
    LORE_SYSTEM = "lore_system"
    FACT = "fact"
    RELATIONSHIP = "relationship"
    PLOT_BEAT = "plot_beat"


class DomainKind(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    FACTION = "faction"
    ITEM = "item"
    LORE_SYSTEM = "lore_system"
    FACT = "fact"
    RELATIONSHIP = "relationship"
    PLOT_BEAT = "plot_beat"
    WEATHER = "weather"
    STAT = "stat"
    ABILITY = "ability"
    OUTFIT = "outfit"


class Exposure(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    ISOLATED = "isolated"


class LocationTopology(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class LocationOccupancy(StrEnum):
    DIRECT_ALLOWED = "direct_allowed"
    CHILD_REQUIRED = "child_required"


class BoundaryAccess(StrEnum):
    FREE = "free"
    CONNECTION_REQUIRED = "connection_required"


class SpatialKind(StrEnum):
    SPOT = "spot"
    AREA = "area"


class GeometryKind(StrEnum):
    POINT = "point"
    POLYLINE = "polyline"
    POLYGON = "polygon"


class AnchorKind(StrEnum):
    LANDMARK = "landmark"
    ENTRANCE = "entrance"
    EXIT = "exit"
    WAYPOINT = "waypoint"
    ENCOUNTER = "encounter"


class ConnectionKind(StrEnum):
    ROUTE = "route"
    DOOR = "door"
    PORTAL = "portal"


class LockSuccessBehavior(StrEnum):
    PERSISTENT = "persistent"
    ONE_PASS = "one_pass"


class ItineraryStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StatScope(StrEnum):
    CHARACTER = "character"
    RELATIONSHIP = "relationship"


class StatVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    NARRATOR = "narrator"


class AbilityTarget(StrEnum):
    SELF = "self"
    CHARACTER = "character"
    CHOICE = "choice"
    RELATIONSHIP = "relationship"
    LOCATION = "location"
    ALL = "all"
    PARTY = "party"
    ALLIES = "allies"
    ENEMIES = "enemies"
    NEARBY_ENEMIES = "nearby_enemies"
    FACTION_MEMBERS = "faction_members"
    RANDOM = "random"


class EffectOperation(StrEnum):
    ADD = "add"
    SUBTRACT = "subtract"
    SET = "set"
    MULTIPLY = "multiply"
    MOVE = "move"
    CREATE = "create"
    REMOVE = "remove"
    APPLY_STATUS = "apply_status"
    REVEAL_KNOWLEDGE = "reveal_knowledge"
    CHANGE_RELATIONSHIP = "change_relationship"
    ADVANCE_TIME = "advance_time"
    PLAY_NOISE = "play_noise"


class EffectTarget(StrEnum):
    ACTOR = "actor"
    TARGET = "target"
    PARTY = "party"
    LOCATION = "location"
    NEARBY_ENEMIES = "nearby_enemies"
    FACTION_MEMBERS = "faction_members"
    RELATIONSHIP_TARGET = "relationship_target"
    ALLIES = "allies"
    ENEMIES = "enemies"
    ALL = "all"
    RANDOM = "random"


class RequirementKind(StrEnum):
    AND = "and"
    OR = "or"
    NOT = "not"
    COMPARE = "compare"
    HAS_ITEM = "has_item"
    HAS_TAG = "has_tag"
    RELATIONSHIP = "relationship"
    LOCATION = "location"
    TIME = "time"
    WEATHER = "weather"
    HAS_ABILITY = "has_ability"


class ComparisonOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"


class DomainModel(BaseModel):
    """Base model that preserves extension data without weakening known fields."""

    model_config = ConfigDict(
        extra="allow",
        use_enum_values=True,
        validate_default=True,
    )


class DomainReference(DomainModel):
    """A resolved reference to canonical persistent identity."""

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        validate_default=True,
        frozen=True,
    )

    id: DomainId
    kind: DomainKind


class InventoryEntry(DomainModel):
    item_id: DomainId
    quantity: int


class CharacterState(DomainModel):
    description: str = ""
    pronouns: str = ""
    appearance: str = ""
    imagegen_description: str = ""
    personality: str = ""
    goals: list[str] = Field(default_factory=list)
    character_secrets: list[str] = Field(default_factory=list)
    secrets_to_character: list[str] = Field(default_factory=list)
    cast_role: str = "supporting"
    player_controlled: bool = False
    autonomy_enabled: bool = False
    intervention_frequency: str = "normal"
    current_location_id: DomainId | None = None
    current_x: Number | None = None
    current_y: Number | None = None
    wardrobe_notes: str = ""
    equipment: list[str] = Field(default_factory=list)
    inventory: list[InventoryEntry] = Field(default_factory=list)
    abilities: list[str] = Field(default_factory=list)
    faction_ids: list[DomainId] = Field(default_factory=list)
    knowledge: list[DomainId] = Field(default_factory=list)
    party_ids: list[DomainId] = Field(default_factory=list)
    known_character_ids: list[DomainId] = Field(default_factory=list)
    known_faction_ids: list[DomainId] = Field(default_factory=list)
    active_outfit_id: DomainId | None = None
    full_body_height_factor: float = Field(default=0.5, ge=0, le=1)
    bullethell_default_mode_id: str | None = None
    bullethell_forced_mode_id: str | None = None
    bullethell_skill_ids: list[str] = Field(default_factory=list)
    archived: bool = False
    visibility: str = "public"

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if not str(normalized.get("description") or "").strip():
            normalized["description"] = str(normalized.get("identity") or "")
        if not str(normalized.get("personality") or "").strip():
            normalized["personality"] = str(
                normalized.get("core_personality") or ""
            )
        if not str(normalized.get("wardrobe_notes") or "").strip():
            normalized["wardrobe_notes"] = str(
                normalized.get("wardrobe") or ""
            )
        if not normalized.get("secrets_to_character"):
            legacy_secret = normalized.get("secrets")
            if isinstance(legacy_secret, list):
                normalized["secrets_to_character"] = legacy_secret
            elif str(legacy_secret or "").strip():
                normalized["secrets_to_character"] = [str(legacy_secret)]
        normalized.pop("secrets", None)
        normalized.pop("identity", None)
        normalized.pop("core_personality", None)
        normalized.pop("wardrobe", None)
        return normalized

    @property
    def identity(self) -> str:
        """Legacy read alias; canonical field is description."""
        return self.description

    @property
    def core_personality(self) -> str:
        """Legacy read alias; canonical field is personality."""
        return self.personality

    @property
    def wardrobe(self) -> str:
        """Legacy read alias; canonical field is wardrobe_notes."""
        return self.wardrobe_notes

    @property
    def secrets(self) -> str:
        """Legacy read alias for narrator-only secret notes."""
        return "\n".join(self.secrets_to_character)

    @property
    def current_location(self) -> DomainReference | None:
        if self.current_location_id is None:
            return None
        return DomainReference(
            id=self.current_location_id,
            kind=DomainKind.LOCATION,
        )


class MapPoint(DomainModel):
    x: Number
    y: Number


class MapGeometry(DomainModel):
    id: DomainId | None = None
    location_id: DomainId
    kind: GeometryKind
    points: list[MapPoint]
    hidden: bool = False
    discovered: bool = True
    requires_map_review: bool = False

    @model_validator(mode="after")
    def validate_points(self) -> "MapGeometry":
        minimum = {"point": 1, "polyline": 2, "polygon": 3}[str(self.kind)]
        if len(self.points) < minimum:
            raise ValueError(f"{self.kind} geometry needs at least {minimum} point(s)")
        if self.kind == GeometryKind.POINT and len(self.points) != 1:
            raise ValueError("point geometry needs exactly one point")
        return self


class LocationState(DomainModel):
    description: str = ""
    imagegen_description: str = ""
    image_tags: list[str] = Field(default_factory=list)
    parent_location_id: DomainId | None = None
    exposure: Exposure = Exposure.OUTDOOR
    x: Number | None = None
    y: Number | None = None
    topology: LocationTopology = LocationTopology.CLOSED
    occupancy: LocationOccupancy = LocationOccupancy.DIRECT_ALLOWED
    boundary_access: BoundaryAccess = BoundaryAccess.FREE
    spatial_kind: SpatialKind = SpatialKind.SPOT
    minutes_per_unit: float = Field(default=1, gt=0)
    base_visibility_units: float | None = Field(default=None, ge=0)
    footprint: MapGeometry | None = None
    local_bounds: MapGeometry | None = None
    encounter_rate: float = Field(default=0, ge=0, le=1)
    enabled: bool = True
    random_encounter: bool = False
    hidden: bool = False
    discovered: bool = True
    important: bool = False
    planning_tier: str = "minor"
    archived: bool = False
    visibility: str = "public"

    @property
    def parent_location(self) -> DomainReference | None:
        if self.parent_location_id is None:
            return None
        return DomainReference(
            id=self.parent_location_id,
            kind=DomainKind.LOCATION,
        )


TextOrList: TypeAlias = str | list[str]


class FactionState(DomainModel):
    summary: str = ""
    description: str = ""
    imagegen_description: str = ""
    culture: str = ""
    goals: list[str] = Field(default_factory=list)
    secrets: TextOrList = ""
    status: str = ""
    archived: bool = False
    visibility: str = "public"


class ItemState(DomainModel):
    summary: str = ""
    description: str = ""
    imagegen_description: str = ""
    appearance: str = ""
    status: str = ""
    abilities: list[str] = Field(default_factory=list)
    current_location_id: DomainId | None = None
    archived: bool = False
    visibility: str = "public"

    @property
    def current_location(self) -> DomainReference | None:
        if self.current_location_id is None:
            return None
        return DomainReference(
            id=self.current_location_id,
            kind=DomainKind.LOCATION,
        )


class LoreSystemState(DomainModel):
    summary: str = ""
    description: str = ""
    imagegen_description: str = ""
    rules: TextOrList = ""
    limits: TextOrList = ""
    costs: TextOrList = ""
    secrets: TextOrList = ""
    archived: bool = False
    visibility: str = "public"


class FactState(DomainModel):
    summary: str = ""
    description: str = ""
    visibility: str = "public"
    revealed: bool = False
    known_character_ids: list[DomainId] = Field(default_factory=list)
    known_faction_ids: list[DomainId] = Field(default_factory=list)
    archived: bool = False

    @property
    def known_characters(self) -> list[DomainReference]:
        return [
            DomainReference(id=entity_id, kind=DomainKind.CHARACTER)
            for entity_id in self.known_character_ids
        ]

    @property
    def known_factions(self) -> list[DomainReference]:
        return [
            DomainReference(id=entity_id, kind=DomainKind.FACTION)
            for entity_id in self.known_faction_ids
        ]


class PlotBeatStatus(StrEnum):
    PLANNED = "planned"
    AVAILABLE = "available"
    ACTIVE = "active"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class PlotBeatState(DomainModel):
    summary: str = ""
    description: str = ""
    status: PlotBeatStatus = PlotBeatStatus.PLANNED
    goals: list[str] = Field(default_factory=list)
    archived: bool = False
    visibility: str = "public"


class WorldEntity(DomainModel):
    id: DomainId
    kind: EntityKind
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    stats: dict[str, Number] = Field(default_factory=dict)
    active_effects: list[dict[str, Any]] = Field(default_factory=list)
    last_changed_sequence: int | None = None

    @property
    def reference(self) -> DomainReference:
        return DomainReference(id=self.id, kind=DomainKind(self.kind))


class GenericWorldEntity(WorldEntity):
    state: dict[str, Any] = Field(default_factory=dict)


class Character(WorldEntity):
    kind: Literal["character"]
    state: CharacterState = Field(default_factory=CharacterState)


class Location(WorldEntity):
    kind: Literal["location"]
    state: LocationState = Field(default_factory=LocationState)


class Faction(WorldEntity):
    kind: Literal["faction"]
    state: FactionState = Field(default_factory=FactionState)


class Item(WorldEntity):
    kind: Literal["item"]
    state: ItemState = Field(default_factory=ItemState)


class LoreSystem(WorldEntity):
    kind: Literal["lore_system"]
    state: LoreSystemState = Field(default_factory=LoreSystemState)


class Fact(WorldEntity):
    kind: Literal["fact"]
    state: FactState = Field(default_factory=FactState)


class PlotBeat(WorldEntity):
    kind: Literal["plot_beat"]
    state: PlotBeatState = Field(default_factory=PlotBeatState)


TypedWorldEntity: TypeAlias = (
    Character
    | Location
    | Faction
    | Item
    | LoreSystem
    | Fact
    | PlotBeat
    | GenericWorldEntity
)


class Relationship(DomainModel):
    id: DomainId
    source_id: DomainId
    target_id: DomainId
    relation: str = Field(min_length=1)
    stats: dict[str, Number] = Field(default_factory=dict)
    active_effects: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def reference(self) -> DomainReference:
        return DomainReference(
            id=self.id,
            kind=DomainKind.RELATIONSHIP,
        )


class Weather(DomainModel):
    id: DomainId
    project_id: DomainId
    name: str = Field(min_length=1)
    description: str = ""
    imagegen_description: str = ""
    tags: list[str] = Field(default_factory=list)
    image_tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def reference(self) -> DomainReference:
        return DomainReference(id=self.id, kind=DomainKind.WEATHER)


class Outfit(DomainModel):
    id: DomainId
    entity_id: DomainId
    name: str = Field(min_length=1)
    description: str = ""
    imagegen_description: str = ""
    equipment: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def reference(self) -> DomainReference:
        return DomainReference(id=self.id, kind=DomainKind.OUTFIT)


class StatDisplayStyle(StrEnum):
    COMPACT = "compact"
    BAR = "bar"


class Stat(DomainModel):
    id: DomainId
    project_id: DomainId
    stat_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1)
    description: str = ""
    scope: StatScope = StatScope.CHARACTER
    default_value: Number = 0
    minimum: Number = 0
    maximum: Number = 100
    minimum_stat_key: str | None = None
    maximum_stat_key: str | None = None
    color: str | None = None
    minimum_color: str | None = None
    maximum_color: str | None = None
    display_style: StatDisplayStyle = StatDisplayStyle.COMPACT
    integer_only: bool = True
    visibility: StatVisibility = StatVisibility.PUBLIC
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Stat:
        if self.minimum > self.maximum:
            raise ValueError("stat minimum cannot exceed maximum")
        if not self.minimum_stat_key and not self.maximum_stat_key:
            if self.default_value < self.minimum or self.default_value > self.maximum:
                raise ValueError("stat default must be within numeric bounds")
        if self.minimum_stat_key == self.stat_key:
            raise ValueError("stat cannot use itself as minimum")
        if self.maximum_stat_key == self.stat_key:
            raise ValueError("stat cannot use itself as maximum")
        return self

    @property
    def reference(self) -> DomainReference:
        return DomainReference(id=self.id, kind=DomainKind.STAT)


class ResolvedStatBounds(DomainModel):
    minimum: Number
    maximum: Number
    minimum_stat_key: str | None = None
    maximum_stat_key: str | None = None


def resolve_stat_bounds(
    definition: Stat,
    values: dict[str, Number],
    stat_lookup: Any | None = None,
) -> ResolvedStatBounds:
    def resolve_reference(key: str | None, fallback: Number) -> Number:
        if not key:
            return fallback
        if key in values:
            return values[key]
        if stat_lookup is None:
            return fallback
        referenced = stat_lookup(key, str(definition.scope))
        return values.get(key, referenced.default_value)

    minimum = resolve_reference(
        definition.minimum_stat_key,
        definition.minimum,
    )
    maximum = resolve_reference(
        definition.maximum_stat_key,
        definition.maximum,
    )
    if float(minimum) > float(maximum):
        raise ValueError(
            f"Resolved bounds for {definition.stat_key} are invalid: "
            f"{minimum} > {maximum}"
        )
    return ResolvedStatBounds(
        minimum=minimum,
        maximum=maximum,
        minimum_stat_key=definition.minimum_stat_key,
        maximum_stat_key=definition.maximum_stat_key,
    )


class RequirementExpression(DomainModel):
    """Recursive requirement tree with legacy leaf compatibility."""

    tags: list[str] = Field(default_factory=list)
    min_stats: dict[str, Number] = Field(default_factory=dict)
    kind: RequirementKind | None = None
    children: list[RequirementExpression] = Field(default_factory=list)
    child: RequirementExpression | None = None
    target: str = EffectTarget.ACTOR
    stat_key: str | None = None
    comparison: ComparisonOperator = ComparisonOperator.GTE
    value: Number | str | bool | None = None
    item_id: DomainId | None = None
    tag: str | None = None
    relation: str | None = None
    location_id: DomainId | None = None
    time_phase_id: DomainId | None = None
    weather_id: DomainId | None = None
    ability_key: str | None = None

    @model_validator(mode="after")
    def validate_tree_shape(self) -> RequirementExpression:
        if self.kind in {RequirementKind.AND, RequirementKind.OR} and not self.children:
            raise ValueError("and/or requirements need children")
        if self.kind == RequirementKind.NOT and self.child is None:
            raise ValueError("not requirement needs a child")
        if self.kind == RequirementKind.COMPARE and not self.stat_key:
            raise ValueError("compare requirement needs stat_key")
        if self.kind == RequirementKind.COMPARE and self.value is None:
            raise ValueError("compare requirement needs value")
        if self.kind == RequirementKind.HAS_ITEM and not self.item_id:
            raise ValueError("has_item requirement needs item_id")
        if self.kind == RequirementKind.HAS_TAG and not self.tag:
            raise ValueError("has_tag requirement needs tag")
        if self.kind == RequirementKind.RELATIONSHIP and not self.relation:
            raise ValueError("relationship requirement needs relation")
        if self.kind == RequirementKind.LOCATION and not self.location_id:
            raise ValueError("location requirement needs location_id")
        if self.kind == RequirementKind.TIME and not self.time_phase_id:
            raise ValueError("time requirement needs time_phase_id")
        if self.kind == RequirementKind.WEATHER and not self.weather_id:
            raise ValueError("weather requirement needs weather_id")
        if self.kind == RequirementKind.HAS_ABILITY and not self.ability_key:
            raise ValueError("has_ability requirement needs ability_key")
        return self


class MapAnchor(DomainModel):
    id: DomainId
    location_id: DomainId
    coordinate_space_id: DomainId | None = None
    name: str = Field(min_length=1)
    kind: AnchorKind = AnchorKind.WAYPOINT
    x: Number | None = None
    y: Number | None = None
    hidden: bool = False
    discovered: bool = True
    enabled: bool = True
    requires_map_review: bool = False

    @model_validator(mode="after")
    def validate_position(self) -> "MapAnchor":
        if (self.x is None) != (self.y is None):
            raise ValueError("map anchor x and y must both be set or both be null")
        if self.x is None:
            self.requires_map_review = True
        return self


class ConnectionLock(DomainModel):
    locked: bool = True
    minigame_key: str | None = None
    difficulty: int = Field(default=1, ge=0)
    success_behavior: LockSuccessBehavior = LockSuccessBehavior.PERSISTENT


class EncounterCandidate(DomainModel):
    location_id: DomainId
    weight: float = Field(default=1, gt=0)


class EncounterRule(DomainModel):
    id: DomainId
    location_id: DomainId | None = None
    connection_id: DomainId | None = None
    probability: float = Field(default=0, ge=0, le=1)
    candidates: list[EncounterCandidate] = Field(default_factory=list)
    hidden: bool = False
    discovered: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def validate_owner(self) -> "EncounterRule":
        if bool(self.location_id) == bool(self.connection_id):
            raise ValueError("encounter rule needs exactly one location or connection owner")
        return self


class Barrier(DomainModel):
    id: DomainId
    location_id: DomainId
    name: str = Field(min_length=1)
    geometry: MapGeometry | None = None
    blocked_modes: list[str] = Field(default_factory=lambda: ["walk"])
    requirements: RequirementExpression | None = None
    hidden: bool = False
    discovered: bool = True
    enabled: bool = True
    requires_map_review: bool = False


class TravelConnection(DomainModel):
    id: DomainId
    kind: ConnectionKind = ConnectionKind.ROUTE
    source_anchor_id: DomainId
    target_anchor_id: DomainId
    travel_minutes: int = Field(default=0, ge=0)
    modes: list[str] = Field(default_factory=lambda: ["walk"])
    bidirectional: bool = True
    requirements: RequirementExpression | None = None
    lock: ConnectionLock | None = None
    hidden: bool = False
    discovered: bool = True
    enabled: bool = True


class TravelSegment(DomainModel):
    kind: Literal["geometric", "connection"]
    source_location_id: DomainId
    target_location_id: DomainId
    minutes: float = Field(ge=0)
    connection_id: DomainId | None = None
    points: list[MapPoint] = Field(default_factory=list)


class TravelItinerary(DomainModel):
    id: DomainId
    character_id: DomainId
    destination_location_id: DomainId | None = None
    destination_anchor_id: DomainId | None = None
    destination_x: Number | None = None
    destination_y: Number | None = None
    mode: str = "walk"
    segments: list[TravelSegment] = Field(default_factory=list)
    current_segment: int = Field(default=0, ge=0)
    remaining_minutes: float = Field(default=0, ge=0)
    status: ItineraryStatus = ItineraryStatus.ACTIVE
    interruption: dict[str, Any] | None = None
    traversal_seed: str = ""


class ActionEffect(DomainModel):
    """A typed stat, world-state, relationship, time, or noise effect."""

    # Unknown legacy target labels historically behaved like "target". Keep
    # accepting them unless a separate migration slice changes that contract.
    target: str = EffectTarget.TARGET
    stat_key: str | None = None
    operation: EffectOperation = EffectOperation.ADD
    amount: Number = 0
    # Unknown duration labels historically meant an immediate effect.
    duration_type: str | None = None
    duration_value: int = 0
    destination_id: DomainId | None = None
    entity_kind: EntityKind | None = None
    name: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None
    fact_id: DomainId | None = None
    relation: str | None = None
    minutes: int = 0
    noise_id: DomainId | None = None

    @model_validator(mode="after")
    def validate_operation_shape(self) -> ActionEffect:
        if int(self.duration_value or 0) < 0:
            raise ValueError("effect duration cannot be negative")
        if self.operation in {
            EffectOperation.ADD,
            EffectOperation.SUBTRACT,
            EffectOperation.SET,
            EffectOperation.MULTIPLY,
        } and not self.stat_key:
            raise ValueError("stat effect needs stat_key")
        if self.operation == EffectOperation.MOVE and not self.destination_id:
            raise ValueError("move effect needs destination_id")
        if self.operation == EffectOperation.CREATE and (
            self.entity_kind is None or not (self.name or "").strip()
        ):
            raise ValueError("create effect needs entity_kind and name")
        if self.operation == EffectOperation.REVEAL_KNOWLEDGE and not self.fact_id:
            raise ValueError("reveal_knowledge effect needs fact_id")
        if self.operation == EffectOperation.CHANGE_RELATIONSHIP and not self.relation:
            raise ValueError("change_relationship effect needs relation")
        if self.operation == EffectOperation.PLAY_NOISE and not self.noise_id:
            raise ValueError("play_noise effect needs noise_id")
        if self.operation == EffectOperation.ADVANCE_TIME and int(
            self.minutes or self.amount
        ) < 0:
            raise ValueError("advance_time effect cannot move backward")
        if self.operation == EffectOperation.APPLY_STATUS and not (
            self.status or self.name
        ):
            raise ValueError("apply_status effect needs status")
        return self


class Ability(DomainModel):
    id: DomainId
    project_id: DomainId
    ability_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1)
    description: str = ""
    target_type: AbilityTarget = AbilityTarget.SELF
    requirements: RequirementExpression = Field(
        default_factory=RequirementExpression,
    )
    costs: dict[str, Number] = Field(default_factory=dict)
    effects: list[ActionEffect] = Field(default_factory=list)
    minigame_profile: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def reference(self) -> DomainReference:
        return DomainReference(id=self.id, kind=DomainKind.ABILITY)
