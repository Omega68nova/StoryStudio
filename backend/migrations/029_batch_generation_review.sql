-- Phase 4 Slice 3: review/history/commit lifecycle.

ALTER TABLE generation_plan_tasks ADD COLUMN approved_at TEXT;
ALTER TABLE generation_plan_tasks ADD COLUMN committed_at TEXT;
ALTER TABLE generation_plan_tasks ADD COLUMN review_note TEXT NOT NULL DEFAULT '';
ALTER TABLE generation_plan_tasks ADD COLUMN commit_metadata_json TEXT;

CREATE TABLE generation_task_revisions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES generation_plan_tasks(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT,
  prompt_json TEXT NOT NULL DEFAULT '{}',
  settings_json TEXT NOT NULL DEFAULT '{}',
  review_note TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(task_id, revision)
);

CREATE INDEX idx_generation_task_revisions_task
ON generation_task_revisions(task_id, revision DESC);
