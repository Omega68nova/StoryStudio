CREATE TABLE project_environment_settings (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 1,
  ai_create_locations INTEGER NOT NULL DEFAULT 0,
  ai_propose_weather INTEGER NOT NULL DEFAULT 0,
  auto_generate_backgrounds INTEGER NOT NULL DEFAULT 0,
  background_workflow_id TEXT REFERENCES workflow_presets(id) ON DELETE SET NULL,
  initial_weather_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE weather_definitions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL COLLATE NOCASE,
  description TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  image_tags_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, name)
);
CREATE TABLE weather_transitions (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_weather_id TEXT NOT NULL REFERENCES weather_definitions(id) ON DELETE CASCADE,
  target_weather_id TEXT NOT NULL REFERENCES weather_definitions(id) ON DELETE CASCADE,
  PRIMARY KEY(project_id, source_weather_id, target_weather_id)
);
CREATE TABLE time_phases (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
  position INTEGER NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  UNIQUE(project_id, position)
);
CREATE TABLE weather_proposals (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  image_tags_json TEXT NOT NULL DEFAULT '[]',
  transitions_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
  source_story_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_weather_proposal_pending ON weather_proposals(project_id, name COLLATE NOCASE) WHERE status='pending';

CREATE TABLE ambient_variants (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_path TEXT NOT NULL,
  label TEXT NOT NULL,
  playback_rate REAL NOT NULL DEFAULT 1 CHECK(playback_rate >= .25 AND playback_rate <= 4),
  default_gain REAL NOT NULL DEFAULT 1 CHECK(default_gain >= 0 AND default_gain <= 1),
  tags_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  available INTEGER NOT NULL DEFAULT 1,
  derived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, source_path, playback_rate, label)
);
CREATE TABLE ambient_assignments (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  owner_type TEXT NOT NULL CHECK(owner_type IN ('weather','time','location','action')),
  owner_id TEXT NOT NULL,
  selector_type TEXT NOT NULL DEFAULT 'default' CHECK(selector_type IN ('default','indoor','outdoor','tag')),
  selector_value TEXT,
  weather_id TEXT REFERENCES weather_definitions(id) ON DELETE CASCADE,
  time_phase_id TEXT REFERENCES time_phases(id) ON DELETE CASCADE,
  variant_id TEXT NOT NULL REFERENCES ambient_variants(id) ON DELETE CASCADE
);
CREATE INDEX idx_ambient_assignments_project ON ambient_assignments(project_id, owner_type, owner_id);
CREATE TABLE user_ambient_preferences (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 1,
  master_volume REAL NOT NULL DEFAULT 1 CHECK(master_volume >= 0 AND master_volume <= 1),
  updated_at TEXT NOT NULL
);
CREATE TABLE location_backgrounds (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  location_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  media_asset_id TEXT NOT NULL UNIQUE REFERENCES entity_media_assets(id) ON DELETE CASCADE,
  weather_id TEXT REFERENCES weather_definitions(id) ON DELETE CASCADE,
  time_phase_id TEXT REFERENCES time_phases(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

INSERT INTO project_environment_settings(project_id, enabled, initial_weather_id, updated_at)
SELECT id, 1, 'sunny-' || id, updated_at FROM projects;
INSERT INTO weather_definitions(id, project_id, name, description, created_at, updated_at)
SELECT 'sunny-' || id, id, 'Sunny', 'Clear, neutral weather with no environmental effects.', created_at, updated_at FROM projects;
INSERT INTO time_phases(id, project_id, name, duration_minutes, position)
SELECT 'morning-' || id,id,'Morning',180,0 FROM projects UNION ALL
SELECT 'day-' || id,id,'Day',180,1 FROM projects UNION ALL
SELECT 'noon-' || id,id,'Noon',120,2 FROM projects UNION ALL
SELECT 'afternoon-' || id,id,'Afternoon',360,3 FROM projects UNION ALL
SELECT 'night-' || id,id,'Night',600,4 FROM projects;
INSERT INTO location_backgrounds(id,project_id,location_id,media_asset_id,position,created_at)
SELECT 'legacy-bg-' || id,project_id,entity_id,id,0,created_at FROM entity_media_assets WHERE kind='location' AND featured=1;
