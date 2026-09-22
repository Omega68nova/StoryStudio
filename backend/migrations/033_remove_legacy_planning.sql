-- Phase 4 Slice 10: remove the legacy Planning v2 state machine.
-- Any untouched legacy workshop is imported into GenerationPlan before tables
-- are rebuilt/dropped. Historical session ids survive only as inert text.

-- Existing bridge plans absorb the actual workshop settings before the source
-- session disappears.
UPDATE generation_plans
SET settings_json = json_set(
  json_patch(
    COALESCE(
      (SELECT ps.settings_json
       FROM planning_sessions ps
       WHERE ps.id = generation_plans.source_id),
      '{}'
    ),
    settings_json
  ),
  '$.legacy_session_id', source_id,
  '$.planning_schema_version', 3
)
WHERE source_kind = 'planning_session';

UPDATE generation_plans
SET source_kind = 'planning_workspace',
    source_id = NULL,
    legacy_import_complete = 1
WHERE source_kind = 'planning_session';

-- Import workshops that were never opened after the GenerationPlan migration.
INSERT INTO generation_plans(
  id, project_id, name, status, source_kind, source_id, settings_json,
  created_at, updated_at, legacy_import_complete
)
SELECT
  'legacy-planning-' || ps.id,
  ps.project_id,
  'Planning: ' || ps.project_id,
  CASE WHEN ps.status = 'completed' THEN 'completed' ELSE 'ready' END,
  'planning_workspace',
  NULL,
  json_set(
    ps.settings_json,
    '$.legacy_session_id', ps.id,
    '$.planning_schema_version', 3
  ),
  ps.created_at,
  ps.updated_at,
  1
FROM planning_sessions ps
WHERE NOT EXISTS (
  SELECT 1
  FROM generation_plans gp
  WHERE gp.source_kind = 'planning_workspace'
    AND json_extract(gp.settings_json, '$.legacy_session_id') = ps.id
);

-- Import missing legacy stages as GenerationPlan tasks.
INSERT INTO generation_plan_tasks(
  id, plan_id, task_key, label, generator_kind, target_kind, target_key,
  prompt_json, settings_json, status, revision, result_json, error,
  created_at, updated_at, source_kind, source_id
)
SELECT
  gp.id || ':stage:' || printf('%02d', s.stage_number),
  gp.id,
  'planning_' || printf('%02d', s.stage_number) || '_' || s.kind,
  CAST(s.stage_number AS TEXT) || '. ' || s.kind,
  CASE WHEN s.stage_number = 8 THEN 'deterministic' ELSE 'text' END,
  'planning_stage',
  CAST(s.stage_number AS TEXT),
  json_object(
    'planning_stage_number', s.stage_number,
    'human_prompt', COALESCE(s.human_prompt, '')
  ),
  json_object(
    'runtime_mode', 'planning',
    'parse_json', 1,
    'planning_workspace', 1
  ),
  CASE
    WHEN s.status IN ('approved','skipped') THEN 'committed'
    WHEN s.status = 'stale' THEN 'stale'
    WHEN s.status IN ('failed','cancelled') THEN s.status
    WHEN COALESCE(s.approved_json, s.draft_json) IS NOT NULL THEN 'generated'
    WHEN s.stage_number = 1 THEN 'ready'
    ELSE 'blocked'
  END,
  1,
  CASE
    WHEN COALESCE(s.approved_json, s.draft_json) IS NULL THEN NULL
    ELSE json_object('json', json(COALESCE(s.approved_json, s.draft_json)))
  END,
  s.validation_error,
  s.created_at,
  s.updated_at,
  'legacy_planning_stage',
  s.id
FROM planning_stages s
JOIN generation_plans gp
  ON gp.source_kind = 'planning_workspace'
 AND json_extract(gp.settings_json, '$.legacy_session_id') = s.session_id
WHERE NOT EXISTS (
  SELECT 1
  FROM generation_plan_tasks t
  WHERE t.plan_id = gp.id
    AND t.target_kind = 'planning_stage'
    AND t.target_key = CAST(s.stage_number AS TEXT)
);

-- Preserve historical publication receipts before planning_stages disappears.
UPDATE generation_plan_tasks
SET commit_metadata_json = json_object(
      'source', 'legacy_planning',
      'stage_number', CAST(target_key AS INTEGER),
      'transaction_id', (
        SELECT ps.transaction_id
        FROM planning_stages ps
        WHERE ps.id = generation_plan_tasks.source_id
      )
    ),
    committed_at = COALESCE(committed_at, updated_at)
WHERE status = 'committed'
  AND source_kind = 'legacy_planning_stage'
  AND commit_metadata_json IS NULL;

-- Normalize already-imported tasks away from bridge-only prompt/settings keys.
UPDATE generation_plan_tasks
SET prompt_json = json_remove(prompt_json, '$.planning_session_id'),
    settings_json = json_set(
      json_remove(settings_json, '$.planning_bridge'),
      '$.planning_workspace', 1
    )
WHERE plan_id IN (
  SELECT id FROM generation_plans WHERE source_kind = 'planning_workspace'
)
  AND target_kind = 'planning_stage';

-- Recreate sequential committed dependencies where absent.
INSERT OR IGNORE INTO generation_task_dependencies(
  task_id, depends_on_task_id, required_state
)
SELECT child.id, parent.id, 'committed'
FROM generation_plan_tasks child
JOIN generation_plan_tasks parent
  ON parent.plan_id = child.plan_id
 AND CAST(parent.target_key AS INTEGER) = CAST(child.target_key AS INTEGER) - 1
WHERE child.target_kind = 'planning_stage'
  AND parent.target_kind = 'planning_stage'
  AND CAST(child.target_key AS INTEGER) > 1;

