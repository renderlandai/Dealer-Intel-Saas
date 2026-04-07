-- Integrations table for Slack, Teams, and future third-party connections
CREATE TABLE IF NOT EXISTS integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('slack', 'teams')),
    access_token TEXT,
    webhook_url TEXT,
    workspace_name TEXT,
    channel_name TEXT,
    channel_id TEXT,
    bot_user_id TEXT,
    connected_by UUID,
    connected_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(organization_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_integrations_org ON integrations(organization_id);
