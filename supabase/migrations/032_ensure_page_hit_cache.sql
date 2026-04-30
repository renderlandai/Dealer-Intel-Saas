-- Phase 6.5.2 — re-apply page_hit_cache table on databases that missed it.
--
-- Why
-- ---
-- The 2026-04-30 logs from the production worker show this on every
-- scan:
--
--   WARNING  Page cache lookup failed:
--     {'message': "Could not find the table 'public.page_hit_cache' ...",
--      'code': 'PGRST205'}
--   WARNING  Failed to record page hit for ...:
--     {'message': 'Missing response', 'code': '204'}
--
-- The table was introduced in migration 016. The CREATE statement was
-- never copied into supabase/schema.sql, so any environment that was
-- bootstrapped from schema.sql (rather than by replaying every
-- migration in order) is missing the table. The cache logic fails
-- soft, so scans still complete, but the entire optimisation that
-- skips already-empty pages on re-scans is dead — every page on every
-- recurring scan re-runs the full extraction pipeline.
--
-- This migration re-applies migration 016 verbatim with IF NOT EXISTS
-- guards so it is a no-op on databases that already have the table
-- and a fix on those that don't. Schema.sql has also been updated so
-- new bootstraps include the table.
--
-- Safe to re-run.

BEGIN;

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

COMMENT ON TABLE page_hit_cache IS
    'Per-(org, distributor, campaign, page_url) cache of pages that produced matches. Read by services/page_cache_service.get_cached_pages on every scan to seed Phase 1; written by record_page_hits after every successful match.';

COMMIT;
