-- Canonical stat/effect/ability rules. Complex legacy row conversion is
-- completed transactionally by Database._migrate_canonical_rules().

DROP TRIGGER IF EXISTS stat_definitions_bounds_insert;
DROP TRIGGER IF EXISTS stat_definitions_bounds_update;

ALTER TABLE stat_definitions RENAME TO stat_definitions_legacy_v2;
ALTER TABLE ability_definitions RENAME TO ability_definitions_legacy_v2;

CREATE TABLE stat_definitions (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  stat_key TEXT NOT NULL,
  label TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  default_value REAL NOT NULL DEFAULT 0,
  minimum REAL NOT NULL DEFAULT 0,
  maximum REAL NOT NULL DEFAULT 100,
  minimum_stat_key TEXT,
  maximum_stat_key TEXT,
  color TEXT,
  minimum_color TEXT,
  maximum_color TEXT,
  display_style TEXT NOT NULL DEFAULT 'compact' CHECK(display_style IN ('compact','bar')),
  integer_only INTEGER NOT NULL DEFAULT 1,
  visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','private','narrator')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(project_id, stat_key),
  CHECK(minimum <= maximum)
);

CREATE TABLE stat_definition_owner_kinds (
  project_id TEXT NOT NULL,
  stat_key TEXT NOT NULL,
  owner_kind TEXT NOT NULL CHECK(owner_kind IN (
    'character','item','location','faction','lore_system','fact','plot_beat','relationship'
  )),
  PRIMARY KEY(project_id, stat_key, owner_kind),
  FOREIGN KEY(project_id, stat_key)
    REFERENCES stat_definitions(project_id, stat_key) ON DELETE CASCADE
);

CREATE TABLE effect_definitions (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  effect_key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  target_stat_key TEXT NOT NULL,
  operation TEXT NOT NULL CHECK(operation IN ('add','subtract','set','multiply')),
  clock TEXT NOT NULL DEFAULT 'world_actions' CHECK(clock IN ('story_minutes','target_actions','world_actions')),
  duration INTEGER NOT NULL DEFAULT 0 CHECK(duration >= -1),
  tick_interval INTEGER NOT NULL DEFAULT 0 CHECK(tick_interval >= 0),
  evaluation_mode TEXT NOT NULL DEFAULT 'snapshot' CHECK(evaluation_mode IN ('snapshot','live')),
  stacking_policy TEXT NOT NULL DEFAULT 'replace' CHECK(stacking_policy IN ('replace','refresh','stack','independent')),
  max_stacks INTEGER NOT NULL DEFAULT 1 CHECK(max_stacks >= 1),
  visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','private','narrator')),
  icon TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(project_id, effect_key),
  FOREIGN KEY(project_id, target_stat_key)
    REFERENCES stat_definitions(project_id, stat_key) ON DELETE RESTRICT,
  CHECK(
    (duration = 0 AND tick_interval = 0) OR
    (duration > 0 AND (tick_interval = 0 OR tick_interval <= duration)) OR
    (duration = -1 AND tick_interval > 0)
  )
);

CREATE TABLE effect_formula_nodes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  effect_key TEXT NOT NULL,
  parent_id TEXT REFERENCES effect_formula_nodes(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  node_kind TEXT NOT NULL CHECK(node_kind IN (
    'constant','stat','add','subtract','multiply','divide','minimum','maximum','negate'
  )),
  constant_value REAL,
  participant TEXT CHECK(participant IN ('actor','source','target')),
  stat_key TEXT,
  FOREIGN KEY(project_id, effect_key)
    REFERENCES effect_definitions(project_id, effect_key) ON DELETE CASCADE,
  FOREIGN KEY(project_id, stat_key)
    REFERENCES stat_definitions(project_id, stat_key) ON DELETE RESTRICT,
  UNIQUE(project_id, effect_key, parent_id, position)
);

CREATE TABLE ability_definitions (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ability_key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  ability_kind TEXT NOT NULL DEFAULT 'active' CHECK(ability_kind IN ('active','passive')),
  target_type TEXT NOT NULL DEFAULT 'self' CHECK(target_type IN (
    'self','character','choice','relationship','location','all','party','allies',
    'enemies','nearby_enemies','faction_members','random'
  )),
  icon TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  timed_attack_line_count INTEGER,
  timed_attack_damage_per_line REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(project_id, ability_key)
);

CREATE TABLE ability_owner_kinds (
  project_id TEXT NOT NULL,
  ability_key TEXT NOT NULL,
  owner_kind TEXT NOT NULL CHECK(owner_kind IN ('character','item')),
  PRIMARY KEY(project_id, ability_key, owner_kind),
  FOREIGN KEY(project_id, ability_key)
    REFERENCES ability_definitions(project_id, ability_key) ON DELETE CASCADE
);

