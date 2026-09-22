export type ProjectSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  active_node_id?: string | null;
};

export type BibleDocument = {
  id: string;
  project_id: string;
  kind: string;
  title: string;
  content: string;
  position: number;
};

export type StoryNode = {
  id: string;
  project_id: string;
  parent_id: string | null;
  role: "user" | "assistant";
  content: string;
  status: string;
  created_at: string;
  pov_character_id?: string | null;
  narration_mode?: "first_person" | "third_limited" | "third_omniscient";
  action_kind?: "story" | "say" | "do" | "guide" | "continue" | "manual_story";
  author_user_id?: string | null;
  author_name_snapshot?: string | null;
};

export type AuthUser = { id: string; username: string; role: "admin" | "member"; enabled?: boolean; project_ids?: string[] };
export type ActiveJob = {
  id: string; kind: string; status: string; phase?: string | null;
  requester_name_snapshot?: string | null; requested_by_user_id?: string | null;
  partial_output?: string; queue_position: number; action_type?: string | null;
  input_preview?: string; can_cancel: boolean;
};

export type ImageSuggestion = {
  id: string;
  story_node_id: string;
  title: string;
  prompt: string;
  negative_prompt: string;
  status: string;
  image_path: string | null;
  image_job_id?: string | null;
  image_job_status?: string | null;
  image_job_phase?: string | null;
  image_progress_current?: number | null;
  image_progress_total?: number | null;
  image_progress_message?: string | null;
};

export type Project = ProjectSummary & {
  bible_documents: BibleDocument[];
  story_nodes: StoryNode[];
  suggestions: ImageSuggestion[];
  npc_interventions: NpcIntervention[];
  scene_appearances: SceneAppearance[];
  trashed_story_nodes?: StoryNode[];
  story_settings: { default_generation_mode: "direct" | "low" | "smart"; response_max_tokens: number; ai_instructions?: string };
  permissions?: { admin: boolean; edit_bible: boolean; submit_story: boolean; edit_story: boolean; manage_context: boolean };
  active_jobs?: ActiveJob[];
  active_minigame?: MinigameSession | null;
  minigame_sessions?: MinigameSession[];
};

export type MinigameManifest = { key: string; version: number; name: string; group: "chance" | "cypher" | "reflex" | "strength" | "fishing" | "attack" | "take_attack"; renderer: "dice" | "coin" | "timing" | "key_mash" | "red_light" | "lockpicking" | "hex_circuit" | "circled_teeth" | "timed_attack" | "dodge_box"; sides?: number; min_difficulty: number; max_difficulty: number; description: string };
export type MinigameConfig = {
  project_id: string; game_key: string; enabled: boolean; ai_description: string;
  allowed_directions: Array<"player_acts" | "acted_on">; allowed_actions: Array<"story" | "say" | "do" | "guide" | "continue">;
  required_actor_tags: string[]; forbidden_actor_tags: string[]; required_target_tags: string[]; forbidden_target_tags: string[];
  required_location_tags: string[]; forbidden_location_tags: string[]; min_difficulty: number; max_difficulty: number;
  timer_policy: "never" | "ai_allowed" | "always"; fallback_attempts: number; allow_infinite_attempts: boolean;
  allow_teeth_override: boolean; min_teeth: number; max_teeth: number;
  allow_empty_slots_override: boolean; min_empty_slots: number; max_empty_slots: number;
  allow_time_override: boolean; min_time_seconds: number; max_time_seconds: number; allow_direction_reversal: boolean;
  min_attack_lines: number; max_attack_lines: number; min_attack_damage: number; max_attack_damage: number;
  dodge_control_mode: "pointer" | "keyboard"; min_fallback_hp: number; max_fallback_hp: number; min_enemy_attack: number; max_enemy_attack: number;
  manifest: MinigameManifest;
};
export type MinigameSession = {
  id: string; project_id: string; job_id: string | null; job_status?: string | null; parent_node_id: string | null; story_node_id: string | null;
  game_key: string; game_version: number; status: "awaiting_input" | "resolved" | "committed" | "cancelled";
  invocation: { game_key: string; actor_id: string; participant_id: string; target_id?: string | null; difficulty: number; challenge_text: string; direction: string; timed?: boolean; requested_overrides?: Record<string, number | boolean>; setup?: { target_start?: number; target_end?: number; traversal_ms?: number; duration_ms?: number; target?: number; lose_threshold_ms?: number; phases?: Array<{ color: "green" | "red"; duration_ms: number; warning_ms: number }>; sweet_center?: number; sweet_width?: number; pick_durability_ms?: number; attempt_limit?: number | null; attempt_source?: string; time_limit_ms?: number | null; masks?: number[]; rotations?: number[]; coordinates?: Array<[number, number]>; slot_count?: number; tooth_count?: number; empty_slot_count?: number; occupied_slots?: number[]; revolution_ms?: number; strike_limit?: number; hit_window_fraction?: number; initial_angle?: number; initial_direction?: number; reverse_on_success?: boolean; resolved_parameters?: Record<string, number>; lines?: Array<{ id: number; start_ms: number; traversal_ms: number }>; line_count?: number; damage_per_line?: number; parameter_source?: string; success_threshold?: number; control_mode?: "pointer" | "keyboard"; initial_hp?: number; hp_source?: string; enemy_attack?: number; attack_source?: string; attack?: Record<string, unknown>; mode?: Record<string, unknown>; skills?: Array<Record<string, unknown>>; hazards?: Array<Record<string, unknown>>; seed?: number } };
  result?: Record<string, unknown> | null; partial_prose: string;
  attempt_started_at?: string | null;
  active_on_branch?: boolean;
};

