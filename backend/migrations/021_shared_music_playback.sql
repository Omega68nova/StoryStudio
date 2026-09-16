CREATE TABLE project_music_playback (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  theme_id TEXT REFERENCES music_themes(id) ON DELETE SET NULL,
  track_id TEXT REFERENCES music_tracks(id) ON DELETE SET NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  updated_by_name_snapshot TEXT,
  updated_at TEXT NOT NULL
);
