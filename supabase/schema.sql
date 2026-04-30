-- Dealer Intel SaaS - Database Schema
-- Run this in Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- ORGANIZATIONS (Multi-tenant support)
-- ============================================
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- CAMPAIGNS
-- ============================================
CREATE TABLE campaigns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active', -- active, paused, completed
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_campaigns_org ON campaigns(organization_id);
CREATE INDEX idx_campaigns_status ON campaigns(status);

-- ============================================
-- ASSETS (Approved campaign creative)
-- ============================================
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    file_url TEXT NOT NULL,
    file_type VARCHAR(50), -- image/png, image/jpeg, video/mp4
    thumbnail_url TEXT,
    width INTEGER,
    height INTEGER,
    file_size INTEGER,
    metadata JSONB DEFAULT '{}',
    -- Channels this creative is approved for. Empty array = all channels.
    -- Values mirror app.models.ScanSource: google_ads, facebook, instagram, youtube, website.
    target_platforms TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_assets_campaign ON assets(campaign_id);
CREATE INDEX idx_assets_target_platforms ON assets USING GIN (target_platforms);

-- ============================================
-- DISTRIBUTORS (Dealers)
-- ============================================
CREATE TABLE distributors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50), -- Internal dealer code
    website_url TEXT,
    facebook_url TEXT,
    instagram_url TEXT,
    youtube_url TEXT,
    google_ads_advertiser_id TEXT,
    region VARCHAR(100),
    status VARCHAR(50) DEFAULT 'active', -- active, inactive
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_distributors_org ON distributors(organization_id);
CREATE INDEX idx_distributors_status ON distributors(status);

-- ============================================
-- SCAN JOBS (Scraping runs)
-- ============================================
CREATE TABLE scan_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'pending', -- pending, running, completed, failed
    source VARCHAR(50) NOT NULL, -- google_ads, facebook, instagram, website
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_heartbeat_at TIMESTAMP WITH TIME ZONE, -- bumped each page by the runner; cleanup keys off this
    total_items INTEGER DEFAULT 0, -- Total images discovered during scan
    processed_items INTEGER DEFAULT 0, -- Images that have been analyzed
    matches_count INTEGER DEFAULT 0, -- Actual matches found against campaign assets
    error_message TEXT,
    apify_run_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_scan_jobs_org ON scan_jobs(organization_id);
CREATE INDEX idx_scan_jobs_status ON scan_jobs(status);
CREATE INDEX idx_scan_jobs_status_heartbeat ON scan_jobs(status, last_heartbeat_at);

