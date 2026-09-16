ALTER TABLE generation_jobs ADD COLUMN phase TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE generation_jobs ADD COLUMN progress_current REAL;
ALTER TABLE generation_jobs ADD COLUMN progress_total REAL;
ALTER TABLE generation_jobs ADD COLUMN progress_message TEXT;

ALTER TABLE story_nodes ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0;
CREATE TABLE story_node_revisions (
  id TEXT PRIMARY KEY,
  story_node_id TEXT NOT NULL REFERENCES story_nodes(id) ON DELETE CASCADE,
  previous_content TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

ALTER TABLE planning_stages ADD COLUMN active_job_id TEXT REFERENCES generation_jobs(id) ON DELETE SET NULL;
ALTER TABLE planning_stages ADD COLUMN transaction_id TEXT REFERENCES world_transactions(id) ON DELETE SET NULL;
CREATE TABLE planning_stage_revisions (
  id TEXT PRIMARY KEY,
  stage_id TEXT NOT NULL REFERENCES planning_stages(id) ON DELETE CASCADE,
  job_id TEXT REFERENCES generation_jobs(id) ON DELETE SET NULL,
  prompt TEXT NOT NULL DEFAULT '',
  draft_json TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_planning_revisions_stage ON planning_stage_revisions(stage_id, created_at);
