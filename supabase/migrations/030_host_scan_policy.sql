-- Phase 6 — Adaptive scan-strategy policy per hostname.
--
-- Today every hostname starts with the same Playwright-desktop-first
-- ladder. When a host (e.g. `rent.cat.com`) is consistently blocked
-- behind an Akamai WAF, we currently re-discover that fact every scan
-- by burning 60-120s of Playwright timeouts before falling back to
-- ScreenshotOne. That re-learning is wasted time and money.
--
-- This table records the latest known good "render strategy" per
-- hostname so the runner can shortcut the ladder. The strategy
-- auto-promotes when the runner sees N consecutive blocked/timeout
-- scans on a host, and decays back when a higher tier starts working
-- (or after 30 days of silence so a host that fixed its WAF gets
-- re-probed).
--
-- Strategies (in escalation order — see `render_strategies.STRATEGY_TIER`):
--   playwright_desktop          tier 0  default; cheapest
--   playwright_mobile_first     tier 1  try mobile UA before desktop
--   playwright_then_screenshotone tier 2  Playwright once, fall back to ScreenshotOne
--   screenshotone_only          tier 3  skip Playwright entirely (datacenter IPs)
--   screenshotone_residential   tier 4  ScreenshotOne with proxy=residential (~$0.01/render)
--   unreachable                 tier 5  flag-only; runner still tries ScreenshotOne residential
--
-- WAF vendor is sniffed from response headers on the first successful
-- (or blocked-but-with-headers) probe. Stored so the operator can see
-- *why* a host got promoted and so future heuristics (e.g. Cloudflare
-- needs cf_clearance) can branch on vendor.

CREATE TABLE IF NOT EXISTS host_scan_policy (
    hostname            TEXT PRIMARY KEY,
    strategy            TEXT NOT NULL DEFAULT 'playwright_desktop',
    waf_vendor          TEXT,                                    -- 'akamai' | 'cloudflare' | 'imperva' | 'cloudfront' | 'sucuri' | 'fastly' | null
    confidence          INTEGER NOT NULL DEFAULT 0,              -- consecutive same-outcome scans (drives promotion)
    last_outcome        TEXT,                                    -- mirrors render_strategies.OUTCOME_*
    last_block_reason   TEXT,
    last_http_status    INTEGER,
    success_count_30d   INTEGER NOT NULL DEFAULT 0,
    blocked_count_30d   INTEGER NOT NULL DEFAULT 0,
    timeout_count_30d   INTEGER NOT NULL DEFAULT 0,
    last_seen_at        TIMESTAMPTZ,
    last_promoted_at    TIMESTAMPTZ,
    manual_override     BOOLEAN NOT NULL DEFAULT FALSE,          -- when true, auto-promotion is disabled
    notes               TEXT,                                    -- operator-editable freeform
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT host_scan_policy_strategy_check CHECK (
        strategy IN (
            'playwright_desktop',
            'playwright_mobile_first',
            'playwright_then_screenshotone',
            'screenshotone_only',
            'screenshotone_residential',
            'unreachable'
        )
    )
);

COMMENT ON TABLE host_scan_policy IS
    'Per-hostname adaptive render strategy. Auto-promoted by host_policy_service after each website scan based on observed outcomes. Manual_override pins a row.';

-- Index for the post-scan aggregation hook which upserts by hostname.
-- (Hostname is already the PK so this is mostly future-proofing for the
--  stale-decay query.)
CREATE INDEX IF NOT EXISTS idx_host_scan_policy_last_seen
    ON host_scan_policy(last_seen_at);

-- Touch updated_at on every UPDATE so the operator UI can sort by
-- recency. We avoid a generic trigger to keep the schema portable; the
-- service layer sets updated_at explicitly. Index supports the admin
-- "Host Health" page sort.
CREATE INDEX IF NOT EXISTS idx_host_scan_policy_strategy
    ON host_scan_policy(strategy);

-- PostgREST cache reload so supabase-py sees the new table immediately
-- (lesson from migrations 028 and 029).
NOTIFY pgrst, 'reload schema';