CREATE TABLE ability_requirement_nodes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  ability_key TEXT NOT NULL,
  parent_id TEXT REFERENCES ability_requirement_nodes(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  edge_kind TEXT NOT NULL DEFAULT 'child' CHECK(edge_kind IN ('child','not_child')),
  node_kind TEXT CHECK(node_kind IN (
    'and','or','not','compare','has_item','has_tag','relationship','location','time','weather','has_ability'
  )),
  target TEXT NOT NULL DEFAULT 'actor',
  stat_key TEXT,
  comparison TEXT,
  value_json TEXT,
  item_id TEXT,
  tag TEXT,
  relation TEXT,
  location_id TEXT,
  time_phase_id TEXT,
  weather_id TEXT,
  required_ability_key TEXT,
  FOREIGN KEY(project_id, ability_key)
    REFERENCES ability_definitions(project_id, ability_key) ON DELETE CASCADE,
  UNIQUE(project_id, ability_key, parent_id, edge_kind, position)
);

CREATE TABLE ability_costs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  ability_key TEXT NOT NULL,
  position INTEGER NOT NULL,
  cost_kind TEXT NOT NULL CHECK(cost_kind IN ('stat','consume_source','consume_fuel')),
  stat_key TEXT,
  item_id TEXT,
  amount REAL NOT NULL CHECK(amount > 0),
  FOREIGN KEY(project_id, ability_key)
    REFERENCES ability_definitions(project_id, ability_key) ON DELETE CASCADE,
  FOREIGN KEY(project_id, stat_key)
    REFERENCES stat_definitions(project_id, stat_key) ON DELETE RESTRICT,
  UNIQUE(project_id, ability_key, position)
);

CREATE TABLE ability_actions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  ability_key TEXT NOT NULL,
  position INTEGER NOT NULL,
  action_kind TEXT NOT NULL CHECK(action_kind IN (
    'apply_effect','move','create','remove','reveal_knowledge',
    'change_relationship','advance_time','play_noise'
  )),
  target TEXT NOT NULL DEFAULT 'target',
  effect_key TEXT,
  destination_id TEXT,
  entity_kind TEXT,
  entity_name TEXT,
  state_json TEXT,
  fact_id TEXT,
  relation TEXT,
  minutes INTEGER,
  noise_id TEXT,
  duration_override INTEGER,
  tick_override INTEGER,
  FOREIGN KEY(project_id, ability_key)
    REFERENCES ability_definitions(project_id, ability_key) ON DELETE CASCADE,
  FOREIGN KEY(project_id, effect_key)
    REFERENCES effect_definitions(project_id, effect_key) ON DELETE RESTRICT,
  UNIQUE(project_id, ability_key, position)
);

CREATE TABLE ability_passive_triggers (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  ability_key TEXT NOT NULL,
  trigger_kind TEXT NOT NULL CHECK(trigger_kind IN (
    'ability_used','stat_changed','damage','owner_action','movement','time_advanced'
  )),
  stat_key TEXT,
  FOREIGN KEY(project_id, ability_key)
    REFERENCES ability_definitions(project_id, ability_key) ON DELETE CASCADE,
  UNIQUE(project_id, ability_key, trigger_kind, stat_key)
);

CREATE TABLE ability_bullethell_skills (
  project_id TEXT NOT NULL,
  ability_key TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  PRIMARY KEY(project_id, ability_key, skill_id),
  FOREIGN KEY(project_id, ability_key)
    REFERENCES ability_definitions(project_id, ability_key) ON DELETE CASCADE
);

CREATE TABLE rule_migration_warnings (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  warning_kind TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  acknowledged INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_effect_formula_parent ON effect_formula_nodes(project_id,effect_key,parent_id,position);
CREATE INDEX idx_ability_actions_order ON ability_actions(project_id,ability_key,position);
CREATE INDEX idx_rule_warnings_project ON rule_migration_warnings(project_id,acknowledged,created_at);

CREATE TRIGGER stat_key_immutable BEFORE UPDATE OF stat_key ON stat_definitions
WHEN NEW.stat_key <> OLD.stat_key BEGIN SELECT RAISE(ABORT, 'stat_key is immutable'); END;
CREATE TRIGGER effect_key_immutable BEFORE UPDATE OF effect_key ON effect_definitions
WHEN NEW.effect_key <> OLD.effect_key BEGIN SELECT RAISE(ABORT, 'effect_key is immutable'); END;
CREATE TRIGGER ability_key_immutable BEFORE UPDATE OF ability_key ON ability_definitions
WHEN NEW.ability_key <> OLD.ability_key BEGIN SELECT RAISE(ABORT, 'ability_key is immutable'); END;
