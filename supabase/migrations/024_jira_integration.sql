-- Extend integrations table for Jira support
ALTER TABLE integrations DROP CONSTRAINT IF EXISTS integrations_provider_check;
ALTER TABLE integrations ADD CONSTRAINT integrations_provider_check
    CHECK (provider IN ('slack', 'teams', 'salesforce', 'dropbox', 'google_drive', 'jira'));

-- Jira needs cloud_id and project_key stored on the integration row
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS cloud_id TEXT;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS project_key TEXT;
