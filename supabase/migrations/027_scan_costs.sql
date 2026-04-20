-- Track per-scan vendor cost in USD.
-- cost_usd: total billed cost for this scan (sum across all vendors).
-- cost_breakdown: per-vendor totals + line items so the UI can show details.
--
-- The full per-call line items also live inside pipeline_stats.cost so the
-- existing PipelineFunnel UI already has access; the dedicated columns are
-- here for fast aggregation (e.g. monthly spend per org).

ALTER TABLE scan_jobs
    ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(10, 4) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cost_breakdown JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN scan_jobs.cost_usd IS 'Total vendor cost (USD) attributed to this scan: Anthropic + Apify + SerpApi + ScreenshotOne.';
COMMENT ON COLUMN scan_jobs.cost_breakdown IS 'Per-vendor totals and line items. Schema: {total_usd, by_vendor: {anthropic: x, apify: y, ...}, line_items: [...]}.';

CREATE INDEX IF NOT EXISTS idx_scan_jobs_cost_org_time
    ON scan_jobs (organization_id, completed_at DESC)
    WHERE cost_usd > 0;
