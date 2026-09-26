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
    EFFECT = "effect"
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


class StatOwnerKind(StrEnum):
    CHARACTER = "character"
    ITEM = "item"
    LOCATION = "location"
    FACTION = "faction"
    LORE_SYSTEM = "lore_system"
    FACT = "fact"
    PLOT_BEAT = "plot_beat"
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


class FormulaParticipant(StrEnum):
    ACTOR = "actor"
    SOURCE = "source"
    TARGET = "target"


class FormulaNodeKind(StrEnum):
    CONSTANT = "constant"
    STAT = "stat"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    NEGATE = "negate"


class EffectClock(StrEnum):
    STORY_MINUTES = "story_minutes"
    TARGET_ACTIONS = "target_actions"
    WORLD_ACTIONS = "world_actions"


class EffectEvaluationMode(StrEnum):
    SNAPSHOT = "snapshot"
    LIVE = "live"


class EffectStackingPolicy(StrEnum):
    REPLACE = "replace"
    REFRESH = "refresh"
    STACK = "stack"
    INDEPENDENT = "independent"


class AbilityKind(StrEnum):
    ACTIVE = "active"
    PASSIVE = "passive"


class AbilityOwnerKind(StrEnum):
    CHARACTER = "character"
    ITEM = "item"


class AbilityActionKind(StrEnum):
    APPLY_EFFECT = "apply_effect"
    MOVE = "move"
    CREATE = "create"
    REMOVE = "remove"
    REVEAL_KNOWLEDGE = "reveal_knowledge"
    CHANGE_RELATIONSHIP = "change_relationship"
    ADVANCE_TIME = "advance_time"
    PLAY_NOISE = "play_noise"


class AbilityCostKind(StrEnum):
    STAT = "stat"
    CONSUME_SOURCE = "consume_source"
    CONSUME_FUEL = "consume_fuel"


class PassiveTriggerKind(StrEnum):
    ABILITY_USED = "ability_used"
    STAT_CHANGED = "stat_changed"
    DAMAGE = "damage"
    OWNER_ACTION = "owner_action"
    MOVEMENT = "movement"
    TIME_ADVANCED = "time_advanced"


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
        minimum = {"point": 1, "polyline": 2, "polygon": 2}[str(self.kind)]
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
    priority_layer: float = 0
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
    project_id: DomainId
    stat_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1)
    description: str = ""
    compatible_owner_kinds: list[StatOwnerKind] = Field(
        default_factory=lambda: [StatOwnerKind.CHARACTER]
    )
    default_value: Number = 0
    minimum: Number = 0
    maximum: Number = 100
    minimum_stat_key: str | None = None
    maximum_stat_key: str | None = None
    color: str | None = None
    minimum_color: str | None = None
    maximum_color: str | None = None
    icon: str | None = None
    display_style: StatDisplayStyle = StatDisplayStyle.COMPACT
    integer_only: bool = True
    visibility: StatVisibility = StatVisibility.PUBLIC
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Stat:
        if not self.compatible_owner_kinds:
            raise ValueError("stat needs at least one compatible owner kind")
        self.compatible_owner_kinds = list(dict.fromkeys(self.compatible_owner_kinds))
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
        return DomainReference(id=self.stat_key, kind=DomainKind.STAT)


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
        referenced = stat_lookup(key)
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


