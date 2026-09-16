CREATE TABLE project_minigame_configs (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  game_key TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,
  ai_description TEXT NOT NULL DEFAULT '',
  allowed_directions_json TEXT NOT NULL DEFAULT '["player_acts","acted_on"]',
  allowed_actions_json TEXT NOT NULL DEFAULT '["do"]',
  required_actor_tags_json TEXT NOT NULL DEFAULT '[]',
  forbidden_actor_tags_json TEXT NOT NULL DEFAULT '[]',
  required_target_tags_json TEXT NOT NULL DEFAULT '[]',
  forbidden_target_tags_json TEXT NOT NULL DEFAULT '[]',
  required_location_tags_json TEXT NOT NULL DEFAULT '[]',
  forbidden_location_tags_json TEXT NOT NULL DEFAULT '[]',
  min_difficulty INTEGER NOT NULL DEFAULT 1,
  max_difficulty INTEGER NOT NULL DEFAULT 10,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(project_id, game_key)
);

CREATE TABLE minigame_sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT REFERENCES generation_jobs(id) ON DELETE SET NULL,
  parent_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
  story_node_id TEXT REFERENCES story_nodes(id) ON DELETE SET NULL,
  game_key TEXT NOT NULL,
  game_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK(status IN ('awaiting_input','resolved','committed','cancelled')),
  invocation_json TEXT NOT NULL,
  result_json TEXT,
  partial_prose TEXT NOT NULL DEFAULT '',
  staged_mutations_json TEXT NOT NULL DEFAULT '[]',
  interventions_json TEXT NOT NULL DEFAULT '[]',
  suggestion_json TEXT,
  continuation_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  committed_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_minigame_sessions_project_status ON minigame_sessions(project_id, status, created_at);
CREATE UNIQUE INDEX idx_minigame_sessions_active_job ON minigame_sessions(job_id)
  WHERE job_id IS NOT NULL AND status IN ('awaiting_input','resolved');

INSERT INTO project_minigame_configs(project_id, game_key, enabled, ai_description, min_difficulty, max_difficulty, updated_at)
SELECT p.id, games.game_key, 0, games.description, games.min_difficulty, games.max_difficulty, p.updated_at
FROM projects p CROSS JOIN (
  SELECT 'roll_d20' game_key, 'A dramatic twenty-sided die challenge.' description, 1 min_difficulty, 19 max_difficulty
  UNION ALL SELECT 'roll_d6', 'A quick six-sided die challenge.', 1, 5
  UNION ALL SELECT 'flip_coin', 'A binary chance challenge where the player calls heads or tails.', 1, 1
  UNION ALL SELECT 'timing_hit', 'A timing challenge where the player hits a moving marker inside a target.', 1, 10
  UNION ALL SELECT 'key_mash', 'A four-second effort challenge where the player presses rapidly.', 1, 10
) games;