export type WorkflowMapping = { node_id: string; input_name?: string | null };
export type WorkflowMappings = {
  positive_prompt: WorkflowMapping;
  image_output: WorkflowMapping;
  transparent_image_output?: WorkflowMapping | null;
  negative_prompt?: WorkflowMapping | null;
  seed?: WorkflowMapping | null;
  width?: WorkflowMapping | null;
  height?: WorkflowMapping | null;
  steps?: WorkflowMapping | null;
  guidance?: WorkflowMapping | null;
  checkpoint?: WorkflowMapping | null;
};

export type WorkflowPreset = {
  id: string;
  name: string;
  graph: Record<string, unknown>;
  source_graph?: Record<string, unknown> | null;
  mappings: WorkflowMappings;
  validation_status: string;
  validation_error: string | null;
};

export type RuntimeSettings = {
  data_dir: string;
  llama_executable: string;
  storyteller_model_path: string;
  storyteller_model_id: string;
  llama_url: string;
  llama_extra_args: string[];
  comfy_command: string[];
  comfy_workdir: string;
  comfy_url: string;
  context_tokens: number;
  planning_context_tokens: number;
  memory_provider: "builtin" | "cognee";
};

export type LoreCard = {
  compact_text: string;
  visual_description: string;
  image_tags: string[];
  search_text: string;
};

export type WorldEntity = {
  id: string;
  kind: string;
  name: string;
  aliases: string[];
  tags: string[];
  state: Record<string, unknown>;
  card: LoreCard;
  reason?: string;
  stats?: Record<string, number>;
  active_effects?: Array<Record<string, unknown>>;
};

export type WorldProjection = {
  project_id: string;
  head_node_id: string | null;
  entities: Record<string, WorldEntity>;
  relations: Record<string, Record<string, unknown>>;
  elapsed_minutes: number;
  display_time: string | null;
  current_theme_id?: string | null;
  transactions: Array<Record<string, unknown>>;
};

export type EntityEditorDraft = {
  id?: string; kind: string; name: string; aliases: string[]; tags: string[];
  state: Record<string, unknown>; advancedState: string;
};
export type CharacterEditorDraft = EntityEditorDraft & { kind: "character" };
export type WorldRelationship = {
  id?: string; source_id: string; target_id: string; relation: string;
  bidirectional?: boolean; major?: boolean; blocked?: boolean; travel_minutes?: number;
  direction?: string; modes?: string[]; [key: string]: unknown;
};

