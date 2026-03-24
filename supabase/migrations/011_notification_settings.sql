-- Add email notification settings to organizations
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS notify_email TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS notify_on_violation BOOLEAN DEFAULT true;
