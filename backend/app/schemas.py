from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator
from app.domain.world import ActionEffect, RequirementExpression


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "member"] = "member"


class AdminUserUpdate(BaseModel):
    enabled: bool | None = None
    role: Literal["admin", "member"] | None = None


class AdminPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ProjectAssignmentsUpdate(BaseModel):
    project_ids: list[str] = Field(default_factory=list, max_length=1000)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    stats_preset: Literal["none", "adventure", "romance"] = "none"


class ProjectUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class BibleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=200_000)


class StoryTurnCreate(BaseModel):
    parent_id: str | None = None
    content: str = Field(default="", max_length=50_000)
    action: Literal["story", "say", "do", "guide", "continue"] = "do"
    pov_character_id: str | None = None
    narration_mode: Literal["first_person", "third_limited", "third_omniscient"] | None = None
    requested_ability: dict[str, Any] | None = None
    generation_mode: Literal["direct", "low", "smart"] | None = None

    @model_validator(mode="after")
    def content_required_for_input_actions(self) -> "StoryTurnCreate":
        if self.action != "continue" and not self.content.strip():
            raise ValueError(f"{self.action.title()} input cannot be empty")
        return self


class StoryEditCreate(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)


class StoryTextUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)


class StoryRegenerateRequest(BaseModel):
    guide: str = Field(default="", max_length=10_000)
    generation_mode: Literal["direct", "low", "smart"] | None = None


class StorySettingsUpdate(BaseModel):
    default_generation_mode: Literal["direct", "low", "smart"] = "low"
    response_max_tokens: int = Field(default=300, ge=64, le=1400)
    ai_instructions: str = Field(default="", max_length=20_000)


class MinigameConfigUpdate(BaseModel):
    enabled: bool = False
    ai_description: str = Field(default="", max_length=2000)
    allowed_directions: list[Literal["player_acts", "acted_on"]] = Field(default_factory=lambda: ["player_acts", "acted_on"])
    allowed_actions: list[Literal["story", "say", "do", "guide", "continue"]] = Field(default_factory=lambda: ["do"])
    required_actor_tags: list[str] = Field(default_factory=list, max_length=100)
    forbidden_actor_tags: list[str] = Field(default_factory=list, max_length=100)
    required_target_tags: list[str] = Field(default_factory=list, max_length=100)
    forbidden_target_tags: list[str] = Field(default_factory=list, max_length=100)
    required_location_tags: list[str] = Field(default_factory=list, max_length=100)
    forbidden_location_tags: list[str] = Field(default_factory=list, max_length=100)
    min_difficulty: int = 1
    max_difficulty: int = 10
    timer_policy: Literal["never", "ai_allowed", "always"] = "never"
    fallback_attempts: int = Field(default=3, ge=1, le=10)
    allow_infinite_attempts: bool = True
    allow_teeth_override: bool = True
    min_teeth: int = Field(default=2, ge=2, le=23)
    max_teeth: int = Field(default=12, ge=2, le=23)
    allow_empty_slots_override: bool = True
    min_empty_slots: int = Field(default=1, ge=1, le=22)
    max_empty_slots: int = Field(default=12, ge=1, le=22)
    allow_time_override: bool = True
    min_time_seconds: int = Field(default=10, ge=1, le=3600)
    max_time_seconds: int = Field(default=120, ge=1, le=3600)
    allow_direction_reversal: bool = True
    min_attack_lines: int = Field(default=1, ge=1, le=8)
    max_attack_lines: int = Field(default=8, ge=1, le=8)
    min_attack_damage: float = Field(default=1, ge=0, le=1_000_000)
    max_attack_damage: float = Field(default=100, ge=0, le=1_000_000)
    dodge_control_mode: Literal["pointer", "keyboard"] = "pointer"
    min_fallback_hp: float = Field(default=1, ge=1, le=1_000_000)
    max_fallback_hp: float = Field(default=999, ge=1, le=1_000_000)
    min_enemy_attack: float = Field(default=0, ge=0, le=1_000_000)
    max_enemy_attack: float = Field(default=999, ge=0, le=1_000_000)


