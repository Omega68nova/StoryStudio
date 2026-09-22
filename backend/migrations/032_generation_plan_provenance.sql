-- Phase 4 Slice 9: GenerationPlan becomes canonical provenance owner.

ALTER TABLE planning_resource_keys
ADD COLUMN generation_plan_id TEXT REFERENCES generation_plans(id) ON DELETE CASCADE;

ALTER TABLE planning_image_plans
ADD COLUMN generation_plan_id TEXT REFERENCES generation_plans(id) ON DELETE CASCADE;

ALTER TABLE inactive_world_transactions
ADD COLUMN generation_plan_id TEXT REFERENCES generation_plans(id) ON DELETE SET NULL;

UPDATE planning_resource_keys
SET generation_plan_id = (
  SELECT gp.id FROM generation_plans gp
  WHERE gp.source_kind='planning_session'
    AND gp.source_id=planning_resource_keys.session_id
  LIMIT 1
)
WHERE generation_plan_id IS NULL;

UPDATE planning_image_plans
SET generation_plan_id = (
  SELECT gp.id FROM generation_plans gp
  WHERE gp.source_kind='planning_session'
    AND gp.source_id=planning_image_plans.session_id
  LIMIT 1
)
WHERE generation_plan_id IS NULL;

UPDATE inactive_world_transactions
SET generation_plan_id = (
  SELECT gp.id FROM generation_plans gp
  WHERE gp.source_kind='planning_session'
    AND gp.source_id=inactive_world_transactions.planning_session_id
  LIMIT 1
)
WHERE generation_plan_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_planning_resource_plan_key
ON planning_resource_keys(generation_plan_id, resource_key);

CREATE INDEX IF NOT EXISTS idx_planning_image_plan_status
ON planning_image_plans(generation_plan_id, status);
