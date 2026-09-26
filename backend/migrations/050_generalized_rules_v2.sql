ALTER TABLE effect_definitions ADD COLUMN value_expression_json TEXT;

CREATE TABLE ability_rule_costs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  ability_key TEXT NOT NULL,
  position INTEGER NOT NULL,
  cost_kind TEXT NOT NULL CHECK(cost_kind IN ('stat')),
  owner_selector_json TEXT NOT NULL,
  stat_key TEXT NOT NULL,
  amount_expression_json TEXT NOT NULL,
  FOREIGN KEY(project_id, ability_key)
    REFERENCES ability_definitions(project_id, ability_key) ON DELETE CASCADE,
  FOREIGN KEY(project_id, stat_key)
    REFERENCES stat_definitions(project_id, stat_key) ON DELETE RESTRICT,
  UNIQUE(project_id, ability_key, position)
);

CREATE INDEX idx_ability_rule_costs_order
  ON ability_rule_costs(project_id, ability_key, position);
