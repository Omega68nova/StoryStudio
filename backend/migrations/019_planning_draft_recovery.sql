ALTER TABLE planning_stages ADD COLUMN raw_draft_text TEXT;
ALTER TABLE planning_stages ADD COLUMN validation_error TEXT;
ALTER TABLE planning_stage_revisions ADD COLUMN raw_output TEXT;
ALTER TABLE planning_stage_revisions ADD COLUMN validation_error TEXT;

