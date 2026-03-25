-- Page-level hit cache for recurring scan optimization.
-- Stores which pages produced matches so repeat scans
-- can prioritize them and skip full page discovery.

CREATE TABLE IF NOT EXISTS page_hit_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    distributor_id UUID NOT NULL REFERENCES distributors(id) ON DELETE CASCADE,
    campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    page_url TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 1,
    last_hit_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    asset_ids_matched JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_phc_org_dist ON page_hit_cache(organization_id, distributor_id);
CREATE INDEX IF NOT EXISTS idx_phc_campaign ON page_hit_cache(campaign_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_phc_unique_page
    ON page_hit_cache(organization_id, distributor_id, campaign_id, page_url);
