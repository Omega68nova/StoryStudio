ALTER TABLE generation_plan_tasks ADD COLUMN source_kind TEXT;
ALTER TABLE generation_plan_tasks ADD COLUMN source_id TEXT;
CREATE INDEX idx_generation_plan_tasks_source
ON generation_plan_tasks(source_kind, source_id);
