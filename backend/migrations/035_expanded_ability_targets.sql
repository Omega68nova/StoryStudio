ALTER TABLE ability_definitions RENAME TO ability_definitions_legacy;

CREATE TABLE ability_definitions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ability_key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  target_type TEXT NOT NULL DEFAULT 'self' CHECK(target_type IN (
    'self','character','choice','relationship','location',
    'all','party','allies','enemies','nearby_enemies','faction_members','random'
  )),
  requirements_json TEXT NOT NULL DEFAULT '{}',
  costs_json TEXT NOT NULL DEFAULT '{}',
  effects_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  minigame_profile_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(project_id, ability_key)
);

INSERT INTO ability_definitions(
  id,project_id,ability_key,name,description,target_type,
  requirements_json,costs_json,effects_json,created_at,updated_at,
  minigame_profile_json
)
SELECT
  id,project_id,ability_key,name,description,target_type,
  requirements_json,costs_json,effects_json,created_at,updated_at,
  minigame_profile_json
FROM ability_definitions_legacy;

DROP TABLE ability_definitions_legacy;
