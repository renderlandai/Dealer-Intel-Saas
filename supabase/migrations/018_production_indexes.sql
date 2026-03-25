-- Production performance indexes for common query patterns.
-- All use IF NOT EXISTS so they're safe to re-run.

-- Matches: filtered by distributor + compliance status (dashboard, reports)
CREATE INDEX IF NOT EXISTS idx_matches_distributor_compliance
    ON matches (distributor_id, compliance_status);

-- Matches: filtered by distributor + created_at (trend charts, today counts)
CREATE INDEX IF NOT EXISTS idx_matches_distributor_created
    ON matches (distributor_id, created_at);

-- Scan jobs: filtered by org + status (active scan checks, plan enforcement)
CREATE INDEX IF NOT EXISTS idx_scan_jobs_org_status
    ON scan_jobs (organization_id, status);

-- Scan jobs: filtered by org + created_at (monthly quota counting)
CREATE INDEX IF NOT EXISTS idx_scan_jobs_org_created
    ON scan_jobs (organization_id, created_at);

-- Alerts: filtered by org + read status (unread badge, dashboard)
CREATE INDEX IF NOT EXISTS idx_alerts_org_read
    ON alerts (organization_id, is_read);

-- Discovered images: filtered by scan job + processed flag (reprocessing)
CREATE INDEX IF NOT EXISTS idx_discovered_images_job_processed
    ON discovered_images (scan_job_id, is_processed);

-- Assets: filtered by campaign (dashboard asset count, scan matching)
CREATE INDEX IF NOT EXISTS idx_assets_campaign
    ON assets (campaign_id);
