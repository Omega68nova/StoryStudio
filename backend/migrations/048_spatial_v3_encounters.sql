-- Spatial V3 encounter policies.
--
-- Random encounters are navigation behavior, not a boolean on semantic
-- locations. Policies may target the navigation space itself (the unassigned
-- base zone) or any feature inside it. This lets city, district, forest, road,
-- corridor, connector, etc. contribute different encounter pools.
--
-- Composition:
--   augment  -> contributes rate/candidates on top of lower-priority policies
--   replace  -> discards lower-priority encounter contributors, then contributes
--   disabled -> discards lower-priority contributors and disables encounters
--
-- Policies are evaluated in ascending priority. Equal priority remains stable
-- by id. A later replace/disabled therefore overrides earlier/base policies.

CREATE TABLE navigation_encounter_policies_current (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    navigation_space_id TEXT REFERENCES navigation_spaces_current(id) ON DELETE CASCADE,
    feature_id TEXT REFERENCES map_features_current(id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'augment'
        CHECK(mode IN ('augment','replace','disabled')),
    priority REAL NOT NULL DEFAULT 0,
    rate_per_100_units REAL NOT NULL DEFAULT 0 CHECK(rate_per_100_units >= 0),
    minimum_distance REAL NOT NULL DEFAULT 0 CHECK(minimum_distance >= 0),
    candidates_json TEXT NOT NULL DEFAULT '[]',
    conditions_json TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL,
    CHECK((navigation_space_id IS NULL) <> (feature_id IS NULL))
);
CREATE INDEX idx_nav_encounter_space
    ON navigation_encounter_policies_current(project_id, navigation_space_id, priority);
CREATE INDEX idx_nav_encounter_feature
    ON navigation_encounter_policies_current(project_id, feature_id, priority);
