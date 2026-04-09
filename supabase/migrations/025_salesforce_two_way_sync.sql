-- Add Salesforce sync tracking columns to distributors
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS salesforce_id TEXT;
ALTER TABLE distributors ADD COLUMN IF NOT EXISTS salesforce_synced_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_distributors_sf_id
    ON distributors(salesforce_id) WHERE salesforce_id IS NOT NULL;

-- Track last inbound sync timestamp on the integration row
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

-- Store the SOQL filter for Salesforce sync (e.g. "RecordType.Name = 'Dealer'")
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS salesforce_sync_filter TEXT;
