-- Add pipeline_stats JSONB column to scan_jobs table.
-- Stores per-stage funnel counts from the image analysis pipeline:
--   total_images, download_failed, hash_rejected, clip_rejected,
--   filter_rejected, below_threshold, verification_rejected,
--   matched, duplicates_skipped, errors.

ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS pipeline_stats JSONB DEFAULT NULL;

COMMENT ON COLUMN scan_jobs.pipeline_stats IS 'Per-stage funnel stats from the AI matching pipeline';
