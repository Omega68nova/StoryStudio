-- Phase 4 Slice 2 hotfix:
-- Expand generation_jobs.kind without rewriting child foreign-key targets.
PRAGMA foreign_keys = OFF;

CREATE TABLE generation_jobs_phase4 (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('story', 'image', 'planning', 'batch_generation')),
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  phase TEXT NOT NULL DEFAULT 'queued',
  progress_current REAL,
  progress_total REAL,
  progress_message TEXT,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  requested_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  requester_name_snapshot TEXT,
  partial_output TEXT NOT NULL DEFAULT ''
);

INSERT INTO generation_jobs_phase4(
  id, project_id, kind, status, payload_json, result_json, error,
  created_at, updated_at, phase, progress_current, progress_total,
  progress_message, metrics_json, requested_by_user_id,
  requester_name_snapshot, partial_output
)
SELECT
  id, project_id, kind, status, payload_json, result_json, error,
  created_at, updated_at, phase, progress_current, progress_total,
  progress_message, metrics_json, requested_by_user_id,
  requester_name_snapshot, partial_output
FROM generation_jobs;

DROP TABLE generation_jobs;
ALTER TABLE generation_jobs_phase4 RENAME TO generation_jobs;

CREATE INDEX idx_generation_jobs_status
  ON generation_jobs(status, created_at);

PRAGMA foreign_keys = ON;
