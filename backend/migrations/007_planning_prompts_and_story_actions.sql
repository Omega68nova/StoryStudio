ALTER TABLE planning_stages ADD COLUMN human_prompt TEXT NOT NULL DEFAULT '';

ALTER TABLE story_nodes ADD COLUMN action_kind TEXT NOT NULL DEFAULT 'do'
  CHECK(action_kind IN ('story', 'say', 'do', 'guide', 'continue', 'manual_story'));

UPDATE planning_stages
SET status = CASE WHEN draft_json IS NULL THEN 'pending' ELSE 'draft' END
WHERE status = 'generating';
