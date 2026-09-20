ALTER TABLE weather_definitions ADD COLUMN imagegen_description TEXT NOT NULL DEFAULT '';
ALTER TABLE time_phases ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE time_phases ADD COLUMN imagegen_description TEXT NOT NULL DEFAULT '';

CREATE TABLE ambient_assignments_new (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  owner_type TEXT NOT NULL CHECK(owner_type IN ('weather','time','location','action')),
  owner_id TEXT NOT NULL,
  selector_type TEXT NOT NULL DEFAULT 'default' CHECK(selector_type IN ('default','indoor','outdoor','isolated','tag')),
  selector_value TEXT,
  weather_id TEXT REFERENCES weather_definitions(id) ON DELETE CASCADE,
  time_phase_id TEXT REFERENCES time_phases(id) ON DELETE CASCADE,
  variant_id TEXT NOT NULL REFERENCES ambient_variants(id) ON DELETE CASCADE
);
INSERT INTO ambient_assignments_new
SELECT id,project_id,owner_type,owner_id,selector_type,selector_value,weather_id,time_phase_id,variant_id
FROM ambient_assignments;
DROP TABLE ambient_assignments;
ALTER TABLE ambient_assignments_new RENAME TO ambient_assignments;
CREATE INDEX idx_ambient_assignments_project ON ambient_assignments(project_id, owner_type, owner_id);
CREATE UNIQUE INDEX idx_ambient_assignment_unique ON ambient_assignments(
  project_id,owner_type,owner_id,selector_type,COALESCE(selector_value,''),
  COALESCE(weather_id,''),COALESCE(time_phase_id,''),variant_id
);
