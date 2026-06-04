-- Phase-8 (2026-05-08): forward-compatible scaffolding for per-dealer
-- scan subjobs. Today the runner persists per-dealer outcome telemetry
-- inside `scan_jobs.pipeline_stats.dealer_outcomes`, which is enough for
-- the UI to show "8 of 10 dealers complete" partial-success states. A
-- follow-up PR will flip the scheduler / worker into a fan-out mode that
-- creates one child `scan_jobs` row per dealer and rolls them up to a
-- parent — at which point these columns become the wiring that supports
-- it without another migration.
--
-- Adding the columns now (instead of later) means:
--   * existing dispatch + cleanup logic continues to work unchanged;
--     `parent_scan_job_id` is NULL for every legacy row.
--   * the worker's atomic-claim query in `app/worker.py` does not need
--     to change — it claims any `pending` row, which now happens to
--     include children.
--   * the cleanup job's heartbeat-staleness check applies uniformly to
--     parent and child rows alike (a parent that lost its watcher is
--     just as stuck as a child whose worker died).
--
-- Why store `target_url` on the child:
--   The current runners receive the dealer URL list as a function arg
--   in their `metadata.dispatch.args`. To make a child row independently
--   replayable without reaching back to the parent's dispatch args, we
--   denormalise the dealer URL onto the row. `distributor_id` is the
--   same idea — it lets per-dealer joins ("show me every scan we've run
--   against Mustang CAT") work without an extra hop.

ALTER TABLE scan_jobs
    ADD COLUMN IF NOT EXISTS parent_scan_job_id UUID
        REFERENCES scan_jobs(id) ON DELETE CASCADE;

ALTER TABLE scan_jobs
    ADD COLUMN IF NOT EXISTS target_url TEXT;

ALTER TABLE scan_jobs
    ADD COLUMN IF NOT EXISTS distributor_id UUID
        REFERENCES distributors(id) ON DELETE SET NULL;

COMMENT ON COLUMN scan_jobs.parent_scan_job_id IS
    'Optional pointer at the rolled-up parent scan when this row is a per-dealer subjob. NULL on legacy single-row scans.';

COMMENT ON COLUMN scan_jobs.target_url IS
    'For per-dealer subjobs: the single dealer URL this row scans. NULL on parent / single-row scans.';

COMMENT ON COLUMN scan_jobs.distributor_id IS
    'For per-dealer subjobs: the distributor whose channel this row scans. NULL on parent / single-row scans.';

-- The cleanup job and dashboard list both filter by status; the parent
-- column is highly selective for the "show children of this parent"
-- query the rollup watcher will run.
CREATE INDEX IF NOT EXISTS idx_scan_jobs_parent
    ON scan_jobs(parent_scan_job_id)
    WHERE parent_scan_job_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_scan_jobs_distributor
    ON scan_jobs(distributor_id)
    WHERE distributor_id IS NOT NULL;

-- PostgREST schema cache must be refreshed before the new columns are
-- visible to the supabase-py client. Migration 028 / 029 hit this same
-- gotcha; do it proactively here too.
NOTIFY pgrst, 'reload schema';
