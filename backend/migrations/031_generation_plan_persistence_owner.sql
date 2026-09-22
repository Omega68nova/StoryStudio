-- Phase 4 Slice 8
-- GenerationPlan now owns editable/review lifecycle. Legacy planning stage
-- rows remain temporarily as publication provenance and FK anchors only.

ALTER TABLE generation_plans ADD COLUMN legacy_import_complete INTEGER NOT NULL DEFAULT 0;

UPDATE generation_plans
SET legacy_import_complete = 1
WHERE source_kind = 'planning_session';
