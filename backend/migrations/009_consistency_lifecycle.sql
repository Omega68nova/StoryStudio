ALTER TABLE planning_sessions ADD COLUMN recovery_warnings_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE planning_stages ADD COLUMN approved_revision_hash TEXT;
ALTER TABLE planning_stages ADD COLUMN legacy_link_state TEXT NOT NULL DEFAULT 'none';
ALTER TABLE planning_entity_keys ADD COLUMN stage_number INTEGER NOT NULL DEFAULT 0;

CREATE TABLE inactive_world_transactions (
  transaction_id TEXT PRIMARY KEY REFERENCES world_transactions(id) ON DELETE CASCADE,
  planning_session_id TEXT REFERENCES planning_sessions(id) ON DELETE SET NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE planning_conflicts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES planning_sessions(id) ON DELETE CASCADE,
  stage_id TEXT NOT NULL REFERENCES planning_stages(id) ON DELETE CASCADE,
  entity_key TEXT NOT NULL,
  proposed_json TEXT NOT NULL,
  candidates_json TEXT NOT NULL,
  resolution_json TEXT,
  status TEXT NOT NULL DEFAULT 'unresolved',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(stage_id, entity_key)
);

CREATE TABLE planning_approval_claims (
  stage_id TEXT PRIMARY KEY REFERENCES planning_stages(id) ON DELETE CASCADE,
  revision_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE managed_file_failures (
  path TEXT PRIMARY KEY,
  error TEXT NOT NULL,
  last_attempt_at TEXT NOT NULL
);

-- Preserve late legacy output before canonicalizing the stage status.
INSERT INTO planning_stage_revisions(id, stage_id, prompt, draft_json, status, created_at, updated_at)
SELECT lower(hex(randomblob(16))), id, COALESCE(human_prompt, ''), draft_json, 'late_legacy_draft', updated_at, updated_at
FROM planning_stages
WHERE approved_json IS NOT NULL AND draft_json IS NOT NULL AND draft_json != approved_json AND status != 'approved';

UPDATE planning_stages SET status = 'approved', active_job_id = NULL
WHERE approved_json IS NOT NULL;
UPDATE planning_stages SET status = 'ready'
WHERE status = 'draft' AND approved_json IS NULL;
UPDATE planning_stages SET status = 'cancelled', active_job_id = NULL
WHERE status IN ('queued', 'generating') AND approved_json IS NULL;
UPDATE planning_stages SET status = 'pending'
WHERE status NOT IN ('pending', 'queued', 'generating', 'ready', 'approved', 'failed', 'cancelled');
