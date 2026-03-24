-- Add logo_url to organizations for PDF report branding
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS logo_url TEXT;

-- Storage bucket for organization logos (run manually in Supabase dashboard
-- if not using the CLI: Storage → New Bucket → "org-logos", public = true)