class MinigameGroupUpdate(BaseModel):
    enabled: bool


class MinigameResolveRequest(BaseModel):
    choice: Literal["heads", "tails"] | None = None
    position: float | None = None
    elapsed_ms: float | None = None
    count: int | None = None
    violation_ms: float | None = None
    broken_picks: int | None = None
    final_angle: float | None = None
    lock_rotation: float | None = None
    timeout: bool | None = None
    rotations: list[int] | None = Field(default=None, max_length=7)
    move_count: int | None = None
    events: list[dict[str, Any]] | None = Field(default=None, max_length=256)
    distance_moved: float | None = None
    samples: list[dict[str, Any]] | None = Field(default=None, max_length=256)
    skill_events: list[dict[str, Any]] | None = Field(default=None, max_length=50)


class BulletHellCloneRequest(BaseModel):
    definition_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=120)


class BulletHellSkillUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    behavior: Literal["free_move", "blue_gravity", "roll"]
    parameters: dict[str, float] = Field(default_factory=dict)


class BulletHellModeUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    movement_skill_id: str
    allowed_skill_ids: list[str] = Field(default_factory=list, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)


class BulletHellAttackUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    ai_description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    uses_enemy_forced_mode: bool = False
    hit_immunity_ms: int = Field(default=500, ge=0, le=5000)
    phases: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class ProjectBulletHellUpdate(BaseModel):
    default_mode_id: str | None = None
    allowed_mode_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_skill_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_attack_ids: list[str] = Field(default_factory=list, max_length=100)


class RuntimeSettingsUpdate(BaseModel):
    data_dir: str = ""
    llama_executable: str = ""
    storyteller_model_path: str = ""
    storyteller_model_id: str = ""
    llama_url: HttpUrl = "http://127.0.0.1:8080"
    llama_extra_args: list[str] = Field(default_factory=list)
    comfy_command: list[str] = Field(default_factory=list)
    comfy_workdir: str = ""
    comfy_url: HttpUrl = "http://127.0.0.1:8188"
    context_tokens: int = Field(default=8192, ge=2048, le=131072)
    planning_context_tokens: int | None = Field(default=None, ge=2048, le=131072)
    memory_provider: Literal["builtin", "cognee"] = "builtin"
    portrait_prompt_prefix: str = Field(
        default="portrait, anime style, full color, clean lineart, soft shading, looking at viewer, simple background, white background,",
        max_length=4000,
    )
    full_body_prompt_prefix: str = Field(
        default="full body, standing, anime style, full color, clean lineart, soft shading, looking at viewer, simple background, white background,",
        max_length=4000,
    )
    icon_prompt_prefix: str = Field(
        default="(((no humans))),simple background, white background,",
        max_length=4000,
    )

    @model_validator(mode="after")
    def planning_context_covers_story_context(self) -> "RuntimeSettingsUpdate":
        if self.planning_context_tokens is None:
            self.planning_context_tokens = self.context_tokens
        if self.planning_context_tokens < self.context_tokens:
            raise ValueError("planning context tokens cannot be smaller than story context tokens")
        return self

    @field_validator("llama_url", "comfy_url")
    @classmethod
    def loopback_only(cls, value: HttpUrl) -> HttpUrl:
        if value.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Inference services must use a loopback address")
        return value

    @field_validator("llama_extra_args")
    @classmethod
    def protect_llama_binding(cls, value: list[str]) -> list[str]:
        reserved = {"--host", "--port", "--models-dir", "--parallel", "-np", "--ctx-size", "-c"}
        if any(argument.split("=", 1)[0] in reserved for argument in value):
            raise ValueError("llama extra arguments cannot override host, port, or models directory")
        return value


