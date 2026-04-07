-- Extend integrations table for Salesforce support
ALTER TABLE integrations DROP CONSTRAINT IF EXISTS integrations_provider_check;
ALTER TABLE integrations ADD CONSTRAINT integrations_provider_check
    CHECK (provider IN ('slack', 'teams', 'salesforce'));

ALTER TABLE integrations ADD COLUMN IF NOT EXISTS refresh_token TEXT;
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS instance_url TEXT;