export type PlanningScalePreset = "intimate" | "local" | "regional" | "global";
export type PlanningStageKind = "foundation" | "macro_world" | "detailed_locations" | "systems" | "cast" | "character_details" | "runtime_presentation" | "images";
export type PlanningStageStatus = "pending" | "ready" | "queued" | "generating" | "approved" | "skipped" | "stale" | "failed" | "cancelled";
export type PlanningResourceReference = { resource_key: string; resource_type: string; resource_id: string; stage_number: number; fingerprint: string };
export type PlanningDependencyImpact = { stage_number: number; changed_domains: string[]; affected_stages: Array<{ stage_number: number; kind: PlanningStageKind; status: PlanningStageStatus }> };
export type PlanningAssetPlan = { id: string; generation_plan_id: string; legacy_session_id?: string | null; resource_key: string; entity_id: string; outfit_id?: string | null; kind: "portrait" | "full_body" | "location"; prompt: string; negative_prompt: string; workflow_preset_id?: string | null; width?: number | null; height?: number | null; status: "draft" | "ready" | "queued" | "generated" | "failed"; media_asset_id?: string | null; generation_job_id?: string | null; error?: string | null };

export type PlanningStage = {
  id: string;
  stage_number: number;
  kind: PlanningStageKind;
  status: PlanningStageStatus;
  draft: Record<string, unknown> | null;
  approved: Record<string, unknown> | null;
  human_prompt: string;
  conflicts?: PlanningConflict[];
  legacy_link_state?: string;
  active_job_id?: string | null;
  raw_draft_text?: string | null;
  validation_error?: string | null;
  operation?: {
    id: string;
    status: string;
    phase?: string | null;
    progress_message?: string | null;
    progress_current?: number | null;
    progress_total?: number | null;
    error?: string | null;
    created_at?: string;
    updated_at?: string;
  } | null;
  dependency_snapshot?: Record<string, string>;
  published_domains?: Record<string, string>;
};

export type PlanningSession = {
  id: string;
  project_id: string;
  status: string;
  current_stage: number;
  schema_version: number;
  settings: { scale_preset: PlanningScalePreset; major_locations: number; minor_locations: number; rooms: number; characters: number; direction: string };
  stages: PlanningStage[];
  image_plans: PlanningAssetPlan[];
  recovery_warnings?: RecoveryWarning[];
};

export type RecoveryWarning = { code: string; message: string };
export type PlanningResolution = { action: "link" | "merge" | "rename" | "omit" | "keep_manual" | "overwrite" | "unlink"; entity_id?: string; new_name?: string };
export type PlanningConflict = { id: string; entity_key: string; proposed: Record<string, unknown>; candidates: Array<{ id: string; kind: string; name: string }>; recommended_resolution?: PlanningResolution | null; resolution?: PlanningResolution | null };
export type DataSummary = { counts: Record<string, number>; managed_disk_bytes: number; active_jobs: Array<Record<string, unknown>>; trashed_story_nodes: number; orphan_files: string[]; dangling_fts_rows: number; file_failures: Array<{ path: string; error: string }> };
export type DeletionImpact = { object_id?: string; project_id?: string; entity_id?: string; session_id?: string; name?: string; confirmation: string; counts: Record<string, number>; warnings?: string[] };

export type PendingReview = {
  id: string;
  job_id: string;
  story_node_id: string | null;
  phase: "pre_prose" | "reconciliation";
  reason: string;
  mutations: Array<Record<string, unknown>>;
};

export type AppEvent = { type: string; payload: Record<string, unknown> };

