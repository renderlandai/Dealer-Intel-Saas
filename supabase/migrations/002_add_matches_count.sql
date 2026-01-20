-- Add matches_count column to scan_jobs table
-- This tracks the actual number of matches found during analysis
-- (as opposed to total_items which is the count of all discovered images)

ALTER TABLE scan_jobs ADD COLUMN IF NOT EXISTS matches_count INTEGER DEFAULT 0;

-- Add a comment explaining the difference
COMMENT ON COLUMN scan_jobs.total_items IS 'Total number of images discovered during the scan';
COMMENT ON COLUMN scan_jobs.matches_count IS 'Number of actual matches found against campaign assets';
COMMENT ON COLUMN scan_jobs.processed_items IS 'Number of images that have been analyzed';









