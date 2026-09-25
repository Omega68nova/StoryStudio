-- Persist enough attachment geometry for bound route endpoints to follow
-- their target spots and areas when those targets move or are reshaped.
ALTER TABLE spatial_anchors_current ADD COLUMN binding_offset_x REAL;
ALTER TABLE spatial_anchors_current ADD COLUMN binding_offset_y REAL;
ALTER TABLE spatial_anchors_current ADD COLUMN binding_segment_index INTEGER;
ALTER TABLE spatial_anchors_current ADD COLUMN binding_segment_t REAL;