class WorkflowMapping(BaseModel):
    node_id: str
    input_name: str | None = None


class WorkflowMappings(BaseModel):
    positive_prompt: WorkflowMapping
    image_output: WorkflowMapping
    transparent_image_output: WorkflowMapping | None = None
    negative_prompt: WorkflowMapping | None = None
    seed: WorkflowMapping | None = None
    width: WorkflowMapping | None = None
    height: WorkflowMapping | None = None
    steps: WorkflowMapping | None = None
    guidance: WorkflowMapping | None = None
    checkpoint: WorkflowMapping | None = None


class WorkflowPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    graph: dict[str, Any]
    mappings: WorkflowMappings


class ImageGenerateRequest(BaseModel):
    workflow_preset_id: str
    prompt: str = Field(min_length=1, max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)
    make_transparent: bool | None = None
    seed: int | None = None
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    steps: int | None = Field(default=None, ge=1, le=500)
    guidance: float | None = Field(default=None, ge=0, le=100)
    checkpoint: str | None = None


class SceneImageRequest(ImageGenerateRequest):
    node_id: str | None = None
    prompt: str = Field(default="", max_length=20_000)


class ImageSuggestionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)


class EventMessage(BaseModel):
    type: Literal[
        "runtime", "job", "token", "story", "suggestion", "image", "error", "planning",
        "tool", "approval_required", "memory_changed", "reconciliation_warning", "world_head",
        "npc", "encounter", "media", "music", "stats", "minigame", "notice",
    ]
    payload: dict[str, Any]


class PlanningSessionCreate(BaseModel):
    scale_preset: Literal["intimate", "local", "regional", "global"] = "local"
    major_locations: int = Field(default=6, ge=1, le=30)
    minor_locations: int = Field(default=20, ge=0, le=200)
    rooms: int = Field(default=16, ge=0, le=200)
    characters: int = Field(default=10, ge=1, le=100)
    direction: str = Field(default="", max_length=10_000)


class RandomPlanningDirectionRequest(BaseModel):
    theme: str = Field(default="", max_length=200)


class ProjectStoryDefaultsUpdate(BaseModel):
    narration_mode: Literal["first_person", "third_limited", "third_omniscient"]
    pov_strategy: Literal["first_player", "selected_character", "none"]
    pov_character_id: str | None = None


class PlanningImagePlanUpdate(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)
    workflow_preset_id: str | None = None
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)


class PlanningImageGenerateBatch(BaseModel):
    plan_ids: list[str] = Field(default_factory=list, max_length=500)


class PlanningDraftUpdate(BaseModel):
    draft: dict[str, Any]


class PlanningResolution(BaseModel):
    action: Literal["link", "merge", "rename", "omit", "keep_manual", "overwrite", "unlink"]
    entity_id: str | None = None
    new_name: str | None = Field(default=None, min_length=1, max_length=200)


class PlanningApprovalRequest(PlanningDraftUpdate):
    resolutions: dict[str, PlanningResolution] = Field(default_factory=dict)


class PlanningBatchAcceptRequest(PlanningDraftUpdate):
    focus: str = Field(min_length=1, max_length=64)


class PlanningDeleteRequest(BaseModel):
    mode: Literal["keep_world", "remove_world"] = "keep_world"
    confirmation: str


class DataResetRequest(BaseModel):
    confirmation: str


class DeletionImpact(BaseModel):
    object_id: str
    name: str = ""
    confirmation: str
    counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PlanningConflictModel(BaseModel):
    entity_key: str
    proposed: dict[str, Any]
    candidates: list[dict[str, Any]]
    recommended_resolution: PlanningResolution | None = None


class DataSummaryModel(BaseModel):
    counts: dict[str, int]
    managed_disk_bytes: int
    active_jobs: list[dict[str, Any]]
    trashed_story_nodes: int
    orphan_files: list[str]
    dangling_fts_rows: int
    file_failures: list[dict[str, Any]]


