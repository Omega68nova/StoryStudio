ALTER TABLE runtime_settings ADD COLUMN planning_context_tokens INTEGER NOT NULL DEFAULT 8192;

UPDATE runtime_settings SET planning_context_tokens = context_tokens;
