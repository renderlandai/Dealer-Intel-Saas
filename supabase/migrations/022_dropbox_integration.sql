-- Extend integrations table for Dropbox support
ALTER TABLE integrations DROP CONSTRAINT IF EXISTS integrations_provider_check;
ALTER TABLE integrations ADD CONSTRAINT integrations_provider_check
    CHECK (provider IN ('slack', 'teams', 'salesforce', 'dropbox', 'google_drive'));

-- Store the synced folder path and associated campaign
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS folder_path TEXT;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS folder_name TEXT;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;