class RecoveryWarning(BaseModel):
    code: str
    message: str


class PlanningGenerateRequest(BaseModel):
    prompt: str = Field(default="", max_length=10_000)
    repair: bool = False
    automate: bool = False
    automation_prompt: str = Field(default="", max_length=10_000)
    append: bool = False
    focus: str | None = Field(default=None, max_length=64)

class GenerationTaskGenerateRequest(BaseModel):
    prompt: str = Field(default="", max_length=10_000)
    repair: bool = False
    automate: bool = False
    automation_prompt: str = Field(default="", max_length=10_000)
    append: bool = False
    focus: str | None = Field(default=None, max_length=64)


class GenerationTaskReviewRequest(BaseModel):
    result: dict[str, Any] | None = None
    note: str = Field(default="", max_length=10_000)
    resolutions: dict[str, PlanningResolution] = Field(default_factory=dict)


class GenerationTaskRejectRequest(BaseModel):
    note: str = Field(default="", max_length=10_000)


class GenerationResultUpdate(BaseModel):
    result: dict[str, Any]


class GenerationDependencyUpdate(BaseModel):
    task_key: str = Field(min_length=1, max_length=120)
    required_state: Literal["generated", "approved", "committed"] = "generated"


class GenerationPlanTaskCreate(BaseModel):
    task_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,119}$")
    label: str = Field(default="", max_length=200)
    generator_kind: Literal["text", "image", "deterministic"]
    target_kind: str = Field(min_length=1, max_length=120)
    target_key: str | None = Field(default=None, max_length=200)
    prompt: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[GenerationDependencyUpdate] = Field(default_factory=list)


class GenerationPlanTaskUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    generator_kind: Literal["text", "image", "deterministic"] | None = None
    target_kind: str | None = Field(default=None, min_length=1, max_length=120)
    target_key: str | None = Field(default=None, max_length=200)
    prompt: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class GenerationDependenciesUpdate(BaseModel):
    dependencies: list[GenerationDependencyUpdate] = Field(default_factory=list)



class WorldEntityCreate(BaseModel):
    kind: Literal["character", "location", "faction", "item", "lore_system", "fact", "relationship", "plot_beat"]
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    state: dict[str, Any] = Field(default_factory=dict)


class WorldEntityUpdate(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    tags: list[str] | None = None


class WorldCloneRequest(BaseModel):
    source_project_id: str = Field(min_length=1)
    entity_ids: list[str] = Field(min_length=1, max_length=500)
    include_children: bool = True
    include_relationships: bool = True
    include_referenced_entities: bool = True
    include_rules: bool = True
    max_depth: int = Field(default=8, ge=0, le=32)


class HardDeleteConfirm(BaseModel):
    confirmation: str


class WorldMutationBatch(BaseModel):
    mutations: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    summary: str = Field(default="Author world edit", max_length=500)


class NpcSettingsUpdate(BaseModel):
    autonomy_enabled: bool = False
    intervention_frequency: Literal["low", "normal", "high"] = "normal"


class OutfitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    appearance: str = Field(default="", max_length=5000)
    equipment: list[str] = Field(default_factory=list, max_length=100)


class EntityMediaCreate(BaseModel):
    kind: Literal["portrait", "full_body"]
    outfit_id: str | None = None
    prompt: str = Field(default="", max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)


class MediaAssetUpdate(BaseModel):
    prompt: str = Field(default="", max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)


class MusicThemeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    playback_mode: Literal["shuffle", "repeat_one", "in_order"] = "shuffle"


class MusicTrackUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    position: int = Field(default=0, ge=0, le=100_000)


class ProjectMusicUpdate(BaseModel):
    mode: Literal["disabled", "player_managed", "ai_managed"] = "disabled"
    enabled_theme_ids: list[str] = Field(default_factory=list, max_length=100)
    manual_theme_id: str | None = None
    volume: float = Field(default=0.7, ge=0, le=1)


class MusicPlaybackUpdate(BaseModel):
    theme_id: str
    track_id: str


class EnvironmentSettingsUpdate(BaseModel):
    enabled: bool = True
    ai_create_locations: bool = False
    ai_propose_weather: bool = False
    auto_generate_backgrounds: bool = False
    background_workflow_id: str | None = None
    initial_weather_id: str


class WeatherDefinitionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    imagegen_description: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=40)
    image_tags: list[str] = Field(default_factory=list, max_length=40)
    enabled: bool = True


