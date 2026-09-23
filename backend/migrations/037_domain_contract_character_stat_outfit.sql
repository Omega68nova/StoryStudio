-- Phase 6: canonical Character / Stat / Outfit domain contract.

ALTER TABLE entity_outfits
ADD COLUMN imagegen_description TEXT NOT NULL DEFAULT '';

ALTER TABLE stat_definitions
ADD COLUMN description TEXT NOT NULL DEFAULT '';

ALTER TABLE stat_definitions
ADD COLUMN minimum_stat_key TEXT;

ALTER TABLE stat_definitions
ADD COLUMN maximum_stat_key TEXT;

ALTER TABLE stat_definitions
ADD COLUMN color TEXT;

ALTER TABLE stat_definitions
ADD COLUMN minimum_color TEXT;

ALTER TABLE stat_definitions
ADD COLUMN maximum_color TEXT;

ALTER TABLE stat_definitions
ADD COLUMN display_style TEXT NOT NULL DEFAULT 'compact'
CHECK(display_style IN ('compact','bar'));

CREATE INDEX idx_stat_definitions_project_scope
ON stat_definitions(project_id, scope, stat_key);