-- GenerationPlan-owned canonical resource provenance.
CREATE TABLE generation_resource_keys (
  generation_plan_id TEXT NOT NULL
    REFERENCES generation_plans(id) ON DELETE CASCADE,
  resource_key TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  stage_number INTEGER NOT NULL,
  fingerprint TEXT NOT NULL DEFAULT '',
  legacy_session_id TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(generation_plan_id, resource_key)
);

INSERT OR REPLACE INTO generation_resource_keys(
  generation_plan_id, resource_key, resource_type, resource_id,
  stage_number, fingerprint, legacy_session_id, updated_at
)
SELECT
  COALESCE(
    prk.generation_plan_id,
    (
      SELECT gp.id
      FROM generation_plans gp
      WHERE gp.source_kind = 'planning_workspace'
        AND json_extract(gp.settings_json, '$.legacy_session_id') = prk.session_id
      LIMIT 1
    )
  ),
  prk.resource_key,
  prk.resource_type,
  prk.resource_id,
  prk.stage_number,
  prk.fingerprint,
  prk.session_id,
  prk.updated_at
FROM planning_resource_keys prk
WHERE COALESCE(
  prk.generation_plan_id,
  (
    SELECT gp.id
    FROM generation_plans gp
    WHERE gp.source_kind = 'planning_workspace'
      AND json_extract(gp.settings_json, '$.legacy_session_id') = prk.session_id
    LIMIT 1
  )
) IS NOT NULL;

CREATE INDEX idx_generation_resource_id
ON generation_resource_keys(resource_type, resource_id);

-- GenerationPlan-owned image preparation records.
CREATE TABLE generation_image_plans (
  id TEXT PRIMARY KEY,
  generation_plan_id TEXT NOT NULL
    REFERENCES generation_plans(id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  resource_key TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES world_entities(id) ON DELETE CASCADE,
  outfit_id TEXT REFERENCES entity_outfits(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK(kind IN ('portrait','full_body','location')),
  prompt TEXT NOT NULL DEFAULT '',
  negative_prompt TEXT NOT NULL DEFAULT '',
  workflow_preset_id TEXT REFERENCES workflow_presets(id) ON DELETE SET NULL,
  width INTEGER,
  height INTEGER,
  prompt_revision TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK(status IN ('draft','ready','queued','generated','failed')),
  media_asset_id TEXT REFERENCES entity_media_assets(id) ON DELETE SET NULL,
  generation_job_id TEXT REFERENCES generation_jobs(id) ON DELETE SET NULL,
  error TEXT,
  legacy_session_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(generation_plan_id, resource_key)
);

INSERT OR REPLACE INTO generation_image_plans(
  id, generation_plan_id, project_id, resource_key, entity_id, outfit_id,
  kind, prompt, negative_prompt, workflow_preset_id, width, height,
  prompt_revision, status, media_asset_id, generation_job_id, error,
  legacy_session_id, created_at, updated_at
)
SELECT
  pip.id,
  COALESCE(
    pip.generation_plan_id,
    (
      SELECT gp.id
      FROM generation_plans gp
      WHERE gp.source_kind = 'planning_workspace'
        AND json_extract(gp.settings_json, '$.legacy_session_id') = pip.session_id
      LIMIT 1
    )
  ),
  pip.project_id,
  pip.resource_key,
  pip.entity_id,
  pip.outfit_id,
  pip.kind,
  pip.prompt,
  pip.negative_prompt,
  pip.workflow_preset_id,
  pip.width,
  pip.height,
  pip.prompt_revision,
  pip.status,
  pip.media_asset_id,
  pip.generation_job_id,
  pip.error,
  pip.session_id,
  pip.created_at,
  pip.updated_at
FROM planning_image_plans pip
WHERE COALESCE(
  pip.generation_plan_id,
  (
    SELECT gp.id
    FROM generation_plans gp
    WHERE gp.source_kind = 'planning_workspace'
      AND json_extract(gp.settings_json, '$.legacy_session_id') = pip.session_id
    LIMIT 1
  )
) IS NOT NULL;

CREATE INDEX idx_generation_image_project
ON generation_image_plans(project_id, status);

-- Remove the last FK from canonical history to planning_sessions.
CREATE TABLE inactive_world_transactions_v2 (
  transaction_id TEXT PRIMARY KEY
    REFERENCES world_transactions(id) ON DELETE CASCADE,
  generation_plan_id TEXT
    REFERENCES generation_plans(id) ON DELETE SET NULL,
  legacy_session_id TEXT,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO inactive_world_transactions_v2(
  transaction_id, generation_plan_id, legacy_session_id, reason, created_at
)
SELECT
  transaction_id,
  COALESCE(
    generation_plan_id,
    (
      SELECT gp.id
      FROM generation_plans gp
      WHERE gp.source_kind = 'planning_workspace'
        AND json_extract(gp.settings_json, '$.legacy_session_id') =
            inactive_world_transactions.planning_session_id
      LIMIT 1
    )
  ),
  planning_session_id,
  reason,
  created_at
FROM inactive_world_transactions;

DROP TABLE inactive_world_transactions;
ALTER TABLE inactive_world_transactions_v2
RENAME TO inactive_world_transactions;

-- The parallel Planning v2 workflow is now obsolete.
DROP TABLE planning_approval_claims;
DROP TABLE planning_conflicts;
DROP TABLE planning_stage_revisions;
DROP TABLE planning_entity_keys;
DROP TABLE planning_image_plans;
DROP TABLE planning_resource_keys;
DROP TABLE planning_stages;
DROP TABLE planning_sessions;
