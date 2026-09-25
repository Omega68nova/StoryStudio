-- Map V2 authoring metadata: deterministic overlapping-area priority and
-- semantic route endpoint bindings.
ALTER TABLE spatial_locations
ADD COLUMN priority_layer REAL NOT NULL DEFAULT 0;

ALTER TABLE spatial_anchors_current
ADD COLUMN binding_kind TEXT NOT NULL DEFAULT 'coordinate'
CHECK(binding_kind IN ('coordinate','area','area_border','spot'));

ALTER TABLE spatial_anchors_current
ADD COLUMN binding_target_id TEXT;