export type NpcIntervention = { id: string; story_node_id: string; npc_id: string; dialogue: string; attempted_action: string; ability_key?: string | null };
export type SceneAppearance = { id: string; story_node_id: string; entity_id: string; outfit_id?: string | null; encounter_kind: string };
export type Outfit = { id: string; entity_id: string; name: string; description: string; equipment: string[] };
export type MediaAsset = { id: string; entity_id: string; outfit_id?: string | null; kind: "portrait" | "full_body" | "location"; status: string; file_path?: string | null; prompt: string; negative_prompt: string };
export type MusicTrack = { id: string; title: string; file_path: string; mime_type: string; position: number };
export type MusicTheme = { id: string; name: string; description: string; playback_mode: "shuffle" | "repeat_one" | "in_order"; tracks: MusicTrack[] };
export type ProjectMusic = { project_id: string; mode: "disabled" | "player_managed" | "ai_managed"; manual_theme_id: string | null; current_theme_id: string | null; shared_theme_id?: string | null; current_track_id?: string | null; playback_revision?: number; playback_updated_by?: string | null; volume: number; enabled_theme_ids: string[] };
export type WeatherDefinition = { id: string; name: string; description: string; imagegen_description: string; tags: string[]; image_tags: string[]; enabled: boolean; transition_ids: string[] };
export type TimePhase = { id: string; name: string; duration_minutes: number; description: string; imagegen_description: string; position: number; enabled: boolean };
export type AmbientVariant = { id: string; source_path: string; url: string; label: string; playback_rate: number; default_gain: number; tags: string[]; enabled: boolean; available: boolean; derived: boolean };
export type AmbientSelector = "default" | "indoor" | "outdoor" | "isolated" | "tag";
export type AmbientAssignment = { id: string; owner_type: "weather" | "time" | "location" | "action"; owner_id: string; selector_type: AmbientSelector; selector_value?: string | null; weather_id?: string | null; time_phase_id?: string | null; variant_id: string };
export type AmbientSoundSet = { selector_type: AmbientSelector; selector_value?: string | null; weather_id?: string | null; time_phase_id?: string | null; variant_ids: string[] };
export type EnvironmentLocation = { id?: string; name: string; parent_location_id: string | null; exposure: "indoor" | "outdoor" | "isolated"; description: string; imagegen_description: string; tags: string[]; image_tags: string[]; enabled: boolean; random_encounter: boolean; discovered: boolean; x: number | null; y: number | null };
export type EnvironmentSettings = { project_id: string; enabled: boolean; ai_create_locations: boolean; ai_propose_weather: boolean; auto_generate_backgrounds: boolean; background_workflow_id: string | null; initial_weather_id: string; revision: number; weather: WeatherDefinition[]; time_phases: TimePhase[] };
export type SceneEnvironment = { enabled: boolean; revision: number; focused_character?: { id: string; name: string } | null; player_action?: string; location?: { id: string; name: string; description: string; tags: string[]; exposure: "indoor" | "outdoor" | "isolated"; parent_location_id?: string | null } | null; location_ancestry?: Array<{ id: string; name: string }>; weather?: WeatherDefinition | null; time_phase?: TimePhase | null; allowed_next_weather?: Array<{ id: string; name: string }>; background?: { id: string; url: string } | null; ambient: AmbientVariant[] };
export type LocationMapLayer = { parent?: { id: string; name: string; parent_id?: string | null } | null; breadcrumbs: Array<{ id: string; name: string }>; locations: Array<{ id: string; name: string; x: number; y: number; has_children: boolean; exposure: string; enabled: boolean; effectively_enabled: boolean }>; routes: Array<{ id: string; source_id: string; target_id: string }> };
export type UserAmbientPreferences = { enabled: boolean; master_volume: number };
export type StatDefinition = { id: string; stat_key: string; label: string; scope: "character" | "relationship"; default_value: number; minimum: number; maximum: number; integer_only: number; visibility: string };
export type AbilityDefinition = { id: string; ability_key: string; name: string; description: string; target_type: "self" | "character" | "relationship"; requirements?: Record<string, unknown>; costs: Record<string, number>; effects: Array<Record<string, unknown>>; minigame_profile?: { timed_attack?: { line_count: number; damage_per_line: number }; bullethell_skill_ids?: string[] } };

export type GenerationTaskStatus =
  | "pending" | "blocked" | "ready" | "queued" | "running"
  | "generated" | "approved" | "committed"
  | "failed" | "cancelled" | "stale";

export type GenerationPlanTask = {
  id: string;
  plan_id: string;
  task_key: string;
  label: string;
  generator_kind: "text" | "image" | "deterministic";
  target_kind: string;
  target_key?: string | null;
  prompt: Record<string, unknown>;
  settings: Record<string, unknown>;
  status: GenerationTaskStatus;
  revision: number;
  result?: Record<string, unknown> | null;
  error?: string | null;
  active_job_id?: string | null;
  approved_at?: string | null;
  committed_at?: string | null;
  review_note?: string;
  commit_metadata?: Record<string, unknown> | null;
  source_kind?: string | null;
  source_id?: string | null;
  dependencies: Array<{ task_key: string; required_state: "generated" | "approved" | "committed" }>;
};

export type GenerationPlan = {
  id: string;
  project_id: string;
  name: string;
  status: "draft" | "ready" | "running" | "awaiting_review" | "completed" | "cancelled" | "failed";
  source_kind?: string | null;
  source_id?: string | null;
  settings: Record<string, unknown>;
  tasks: GenerationPlanTask[];
  ready_task_keys: string[];
};