-- ============================================
-- DISCOVERED IMAGES (Scraped content)
-- ============================================
CREATE TABLE discovered_images (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scan_job_id UUID REFERENCES scan_jobs(id) ON DELETE CASCADE,
    distributor_id UUID REFERENCES distributors(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    image_url TEXT NOT NULL,
    local_file_url TEXT, -- Stored copy in Supabase Storage
    source_type VARCHAR(50), -- ad, organic_post, website_banner
    channel VARCHAR(50), -- google_ads, facebook, instagram, youtube, website
    discovered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    is_processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_discovered_distributor ON discovered_images(distributor_id);
CREATE INDEX idx_discovered_job ON discovered_images(scan_job_id);
CREATE INDEX idx_discovered_processed ON discovered_images(is_processed);

-- ============================================
-- MATCHES (Asset matches found)
-- ============================================
CREATE TABLE matches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asset_id UUID REFERENCES assets(id) ON DELETE CASCADE,
    discovered_image_id UUID REFERENCES discovered_images(id) ON DELETE CASCADE,
    distributor_id UUID REFERENCES distributors(id) ON DELETE SET NULL,
    confidence_score DECIMAL(5,2), -- 0.00 to 100.00
    match_type VARCHAR(50), -- exact, strong, partial, weak
    is_modified BOOLEAN DEFAULT FALSE,
    modifications JSONB DEFAULT '[]', -- List of detected modifications
    channel VARCHAR(50),
    source_url TEXT,
    screenshot_url TEXT,
    discovered_at TIMESTAMP WITH TIME ZONE,
    compliance_status VARCHAR(50) DEFAULT 'pending', -- pending, compliant, violation, review
    compliance_issues JSONB DEFAULT '[]',
    ai_analysis JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by UUID
);

CREATE INDEX idx_matches_asset ON matches(asset_id);
CREATE INDEX idx_matches_distributor ON matches(distributor_id);
CREATE INDEX idx_matches_confidence ON matches(confidence_score);
CREATE INDEX idx_matches_compliance ON matches(compliance_status);

-- ============================================
-- COMPLIANCE RULES
-- ============================================
CREATE TABLE compliance_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    rule_type VARCHAR(50), -- required_element, forbidden_element, date_check
    rule_config JSONB NOT NULL, -- Rule-specific configuration
    severity VARCHAR(50) DEFAULT 'warning', -- info, warning, critical
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_rules_org ON compliance_rules(organization_id);

-- ============================================
-- ALERTS
-- ============================================
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    match_id UUID REFERENCES matches(id) ON DELETE CASCADE,
    distributor_id UUID REFERENCES distributors(id) ON DELETE SET NULL,
    alert_type VARCHAR(50) NOT NULL, -- compliance_violation, zombie_ad, modified_asset
    severity VARCHAR(50) DEFAULT 'warning',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_alerts_org ON alerts(organization_id);
CREATE INDEX idx_alerts_unread ON alerts(is_read) WHERE is_read = FALSE;

-- Adaptive scan-strategy policy per hostname (mirror of migrations 030 + 031).
-- See `services/host_policy_service.py` and
-- `services/render_strategies.py` for the auto-promotion ladder.
-- Strategy enum updated in migration 031 to replace ScreenshotOne with
-- Bright Data Web Unlocker — see `services/unlocker_service.py`.
CREATE TABLE IF NOT EXISTS host_scan_policy (
    hostname            TEXT PRIMARY KEY,
    strategy            TEXT NOT NULL DEFAULT 'playwright_desktop',
    waf_vendor          TEXT,
    confidence          INTEGER NOT NULL DEFAULT 0,
    last_outcome        TEXT,
    last_block_reason   TEXT,
    last_http_status    INTEGER,
    success_count_30d   INTEGER NOT NULL DEFAULT 0,
    blocked_count_30d   INTEGER NOT NULL DEFAULT 0,
    timeout_count_30d   INTEGER NOT NULL DEFAULT 0,
    last_seen_at        TIMESTAMPTZ,
    last_promoted_at    TIMESTAMPTZ,
    manual_override     BOOLEAN NOT NULL DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT host_scan_policy_strategy_check CHECK (
        strategy IN (
            'playwright_desktop',
            'playwright_mobile_first',
            'playwright_then_unlocker',
            'unlocker_only',
            'unreachable'
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_host_scan_policy_last_seen
    ON host_scan_policy(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_host_scan_policy_strategy
    ON host_scan_policy(strategy);

-- Page-level hit cache for recurring scan optimization (mirror of
-- migrations 016 + 032). On repeat scans, hot pages are scanned first;
-- if all campaign assets are matched from cached pages alone (early
-- stop), full page discovery is skipped entirely. See
-- `services/page_cache_service.py`.
--
-- This block was missing from schema.sql when the prod database was
-- bootstrapped, which is why runtime ``page_cache_service`` calls
-- logged ``Could not find the table 'public.page_hit_cache'``. Adding
-- here so future fresh installs pick it up; migration 032 re-applies
-- it idempotently to existing databases.
CREATE TABLE IF NOT EXISTS page_hit_cache (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id    UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    distributor_id     UUID NOT NULL REFERENCES distributors(id) ON DELETE CASCADE,
    campaign_id        UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    page_url           TEXT NOT NULL,
    hit_count          INTEGER NOT NULL DEFAULT 1,
    last_hit_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    asset_ids_matched  JSONB DEFAULT '[]',
    created_at         TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_phc_org_dist
    ON page_hit_cache(organization_id, distributor_id);
CREATE INDEX IF NOT EXISTS idx_phc_campaign
    ON page_hit_cache(campaign_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_phc_unique_page
    ON page_hit_cache(organization_id, distributor_id, campaign_id, page_url);

-- ============================================
-- VIEWS FOR DASHBOARD
-- ============================================

-- Dashboard stats view
CREATE OR REPLACE VIEW dashboard_stats AS
SELECT 
    o.id as organization_id,
    (SELECT COUNT(*) FROM campaigns c WHERE c.organization_id = o.id AND c.status = 'active') as active_campaigns,
    (SELECT COUNT(*) FROM assets a JOIN campaigns c ON a.campaign_id = c.id WHERE c.organization_id = o.id) as total_assets,
    (SELECT COUNT(*) FROM distributors d WHERE d.organization_id = o.id AND d.status = 'active') as active_distributors,
    (SELECT COUNT(*) FROM matches m 
        JOIN assets a ON m.asset_id = a.id 
        JOIN campaigns c ON a.campaign_id = c.id 
        WHERE c.organization_id = o.id) as total_matches,
    (SELECT COUNT(*) FROM alerts al WHERE al.organization_id = o.id AND al.is_read = FALSE) as unread_alerts
FROM organizations o;

-- Recent matches view (deduplicated: best match per asset+distributor)
CREATE OR REPLACE VIEW recent_matches AS
WITH ranked AS (
    SELECT
        m.*,
        a.name        AS asset_name,
        a.file_url    AS asset_url,
        d.name        AS distributor_name,
        c.name        AS campaign_name,
        COALESCE(m.screenshot_url, di.image_url) AS discovered_image_url,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(m.asset_id, m.id), COALESCE(m.distributor_id, m.id)
            ORDER BY m.confidence_score DESC, m.last_seen_at DESC NULLS LAST, m.created_at DESC
        ) AS rn
    FROM matches m
    LEFT JOIN assets a             ON m.asset_id = a.id
    LEFT JOIN distributors d       ON m.distributor_id = d.id
    LEFT JOIN campaigns c          ON a.campaign_id = c.id
    LEFT JOIN discovered_images di ON m.discovered_image_id = di.id
)
SELECT
    id, asset_id, discovered_image_id, distributor_id,
    confidence_score, match_type, is_modified, modifications,
    channel, source_url, screenshot_url, discovered_at,
    compliance_status, compliance_issues, ai_analysis,
    created_at, reviewed_at, reviewed_by,
    last_seen_at, scan_count, previous_compliance_status,
    asset_name, asset_url, distributor_name, campaign_name,
    discovered_image_url
FROM ranked
WHERE rn = 1
ORDER BY created_at DESC;

-- ============================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================

-- Enable RLS on all tables
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE distributors ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE discovered_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;

-- For MVP: Allow all operations with service role key
-- In production, add proper user-based policies

CREATE POLICY "Allow all for service role" ON organizations FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON campaigns FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON assets FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON distributors FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON scan_jobs FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON discovered_images FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON matches FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON compliance_rules FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON alerts FOR ALL USING (true);

-- ============================================
-- SEED DATA (Demo Organization)
-- ============================================

INSERT INTO organizations (id, name, slug) VALUES 
    ('00000000-0000-0000-0000-000000000001', 'Demo Organization', 'demo');

-- Sample Campaign
INSERT INTO campaigns (id, organization_id, name, description, status) VALUES
    ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Q1 2026 Brand Campaign', 'Main brand awareness campaign for Q1', 'active');

-- Sample Distributors
INSERT INTO distributors (organization_id, name, code, website_url, facebook_url, region, status) VALUES
    ('00000000-0000-0000-0000-000000000001', 'Mustang CAT', 'MCAT001', 'https://mustangcat.com', 'https://facebook.com/MustangCAT', 'Texas', 'active'),
    ('00000000-0000-0000-0000-000000000001', 'Thompson Machinery', 'THOM002', 'https://thomcat.com', 'https://facebook.com/ThompsonCat', 'Tennessee', 'active'),
    ('00000000-0000-0000-0000-000000000001', 'Ring Power', 'RING003', 'https://ringpower.com', 'https://facebook.com/RingPower', 'Florida', 'active');




