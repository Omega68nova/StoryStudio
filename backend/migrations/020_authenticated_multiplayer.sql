CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  username_normalized TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','member')),
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE auth_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX idx_auth_sessions_user ON auth_sessions(user_id, expires_at);

CREATE TABLE user_project_access (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY(user_id, project_id)
);

ALTER TABLE story_nodes ADD COLUMN author_user_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE story_nodes ADD COLUMN author_name_snapshot TEXT;
ALTER TABLE generation_jobs ADD COLUMN requested_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE generation_jobs ADD COLUMN requester_name_snapshot TEXT;
ALTER TABLE generation_jobs ADD COLUMN partial_output TEXT NOT NULL DEFAULT '';

