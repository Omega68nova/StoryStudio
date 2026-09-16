CREATE TABLE npc_interventions (
  id TEXT PRIMARY KEY,
  story_node_id TEXT NOT NULL REFERENCES story_nodes(id) ON DELETE CASCADE,
  npc_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  dialogue TEXT NOT NULL DEFAULT '',
  attempted_action TEXT NOT NULL,
  cited_fact_ids_json TEXT NOT NULL DEFAULT '[]',
  ability_key TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_npc_interventions_node ON npc_interventions(story_node_id);

CREATE TABLE entity_outfits (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  equipment_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(entity_id, name)
);

CREATE TABLE entity_media_assets (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  outfit_id TEXT REFERENCES entity_outfits(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('portrait', 'full_body', 'location')),
  source TEXT NOT NULL CHECK(source IN ('upload', 'generated', 'suggested')),
  status TEXT NOT NULL,
  file_path TEXT,
  mime_type TEXT,
  original_name TEXT,
  prompt TEXT NOT NULL DEFAULT '',
  negative_prompt TEXT NOT NULL DEFAULT '',
  featured INTEGER NOT NULL DEFAULT 1,
  source_story_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_entity_media_featured ON entity_media_assets(entity_id, kind, COALESCE(outfit_id, ''), featured) WHERE featured = 1;

CREATE TABLE scene_appearances (
  id TEXT PRIMARY KEY,
  story_node_id TEXT NOT NULL REFERENCES story_nodes(id) ON DELETE CASCADE,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  outfit_id TEXT REFERENCES entity_outfits(id) ON DELETE SET NULL,
  encounter_kind TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(story_node_id, entity_id)
);

CREATE TABLE music_themes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE music_tracks (
  id TEXT PRIMARY KEY,
  theme_id TEXT NOT NULL REFERENCES music_themes(id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  file_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_music_tracks_hash ON music_tracks(sha256);
CREATE TABLE project_music_settings (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  mode TEXT NOT NULL DEFAULT 'disabled' CHECK(mode IN ('disabled', 'player_managed', 'ai_managed')),
  manual_theme_id TEXT REFERENCES music_themes(id) ON DELETE RESTRICT,
  volume REAL NOT NULL DEFAULT 0.7 CHECK(volume >= 0 AND volume <= 1)
);
CREATE TABLE project_music_themes (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  theme_id TEXT NOT NULL REFERENCES music_themes(id) ON DELETE RESTRICT,
  PRIMARY KEY(project_id, theme_id)
);

CREATE TABLE stat_definitions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  stat_key TEXT NOT NULL,
  label TEXT NOT NULL,
  scope TEXT NOT NULL CHECK(scope IN ('character', 'relationship')),
  default_value REAL NOT NULL DEFAULT 0,
  minimum REAL NOT NULL DEFAULT 0,
  maximum REAL NOT NULL DEFAULT 100,
  integer_only INTEGER NOT NULL DEFAULT 1,
  visibility TEXT NOT NULL DEFAULT 'public',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, stat_key)
);
CREATE TABLE ability_definitions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ability_key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  target_type TEXT NOT NULL DEFAULT 'self' CHECK(target_type IN ('self', 'character', 'relationship')),
  requirements_json TEXT NOT NULL DEFAULT '{}',
  costs_json TEXT NOT NULL DEFAULT '{}',
  effects_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, ability_key)
);

CREATE TRIGGER stat_definitions_bounds_insert BEFORE INSERT ON stat_definitions
WHEN NEW.minimum > NEW.maximum OR NEW.default_value < NEW.minimum OR NEW.default_value > NEW.maximum
BEGIN SELECT RAISE(ABORT, 'invalid stat bounds'); END;
CREATE TRIGGER stat_definitions_bounds_update BEFORE UPDATE ON stat_definitions
WHEN NEW.minimum > NEW.maximum OR NEW.default_value < NEW.minimum OR NEW.default_value > NEW.maximum
BEGIN SELECT RAISE(ABORT, 'invalid stat bounds'); END;
