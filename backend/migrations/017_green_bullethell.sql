INSERT OR IGNORE INTO bullethell_skills VALUES
('builtin:green_shield','green_shield',1,'Green shield','free_move','{"green_shield":1.0}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);

INSERT OR IGNORE INTO bullethell_modes VALUES
('builtin:green','green',1,'Green','builtin:green_shield','["builtin:green_shield"]','{}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);

INSERT OR IGNORE INTO bullethell_attacks VALUES
('builtin:spear_volley','spear_volley',1,'Spear Volley','Spears approach from eight directions. Face the directional shield toward each incoming spear.','["spear","shield","directional"]',1,500,'[{"type":"spear_burst","start_ms":300,"duration_ms":4400,"repetitions":10,"spacing_ms":380,"telegraph_ms":300,"speed":0.75,"radius":0.035,"damage_multiplier":1.0}]',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
