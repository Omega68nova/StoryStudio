CREATE TABLE project_story_settings (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  default_generation_mode TEXT NOT NULL DEFAULT 'low' CHECK(default_generation_mode IN ('direct','low','smart')),
  response_max_tokens INTEGER NOT NULL DEFAULT 300 CHECK(response_max_tokens BETWEEN 64 AND 1400),
  updated_at TEXT NOT NULL
);

INSERT INTO project_story_settings(project_id, default_generation_mode, response_max_tokens, updated_at)
SELECT id, 'low', 300, updated_at FROM projects;

ALTER TABLE generation_jobs ADD COLUMN metrics_json TEXT NOT NULL DEFAULT '{}';
