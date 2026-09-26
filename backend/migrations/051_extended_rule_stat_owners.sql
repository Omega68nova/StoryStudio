ALTER TABLE stat_definition_owner_kinds RENAME TO stat_definition_owner_kinds_v2_old;

CREATE TABLE stat_definition_owner_kinds (
  project_id TEXT NOT NULL,
  stat_key TEXT NOT NULL,
  owner_kind TEXT NOT NULL CHECK(owner_kind IN (
    'character','item','location','faction','lore_system','fact','plot_beat','relationship',
    'ability','effect','weather','outfit','navigation_space','map_feature'
  )),
  PRIMARY KEY(project_id, stat_key, owner_kind),
  FOREIGN KEY(project_id, stat_key)
    REFERENCES stat_definitions(project_id, stat_key) ON DELETE CASCADE
);

INSERT INTO stat_definition_owner_kinds(project_id,stat_key,owner_kind)
SELECT project_id,stat_key,owner_kind FROM stat_definition_owner_kinds_v2_old;

DROP TABLE stat_definition_owner_kinds_v2_old;

CREATE TABLE rule_object_stats (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  owner_kind TEXT NOT NULL CHECK(owner_kind IN (
    'ability','effect','weather','outfit','navigation_space','map_feature'
  )),
  owner_id TEXT NOT NULL,
  stat_key TEXT NOT NULL,
  value REAL NOT NULL,
  PRIMARY KEY(project_id, owner_kind, owner_id, stat_key),
  FOREIGN KEY(project_id, stat_key)
    REFERENCES stat_definitions(project_id, stat_key) ON DELETE CASCADE
);

CREATE INDEX idx_rule_object_stats_owner
  ON rule_object_stats(project_id,owner_kind,owner_id);
