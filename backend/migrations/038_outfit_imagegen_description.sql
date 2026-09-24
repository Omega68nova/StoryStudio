-- Restore the canonical outfit image-generation description while preserving
-- values written through the temporary legacy `appearance` field.

ALTER TABLE entity_outfits
ADD COLUMN imagegen_description TEXT NOT NULL DEFAULT '';

UPDATE entity_outfits
SET imagegen_description = appearance
WHERE imagegen_description = ''
  AND appearance <> '';
