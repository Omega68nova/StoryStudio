ALTER TABLE project_environment_settings ADD COLUMN perception_stat_key TEXT;
ALTER TABLE weather_definitions ADD COLUMN visibility_multiplier REAL NOT NULL DEFAULT 1.0 CHECK(visibility_multiplier >= 0);
ALTER TABLE time_phases ADD COLUMN visibility_multiplier REAL NOT NULL DEFAULT 1.0 CHECK(visibility_multiplier >= 0);
