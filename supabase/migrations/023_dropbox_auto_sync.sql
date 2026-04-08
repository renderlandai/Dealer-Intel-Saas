-- Store the Dropbox account ID for webhook matching
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS external_account_id TEXT;

-- Track folder-to-campaign mappings for auto-sync
CREATE TABLE IF NOT EXISTS dropbox_folder_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    folder_path TEXT NOT NULL,
    folder_name TEXT NOT NULL,
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(integration_id, folder_path)
);

CREATE INDEX IF NOT EXISTS idx_dbx_folder_mappings_integration ON dropbox_folder_mappings(integration_id);
CREATE INDEX IF NOT EXISTS idx_dbx_folder_mappings_org ON dropbox_folder_mappings(organization_id);
