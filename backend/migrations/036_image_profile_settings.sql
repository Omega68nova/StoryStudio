-- Phase 6: configurable semantic image profile prefixes.
ALTER TABLE runtime_settings
ADD COLUMN portrait_prompt_prefix TEXT NOT NULL DEFAULT 'portrait, anime style, full color, clean lineart, soft shading, looking at viewer, simple background, white background,';

ALTER TABLE runtime_settings
ADD COLUMN full_body_prompt_prefix TEXT NOT NULL DEFAULT 'full body, standing, anime style, full color, clean lineart, soft shading, looking at viewer, simple background, white background,';

ALTER TABLE runtime_settings
ADD COLUMN icon_prompt_prefix TEXT NOT NULL DEFAULT '(((no humans))),simple background, white background,';
