-- 014_billing_plan.sql
-- Add subscription/billing columns to organizations for Stripe integration.

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS plan VARCHAR(20) DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS plan_status VARCHAR(20) DEFAULT 'trialing',
    ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT,
    ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT,
    ADD COLUMN IF NOT EXISTS extra_dealers_count INTEGER DEFAULT 0;

-- Default new orgs to a 14-day trial
UPDATE organizations
SET trial_expires_at = NOW() + INTERVAL '14 days'
WHERE plan = 'free' AND trial_expires_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_orgs_plan ON organizations(plan);
CREATE INDEX IF NOT EXISTS idx_orgs_stripe_customer ON organizations(stripe_customer_id);
