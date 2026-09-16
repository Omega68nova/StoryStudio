CREATE TABLE bullethell_skills (
  id TEXT PRIMARY KEY, definition_key TEXT NOT NULL UNIQUE, version INTEGER NOT NULL DEFAULT 1,
  name TEXT NOT NULL, behavior TEXT NOT NULL CHECK(behavior IN ('free_move','blue_gravity','roll')),
  parameters_json TEXT NOT NULL DEFAULT '{}', built_in INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE bullethell_modes (
  id TEXT PRIMARY KEY, definition_key TEXT NOT NULL UNIQUE, version INTEGER NOT NULL DEFAULT 1,
  name TEXT NOT NULL, movement_skill_id TEXT NOT NULL REFERENCES bullethell_skills(id) ON DELETE RESTRICT,
  allowed_skill_ids_json TEXT NOT NULL DEFAULT '[]', parameters_json TEXT NOT NULL DEFAULT '{}',
  built_in INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE bullethell_attacks (
  id TEXT PRIMARY KEY, definition_key TEXT NOT NULL UNIQUE, version INTEGER NOT NULL DEFAULT 1,
  name TEXT NOT NULL, ai_description TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',
  uses_enemy_forced_mode INTEGER NOT NULL DEFAULT 0, hit_immunity_ms INTEGER NOT NULL DEFAULT 500,
  phases_json TEXT NOT NULL DEFAULT '[]', built_in INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE project_bullethell_settings (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  default_mode_id TEXT REFERENCES bullethell_modes(id) ON DELETE RESTRICT,
  updated_at TEXT NOT NULL
);
CREATE TABLE project_bullethell_modes (project_id TEXT REFERENCES projects(id) ON DELETE CASCADE, mode_id TEXT REFERENCES bullethell_modes(id) ON DELETE RESTRICT, PRIMARY KEY(project_id,mode_id));
CREATE TABLE project_bullethell_skills (project_id TEXT REFERENCES projects(id) ON DELETE CASCADE, skill_id TEXT REFERENCES bullethell_skills(id) ON DELETE RESTRICT, PRIMARY KEY(project_id,skill_id));
CREATE TABLE project_bullethell_attacks (project_id TEXT REFERENCES projects(id) ON DELETE CASCADE, attack_id TEXT REFERENCES bullethell_attacks(id) ON DELETE RESTRICT, PRIMARY KEY(project_id,attack_id));

INSERT INTO bullethell_skills VALUES
('builtin:free_move','free_move',1,'Free movement','free_move','{"speed":1.0}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('builtin:blue_gravity','blue_gravity',1,'Blue gravity','blue_gravity','{"speed":1.0,"gravity":1.0,"jump_strength":1.0,"max_jump_hold_ms":280}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('builtin:roll','roll',1,'Roll','roll','{"speed":2.4,"duration_ms":350,"cooldown_ms":1000}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
INSERT INTO bullethell_modes VALUES
('builtin:base','base',1,'Base','builtin:free_move','["builtin:free_move","builtin:roll"]','{}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('builtin:blue','blue',1,'Blue','builtin:blue_gravity','["builtin:blue_gravity","builtin:roll"]','{}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
INSERT INTO bullethell_attacks VALUES
('builtin:particle_rain','particle_rain',1,'Particle Rain','Seeded particles fall from above.','["rain","projectile"]',0,500,'[{"type":"particle_rain","start_ms":0,"duration_ms":5000,"density":12,"radius":0.025,"speed":0.34,"damage_multiplier":1.0}]',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('builtin:third_beams','third_beams',1,'Third-Screen Beams','Telegraphed beams cover one third of the arena.','["beam","telegraphed"]',1,500,'[{"type":"third_beam","start_ms":250,"duration_ms":4500,"direction":"vertical","repetitions":4,"spacing_ms":1050,"telegraph_ms":650,"active_ms":300,"damage_multiplier":1.0}]',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
INSERT INTO project_bullethell_settings(project_id,default_mode_id,updated_at) SELECT id,'builtin:base',updated_at FROM projects;
