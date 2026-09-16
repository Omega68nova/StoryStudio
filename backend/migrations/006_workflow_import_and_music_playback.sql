ALTER TABLE music_themes ADD COLUMN playback_mode TEXT NOT NULL DEFAULT 'shuffle'
  CHECK(playback_mode IN ('shuffle', 'repeat_one', 'in_order'));

ALTER TABLE workflow_presets ADD COLUMN source_graph_json TEXT;
ALTER TABLE workflow_presets ADD COLUMN source_format TEXT NOT NULL DEFAULT 'api'
  CHECK(source_format IN ('api', 'ui'));