class WeatherTransitionsUpdate(BaseModel):
    target_weather_ids: list[str] = Field(default_factory=list, max_length=100)


class TimePhaseItem(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=1, le=100_000)
    description: str = Field(default="", max_length=2000)
    imagegen_description: str = Field(default="", max_length=4000)
    enabled: bool = True


class TimePhasesUpdate(BaseModel):
    phases: list[TimePhaseItem] = Field(min_length=1, max_length=24)


class TimePhaseOrderUpdate(BaseModel):
    phase_ids: list[str] = Field(min_length=1, max_length=24)


class AmbientPreferenceUpdate(BaseModel):
    enabled: bool = True
    master_volume: float = Field(default=1, ge=0, le=1)


class NoisePreferenceUpdate(BaseModel):
    enabled: bool = True
    master_volume: float = Field(default=1, ge=0, le=1)


class NoiseVariantUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    playback_rate: float = Field(default=1, ge=.25, le=4)
    default_gain: float = Field(default=1, ge=0, le=1)
    tags: list[str] = Field(default_factory=list, max_length=40)
    enabled: bool = True


class AmbientVariantCreate(BaseModel):
    source_path: str
    label: str = Field(min_length=1, max_length=160)
    playback_rate: float = Field(default=1, ge=.25, le=4)
    default_gain: float = Field(default=1, ge=0, le=1)
    tags: list[str] = Field(default_factory=list, max_length=40)
    enabled: bool = True


class AmbientAssignmentCreate(BaseModel):
    owner_type: Literal["weather", "time", "location", "action"]
    owner_id: str = Field(min_length=1, max_length=200)
    selector_type: Literal["default", "indoor", "outdoor", "isolated", "tag"] = "default"
    selector_value: str | None = None
    weather_id: str | None = None
    time_phase_id: str | None = None
    variant_id: str


class AmbientSoundSet(BaseModel):
    selector_type: Literal["default", "indoor", "outdoor", "isolated", "tag"] = "default"
    selector_value: str | None = None
    weather_id: str | None = None
    time_phase_id: str | None = None
    variant_ids: list[str] = Field(default_factory=list, max_length=200)


class AmbientSoundSetsUpdate(BaseModel):
    sets: list[AmbientSoundSet] = Field(default_factory=list, max_length=100)


class EnvironmentLocationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_location_id: str | None = None
    exposure: Literal["indoor", "outdoor", "isolated"] = "outdoor"
    description: str = Field(default="", max_length=4000)
    imagegen_description: str = Field(default="", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    image_tags: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool = True
    random_encounter: bool = False
    discovered: bool = True
    x: float | None = None
    y: float | None = None


class WeatherProposalDecision(BaseModel):
    action: Literal["approve", "reject"]


class SceneEnvironmentUpdate(BaseModel):
    focused_character_id: str
    player_action: str = "standing"
    weather_id: str | None = None


class LocationBackgroundCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)
    weather_id: str | None = None
    time_phase_id: str | None = None


