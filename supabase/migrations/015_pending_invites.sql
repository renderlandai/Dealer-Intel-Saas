-- 015_pending_invites.sql
-- Pending invitations for team members to join an organization.

CREATE TABLE IF NOT EXISTS pending_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    invited_by UUID NOT NULL,
    token UUID NOT NULL DEFAULT gen_random_uuid(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '7 days'),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invites_org ON pending_invites(organization_id);
CREATE INDEX IF NOT EXISTS idx_invites_email ON pending_invites(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invites_token ON pending_invites(token);
