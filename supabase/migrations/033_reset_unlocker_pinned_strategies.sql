-- 033_reset_unlocker_pinned_strategies.sql
--
-- Phase 6.5.9 — one-shot demote of host_scan_policy rows that were
-- auto-promoted to BD-only strategies during the 6.5 rollout.
--
-- Background. The auto-promotion logic in `host_policy_service.record_host_outcomes`
-- bumps a host one rung up the ladder after `PROMOTE_THRESHOLD = 2`
-- consecutive scans where every probed page produced a non-success
-- outcome. There is no symmetric auto-demote — a host that fails twice
-- is parked on `unlocker_only` (or worse, `unreachable`) forever, and
-- daily scans for those dealers stop attempting Playwright entirely.
--
-- During the 6.5 BD rollout a number of healthy hosts caught two bad
-- scans for unrelated reasons (Playwright OOMs, DAM URL regressions,
-- the AEM template-href bug fixed in 6.5.3) and got pinned to
-- `unlocker_only`. With 6.5.9 flipping the BD asset-fetch and BD
-- discovery defaults off, the next ladder run for those hosts is
-- intended to be Playwright-first again. This migration resets the
-- pinned rows so the runner re-learns from current evidence rather
-- than from the 6.5-era false-positives.
--
-- Manual overrides (`manual_override = true`) are preserved — those
-- rows were set by an operator and the system should not silently
-- undo them. Hosts already on `playwright_desktop` /
-- `playwright_mobile_first` / `playwright_then_unlocker` are left
-- alone; only the two BD-pinned strategies (`unlocker_only`,
-- `unreachable`) are demoted.

UPDATE host_scan_policy
SET
    strategy = 'playwright_desktop',
    confidence = 0,
    last_outcome = NULL,
    updated_at = NOW()
WHERE
    strategy IN ('unlocker_only', 'unreachable')
    AND COALESCE(manual_override, FALSE) = FALSE;

-- Reporting comment so the migration log shows the count without
-- needing a separate observability query. PostgreSQL will print the
-- UPDATE row count in the migration runner's output.
