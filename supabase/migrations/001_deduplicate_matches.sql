-- Migration: Fix recent_matches view
-- NOTE: Do NOT delete data - the backend code handles deduplication on insert

-- Simple fast view (no deduplication needed - backend prevents duplicates)
CREATE OR REPLACE VIEW recent_matches AS
SELECT 
    m.*,
    a.name as asset_name,
    a.file_url as asset_url,
    d.name as distributor_name,
    c.name as campaign_name
FROM matches m
LEFT JOIN assets a ON m.asset_id = a.id
LEFT JOIN distributors d ON m.distributor_id = d.id
LEFT JOIN campaigns c ON a.campaign_id = c.id
ORDER BY m.created_at DESC;
