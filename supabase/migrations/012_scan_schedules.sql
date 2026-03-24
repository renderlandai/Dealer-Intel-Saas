-- Scan schedule configuration
CREATE TABLE IF NOT EXISTS scan_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('google_ads', 'facebook', 'instagram', 'website')),
    frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly', 'biweekly', 'monthly')),
    run_at_time TEXT NOT NULL DEFAULT '09:00',
    run_on_day INTEGER CHECK (run_on_day BETWEEN 0 AND 6),
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(campaign_id, source)
);

CREATE INDEX IF NOT EXISTS idx_scan_schedules_active ON scan_schedules (is_active, next_run_at)
    WHERE is_active = true;