class StatDefinitionCreate(BaseModel):
    stat_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    scope: Literal["character", "relationship"] = "character"
    default_value: float = 0
    minimum: float = 0
    maximum: float = 100
    minimum_stat_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
    )
    maximum_stat_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
    )
    color: str | None = Field(default=None, max_length=64)
    minimum_color: str | None = Field(default=None, max_length=64)
    maximum_color: str | None = Field(default=None, max_length=64)
    display_style: Literal["compact", "bar"] = "compact"
    integer_only: bool = True
    visibility: Literal["public", "private", "narrator"] = "public"

    @model_validator(mode="after")
    def validate_bound_shape(self) -> "StatDefinitionCreate":
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if self.minimum_stat_key == self.stat_key:
            raise ValueError("minimum_stat_key cannot reference itself")
        if self.maximum_stat_key == self.stat_key:
            raise ValueError("maximum_stat_key cannot reference itself")
        if not self.minimum_stat_key and not self.maximum_stat_key:
            if self.default_value < self.minimum or self.default_value > self.maximum:
                raise ValueError("default_value must be inside numeric bounds")
        return self


class StatAdjustmentRequest(BaseModel):
    entity_id: str | None = None
    relation_id: str | None = None
    stat_key: str
    operation: Literal["add", "subtract", "set", "multiply"] = "set"
    amount: float


class AbilityDefinitionCreate(BaseModel):
    ability_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    target_type: Literal["self", "character", "choice", "relationship", "location", "all", "party", "allies", "enemies", "nearby_enemies", "faction_members", "random"] = "self"
    requirements: dict[str, Any] = Field(default_factory=dict)
    costs: dict[str, float] = Field(default_factory=dict)
    effects: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    minigame_profile: dict[str, Any] = Field(default_factory=dict)

    @field_validator("minigame_profile")
    @classmethod
    def validate_minigame_profile(cls, profile: dict[str, Any]) -> dict[str, Any]:
        unknown = set(profile) - {"timed_attack", "bullethell_skill_ids"}
        if unknown:
            raise ValueError("unsupported ability minigame profile")
        attack = profile.get("timed_attack")
        if attack is not None:
            if not isinstance(attack, dict) or isinstance(attack.get("line_count"), bool) or not isinstance(attack.get("line_count"), int):
                raise ValueError("timed_attack profile requires an integer line_count")
            try:
                damage = float(attack["damage_per_line"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("timed_attack profile requires numeric damage_per_line") from exc
            if not 1 <= attack["line_count"] <= 8 or not 0 <= damage <= 1_000_000:
                raise ValueError("timed_attack profile values are outside valid ranges")
            profile = {**profile, "timed_attack": {"line_count": attack["line_count"], "damage_per_line": damage}}
        skill_ids = profile.get("bullethell_skill_ids")
        if skill_ids is not None:
            if not isinstance(skill_ids, list) or len(skill_ids) > 50 or any(not isinstance(value, str) for value in skill_ids):
                raise ValueError("bullethell_skill_ids must be a list of definition IDs")
            profile = {**profile, "bullethell_skill_ids": list(dict.fromkeys(skill_ids))}
        return profile

    @field_validator("costs")
    @classmethod
    def validate_costs(cls, costs: dict[str, float]) -> dict[str, float]:
        if any(value < 0 for value in costs.values()):
            raise ValueError("ability costs cannot be negative")
        return costs

    @field_validator("effects")
    @classmethod
    def validate_effects(cls, effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for effect in effects:
            if effect.get("duration_type") not in {None, "turns", "minutes"}:
                raise ValueError("effect duration_type must be turns or minutes")
            ActionEffect.model_validate(effect)
        return effects

    @field_validator("requirements")
    @classmethod
    def validate_requirements(cls, requirements: dict[str, Any]) -> dict[str, Any]:
        RequirementExpression.model_validate(requirements)
        return requirements


class WorldHeadUpdate(BaseModel):
    node_id: str | None = None


class ReviewDecision(BaseModel):
    action: Literal["approve", "reject_replan", "accept_reconciliation", "reject_regenerate"]
    mutations: list[dict[str, Any]] | None = None
    feedback: str = Field(default="", max_length=5000)
