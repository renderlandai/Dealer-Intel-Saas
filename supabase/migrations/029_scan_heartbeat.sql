-- Phase 5 (minimal worker) prerequisite: per-scan heartbeat column.
--
-- Today `services/scheduler_service._cleanup_stale_scans` auto-fails any
-- `scan_jobs` row that has been in `running` status longer than its
-- `created_at` window. With the per-page heartbeat re-instated (see
-- `services/scan_runners._heartbeat`), a long-but-healthy scan stays alive
-- because it stamps `last_heartbeat_at` every page. Cleanup keys off the
-- heartbeat (with a fall-back to `created_at` for older rows that never
-- wrote one), so the 4-hour cutoff only fires on actually-stuck scans.
--
-- Why a new column instead of reusing `started_at`:
--   * `started_at` is the single source of truth for "when did work begin"
--     and is read by the dashboard. Bumping it on every page would corrupt
--     scan-duration metrics and the original 2026-04-01 bug that took
--     `_heartbeat()` out of service in the first place.
--   * `updated_at` does not exist on `scan_jobs` — it was never added when
--     the table was first created (see supabase/schema.sql:86).
--
-- Backfill: existing rows get NULL; the cleanup query treats NULL as "use
-- created_at" so nothing changes for historical jobs.

ALTER TABLE scan_jobs
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;

COMMENT ON COLUMN scan_jobs.last_heartbeat_at IS
    'Updated by the scan runner once per page (and at major phase boundaries). The cleanup job uses this column instead of started_at so long but healthy scans are not auto-failed.';

-- Composite index used by `_cleanup_stale_scans` to find stuck running rows.
-- Status is highly selective once filtered to `running`/`analyzing`, and
-- the time predicate is what determines the row count returned.
CREATE INDEX IF NOT EXISTS idx_scan_jobs_status_heartbeat
    ON scan_jobs(status, last_heartbeat_at);

-- PostgREST schema cache must be refreshed before the new column is visible
-- to the supabase-py client. Migration 028 hit this exact gotcha; do it
-- proactively here.
NOTIFY pgrst, 'reload schema';
