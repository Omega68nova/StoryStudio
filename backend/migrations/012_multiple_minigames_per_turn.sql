DROP INDEX IF EXISTS idx_minigame_sessions_active_job;
CREATE UNIQUE INDEX idx_minigame_sessions_awaiting_job ON minigame_sessions(job_id)
  WHERE job_id IS NOT NULL AND status = 'awaiting_input';
