ALTER TABLE projects ADD COLUMN active_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL;
ALTER TABLE story_nodes ADD COLUMN pov_character_id TEXT;
ALTER TABLE story_nodes ADD COLUMN narration_mode TEXT NOT NULL DEFAULT 'third_limited';

ALTER TABLE generation_jobs RENAME TO generation_jobs_v1;
CREATE TABLE generation_jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('story', 'image', 'planning')),
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
INSERT INTO generation_jobs SELECT * FROM generation_jobs_v1;
DROP TABLE generation_jobs_v1;
CREATE INDEX idx_generation_jobs_status ON generation_jobs(status, created_at);

CREATE TABLE world_entities (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  tags_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX idx_world_entities_project_kind ON world_entities(project_id, kind);

CREATE TABLE world_transactions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  story_node_id TEXT REFERENCES story_nodes(id) ON DELETE CASCADE,
  parent_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
  branch_sequence INTEGER NOT NULL,
  elapsed_minutes INTEGER NOT NULL DEFAULT 0,
  display_time TEXT,
  provenance TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('committed', 'pending', 'rejected')),
  summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX idx_world_transactions_project_node ON world_transactions(project_id, story_node_id);

CREATE TABLE world_events (
  id TEXT PRIMARY KEY,
  transaction_id TEXT NOT NULL REFERENCES world_transactions(id) ON DELETE CASCADE,
  entity_id TEXT REFERENCES world_entities(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(transaction_id, ordinal)
);
CREATE INDEX idx_world_events_entity ON world_events(entity_id, created_at);

CREATE TABLE lore_card_versions (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  transaction_id TEXT NOT NULL REFERENCES world_transactions(id) ON DELETE CASCADE,
  state_json TEXT NOT NULL,
  compact_text TEXT NOT NULL,
  visual_description TEXT NOT NULL DEFAULT '',
  image_tags_json TEXT NOT NULL DEFAULT '[]',
  search_text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(entity_id, transaction_id)
);
CREATE INDEX idx_lore_cards_entity ON lore_card_versions(entity_id, created_at);
CREATE VIRTUAL TABLE lore_card_search USING fts5(
  entity_id UNINDEXED,
  project_id UNINDEXED,
  version_id UNINDEXED,
  search_text,
  tokenize = 'unicode61'
);

CREATE TABLE world_projection_cache (
  cache_key TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  head_node_id TEXT REFERENCES story_nodes(id) ON DELETE CASCADE,
  projection_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE planning_sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  settings_json TEXT NOT NULL,
  current_stage INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE planning_stages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES planning_sessions(id) ON DELETE CASCADE,
  stage_number INTEGER NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  draft_json TEXT,
  approved_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(session_id, stage_number)
);

CREATE TABLE planning_entity_keys (
  session_id TEXT NOT NULL REFERENCES planning_sessions(id) ON DELETE CASCADE,
  entity_key TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  PRIMARY KEY(session_id, entity_key)
);

CREATE TABLE pending_reviews (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
  story_node_id TEXT REFERENCES story_nodes(id) ON DELETE CASCADE,
  phase TEXT NOT NULL CHECK(phase IN ('pre_prose', 'reconciliation')),
  status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
  mutations_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_pending_reviews_job ON pending_reviews(job_id, status);

CREATE TABLE memory_sync_state (
  provider TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL REFERENCES lore_card_versions(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  error TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(provider, project_id, entity_id)
);

ALTER TABLE runtime_settings ADD COLUMN memory_provider TEXT NOT NULL DEFAULT 'builtin';