def validate_stat_dependency_graph(definitions: list[Stat]) -> None:
    """Validate project-local dynamic stat-bound references as one graph."""
    by_key = {item.stat_key: item for item in definitions}
    graph: dict[str, list[str]] = {}
    for definition in definitions:
        dependencies = [
            key
            for key in (definition.minimum_stat_key, definition.maximum_stat_key)
            if key
        ]
        for key in dependencies:
            referenced = by_key.get(key)
            if referenced is None:
                raise ValueError(
                    f"Stat {definition.stat_key} references unavailable bound stat {key}"
                )
            if not set(map(str, definition.compatible_owner_kinds)).intersection(
                map(str, referenced.compatible_owner_kinds)
            ):
                raise ValueError(
                    f"Stat {definition.stat_key} has no compatible owner kind "
                    f"in common with bound stat {key}"
                )
        graph[definition.stat_key] = dependencies

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError("Stat bound dependencies contain a cycle")
        if key in visited:
            return
        visiting.add(key)
        for child in graph.get(key, []):
            visit(child)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


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
    binding_kind: Literal["coordinate", "area", "area_border", "spot"] = "coordinate"
    binding_target_id: DomainId | None = None
    binding_offset_x: Number | None = None
    binding_offset_y: Number | None = None
    binding_segment_index: int | None = Field(default=None, ge=0)
    binding_segment_t: float | None = Field(default=None, ge=0, le=1)
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
        # Semantic bindings derive their position from the bound location or
        # area geometry. Only free-coordinate anchors require stored x/y.
        if self.binding_kind == "coordinate" and self.x is None:
            self.requires_map_review = True
        elif self.binding_kind != "coordinate":
            self.requires_map_review = False
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


class FormulaNode(DomainModel):
    kind: FormulaNodeKind
    value: Number | None = None
    participant: FormulaParticipant | None = None
    stat_key: str | None = None
    children: list[FormulaNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> "FormulaNode":
        if self.kind == FormulaNodeKind.CONSTANT:
            if self.value is None or self.participant or self.stat_key or self.children:
                raise ValueError("constant formula nodes contain only a value")
        elif self.kind == FormulaNodeKind.STAT:
            if not self.participant or not self.stat_key or self.value is not None or self.children:
                raise ValueError("stat formula nodes need participant and stat_key")
        else:
            expected = 1 if self.kind == FormulaNodeKind.NEGATE else 2
            if len(self.children) != expected or self.value is not None or self.participant or self.stat_key:
                raise ValueError(f"{self.kind} formula nodes need {expected} children")
        return self


class EffectDefinition(DomainModel):
    project_id: DomainId
    effect_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1)
    description: str = ""
    target_stat_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    operation: EffectOperation = EffectOperation.ADD
    formula: FormulaNode
    value_expression: dict[str, Any] | None = None
    clock: EffectClock = EffectClock.WORLD_ACTIONS
    duration: int = Field(default=0, ge=-1)
    tick_interval: int = Field(default=0, ge=0)
    evaluation_mode: EffectEvaluationMode = EffectEvaluationMode.SNAPSHOT
    stacking_policy: EffectStackingPolicy = EffectStackingPolicy.REPLACE
    max_stacks: int = Field(default=1, ge=1)
    visibility: StatVisibility = StatVisibility.PUBLIC
    icon: str | None = None
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> "EffectDefinition":
        valid = (
            (self.duration == 0 and self.tick_interval == 0)
            or (self.duration > 0 and self.tick_interval <= self.duration)
            or (self.duration == -1 and self.tick_interval > 0)
        )
        if not valid:
            raise ValueError("invalid effect duration/tick combination")
        count = 0
        def visit(node: FormulaNode, depth: int) -> None:
            nonlocal count
            count += 1
            if depth > 12 or count > 64:
                raise ValueError("effect formula exceeds complexity limits")
            for child in node.children: visit(child, depth + 1)
        visit(self.formula, 1)
        return self

    @property
    def reference(self) -> DomainReference:
        return DomainReference(id=self.effect_key, kind=DomainKind.EFFECT)


class AbilityCost(DomainModel):
    kind: AbilityCostKind = AbilityCostKind.STAT
    stat_key: str | None = None
    item_id: DomainId | None = None
    amount: Number = Field(gt=0)

    @model_validator(mode="after")
    def validate_shape(self) -> "AbilityCost":
        if self.kind == AbilityCostKind.STAT:
            if not self.stat_key:
                raise ValueError("stat cost needs stat_key")
            if self.item_id:
                raise ValueError("stat cost cannot contain item_id")
        elif self.kind == AbilityCostKind.CONSUME_FUEL:
            if not self.item_id:
                raise ValueError("fuel cost needs item_id")
            if self.stat_key:
                raise ValueError("fuel cost cannot contain stat_key")
        elif self.stat_key or self.item_id:
            raise ValueError("consume_source cost cannot contain stat_key or item_id")
        return self


