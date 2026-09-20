-- Version 2 intentionally discards legacy workshop metadata while preserving
-- every canonical record and world transaction produced by those workshops.
UPDATE generation_jobs SET status='interrupted', error='Legacy planning workshop was replaced', updated_at=CURRENT_TIMESTAMP
WHERE kind='planning' AND status IN ('queued','running','switching');
DELETE FROM planning_sessions;

ALTER TABLE planning_sessions ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 2;
ALTER TABLE planning_stages ADD COLUMN dependency_snapshot_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE planning_stages ADD COLUMN published_domains_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE planning_stages ADD COLUMN replaces_revision_hash TEXT;

CREATE TABLE project_story_defaults (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  narration_mode TEXT NOT NULL DEFAULT 'third_limited' CHECK(narration_mode IN ('first_person','third_limited','third_omniscient')),
  pov_strategy TEXT NOT NULL DEFAULT 'first_player' CHECK(pov_strategy IN ('first_player','selected_character','none')),
  pov_character_id TEXT REFERENCES world_entities(id) ON DELETE SET NULL,
  updated_at TEXT NOT NULL
);
INSERT INTO project_story_defaults(project_id,updated_at) SELECT id,updated_at FROM projects;

CREATE TABLE planning_resource_keys (
  session_id TEXT NOT NULL REFERENCES planning_sessions(id) ON DELETE CASCADE,
  resource_key TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  stage_number INTEGER NOT NULL,
  fingerprint TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY(session_id,resource_key)
);
CREATE INDEX idx_planning_resource_id ON planning_resource_keys(resource_type,resource_id);

CREATE TABLE planning_image_plans (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES planning_sessions(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  resource_key TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  outfit_id TEXT REFERENCES entity_outfits(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK(kind IN ('portrait','full_body','location')),
  prompt TEXT NOT NULL DEFAULT '',
  negative_prompt TEXT NOT NULL DEFAULT '',
  workflow_preset_id TEXT REFERENCES workflow_presets(id) ON DELETE SET NULL,
  width INTEGER,
  height INTEGER,
  prompt_revision TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','ready','queued','generated','failed')),
  media_asset_id TEXT REFERENCES entity_media_assets(id) ON DELETE SET NULL,
  generation_job_id TEXT REFERENCES generation_jobs(id) ON DELETE SET NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(session_id,resource_key)
);
CREATE INDEX idx_planning_image_project ON planning_image_plans(project_id,status);

CREATE TABLE character_routines (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  character_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  location_id TEXT REFERENCES world_entities(id) ON DELETE SET NULL,
  time_phase_id TEXT REFERENCES time_phases(id) ON DELETE SET NULL,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_character_routines_character ON character_routines(character_id);
