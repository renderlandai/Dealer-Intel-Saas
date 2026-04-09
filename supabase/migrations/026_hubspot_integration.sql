-- Extend integrations provider constraint to include 'hubspot'
ALTER TABLE integrations DROP CONSTRAINT IF EXISTS integrations_provider_check;
ALTER TABLE integrations ADD CONSTRAINT integrations_provider_check
    CHECK (provider IN ('slack', 'salesforce', 'dropbox', 'google_drive', 'jira', 'hubspot'));

-- Track HubSpot portal ID for the connected account
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS hubspot_portal_id TEXT;

-- Store the Company filter for HubSpot sync (e.g. a filter JSON string)
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS hubspot_sync_filter TEXT;

-- Add hubspot_id to distributors for linking dealers to HubSpot Companies
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS hubspot_id TEXT;
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS hubspot_synced_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_distributors_hubspot_id
    ON distributors(hubspot_id) WHERE hubspot_id IS NOT NULL;
