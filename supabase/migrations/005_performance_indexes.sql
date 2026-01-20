-- Migration: Add performance indexes for matches queries
-- This significantly speeds up the matches list and stats endpoints

-- Index for ORDER BY created_at DESC (used by recent_matches view)
CREATE INDEX IF NOT EXISTS idx_matches_created_at ON matches(created_at DESC);

-- Composite index for filtering by compliance_status + sorting by created_at
-- This optimizes the common "show violations sorted by date" query pattern
CREATE INDEX IF NOT EXISTS idx_matches_status_created ON matches(compliance_status, created_at DESC);

-- Composite index for match_type filtering + sorting
CREATE INDEX IF NOT EXISTS idx_matches_type_created ON matches(match_type, created_at DESC);

-- Function to get match stats efficiently using SQL aggregation
-- This replaces fetching all rows and aggregating in Python
CREATE OR REPLACE FUNCTION get_match_stats()
RETURNS JSON AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'total_matches', COUNT(*),
        'compliant', COUNT(*) FILTER (WHERE compliance_status = 'compliant'),
        'violations', COUNT(*) FILTER (WHERE compliance_status = 'violation'),
        'pending_review', COUNT(*) FILTER (WHERE compliance_status = 'pending'),
        'by_type', json_build_object(
            'exact', COUNT(*) FILTER (WHERE match_type = 'exact'),
            'strong', COUNT(*) FILTER (WHERE match_type = 'strong'),
            'partial', COUNT(*) FILTER (WHERE match_type = 'partial')
        ),
        'average_confidence', COALESCE(ROUND(AVG(confidence_score)::numeric, 2), 0),
        'compliance_rate', CASE 
            WHEN COUNT(*) > 0 THEN ROUND((COUNT(*) FILTER (WHERE compliance_status = 'compliant')::numeric / COUNT(*) * 100), 1)
            ELSE 0 
        END
    ) INTO result
    FROM matches;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;






