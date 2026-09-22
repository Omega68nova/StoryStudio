ALTER TABLE generation_plan_tasks
ADD COLUMN active_job_id TEXT REFERENCES generation_jobs(id) ON DELETE SET NULL;

CREATE INDEX idx_generation_plan_tasks_active_job
ON generation_plan_tasks(active_job_id);