class AbilityAction(DomainModel):
    kind: AbilityActionKind
    target: EffectTarget = EffectTarget.TARGET
    effect_key: str | None = None
    destination_id: DomainId | None = None
    entity_kind: EntityKind | None = None
    entity_name: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    fact_id: DomainId | None = None
    relation: str | None = None
    minutes: int | None = Field(default=None, ge=0)
    noise_id: DomainId | None = None
    duration_override: int | None = Field(default=None, ge=-1)
    tick_override: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_shape(self) -> "AbilityAction":
        required = {
            AbilityActionKind.APPLY_EFFECT: self.effect_key,
            AbilityActionKind.MOVE: self.destination_id,
            AbilityActionKind.CREATE: self.entity_kind and self.entity_name,
            AbilityActionKind.REVEAL_KNOWLEDGE: self.fact_id,
            AbilityActionKind.CHANGE_RELATIONSHIP: self.relation,
            AbilityActionKind.ADVANCE_TIME: self.minutes is not None,
            AbilityActionKind.PLAY_NOISE: self.noise_id,
        }
        if self.kind in required and not required[self.kind]:
            raise ValueError(f"{self.kind} action is missing its required reference")
        fields_by_kind = {
            AbilityActionKind.APPLY_EFFECT: {"effect_key", "duration_override", "tick_override"},
            AbilityActionKind.MOVE: {"destination_id"},
            AbilityActionKind.CREATE: {"entity_kind", "entity_name", "state"},
            AbilityActionKind.REMOVE: set(),
            AbilityActionKind.REVEAL_KNOWLEDGE: {"fact_id"},
            AbilityActionKind.CHANGE_RELATIONSHIP: {"relation"},
            AbilityActionKind.ADVANCE_TIME: {"minutes"},
            AbilityActionKind.PLAY_NOISE: {"noise_id"},
        }
        populated = {
            "effect_key": self.effect_key,
            "destination_id": self.destination_id,
            "entity_kind": self.entity_kind,
            "entity_name": self.entity_name,
            "state": self.state or None,
            "fact_id": self.fact_id,
            "relation": self.relation,
            "minutes": self.minutes,
            "noise_id": self.noise_id,
            "duration_override": self.duration_override,
            "tick_override": self.tick_override,
        }
        invalid = sorted(key for key, value in populated.items() if value is not None and key not in fields_by_kind[self.kind])
        if invalid:
            raise ValueError(f"{self.kind} action contains incompatible field(s): {', '.join(invalid)}")
        return self


class PassiveTrigger(DomainModel):
    kind: PassiveTriggerKind
    stat_key: str | None = None


class Ability(DomainModel):
    project_id: DomainId
    ability_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1)
    description: str = ""
    ability_kind: AbilityKind = AbilityKind.ACTIVE
    compatible_owner_kinds: list[AbilityOwnerKind] = Field(
        default_factory=lambda: [AbilityOwnerKind.CHARACTER]
    )
    target_type: AbilityTarget = AbilityTarget.SELF
    requirements: RequirementExpression = Field(default_factory=RequirementExpression)
    costs: list[AbilityCost] = Field(default_factory=list)
    rule_costs: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[AbilityAction] = Field(default_factory=list)
    passive_triggers: list[PassiveTrigger] = Field(default_factory=list)
    icon: str | None = None
    enabled: bool = True
    timed_attack_line_count: int | None = Field(default=None, ge=1, le=8)
    timed_attack_damage_per_line: Number | None = Field(default=None, ge=0)
    bullethell_skill_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_ability(self) -> "Ability":
        if not self.compatible_owner_kinds:
            raise ValueError("ability needs at least one compatible owner kind")
        self.compatible_owner_kinds = list(dict.fromkeys(self.compatible_owner_kinds))
        if self.ability_kind == AbilityKind.PASSIVE and not self.passive_triggers:
            raise ValueError("passive ability needs at least one trigger")
        if (self.timed_attack_line_count is None) != (self.timed_attack_damage_per_line is None):
            raise ValueError("timed attack line count and damage must be configured together")
        return self

    @property
    def reference(self) -> DomainReference:
        return DomainReference(id=self.ability_key, kind=DomainKind.ABILITY)
