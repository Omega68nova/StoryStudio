-- Phase 4: generic BatchGeneration / GenerationPlan foundation.
-- Additive only: legacy planning_* tables remain untouched.

CREATE TABLE generation_plans (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK(status IN (
      'draft','ready','running','awaiting_review',
      'completed','cancelled','failed'
    )),
  source_kind TEXT,
  source_id TEXT,
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_generation_plans_project
  ON generation_plans(project_id, updated_at);

CREATE TABLE generation_plan_tasks (
  id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES generation_plans(id) ON DELETE CASCADE,
  task_key TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  generator_kind TEXT NOT NULL
    CHECK(generator_kind IN ('text','image','deterministic')),
  target_kind TEXT NOT NULL,
  target_key TEXT,
  prompt_json TEXT NOT NULL DEFAULT '{}',
  settings_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN (
      'pending','blocked','ready','queued','running',
      'generated','approved','committed','failed',
      'cancelled','stale'
    )),
  revision INTEGER NOT NULL DEFAULT 1,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(plan_id, task_key)
);

CREATE INDEX idx_generation_plan_tasks_plan
  ON generation_plan_tasks(plan_id, status);

CREATE TABLE generation_task_dependencies (
  task_id TEXT NOT NULL
    REFERENCES generation_plan_tasks(id) ON DELETE CASCADE,
  depends_on_task_id TEXT NOT NULL
    REFERENCES generation_plan_tasks(id) ON DELETE CASCADE,
  required_state TEXT NOT NULL DEFAULT 'generated'
    CHECK(required_state IN ('generated','approved','committed')),
  PRIMARY KEY(task_id, depends_on_task_id),
  CHECK(task_id <> depends_on_task_id)
);

CREATE INDEX idx_generation_task_dependencies_parent
  ON generation_task_dependencies(depends_on_task_id);
