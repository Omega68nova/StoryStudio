CREATE TABLE noise_variants (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_path TEXT NOT NULL,
  label TEXT NOT NULL,
  playback_rate REAL NOT NULL DEFAULT 1 CHECK(playback_rate >= .25 AND playback_rate <= 4),
  default_gain REAL NOT NULL DEFAULT 1 CHECK(default_gain >= 0 AND default_gain <= 1),
  tags_json TEXT NOT NULL DEFAULT '[]',
  enabled INTEGER NOT NULL DEFAULT 1,
  available INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, source_path, playback_rate, label)
);

CREATE INDEX idx_noise_variants_project
ON noise_variants(project_id, enabled, available);

CREATE TABLE user_noise_preferences (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 1,
  master_volume REAL NOT NULL DEFAULT 1 CHECK(master_volume >= 0 AND master_volume <= 1),
  updated_at TEXT NOT NULL
);
