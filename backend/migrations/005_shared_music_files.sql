-- A single managed audio file may be listed in more than one theme.
ALTER TABLE music_tracks RENAME TO music_tracks_unique_hash;

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

INSERT INTO music_tracks(id, theme_id, title, file_path, mime_type, sha256, position, created_at)
SELECT id, theme_id, title, file_path, mime_type, sha256, position, created_at
FROM music_tracks_unique_hash;

DROP TABLE music_tracks_unique_hash;
CREATE INDEX idx_music_tracks_hash ON music_tracks(sha256);
