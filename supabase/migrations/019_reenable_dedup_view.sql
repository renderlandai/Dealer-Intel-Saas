-- Re-enable deduplication in the recent_matches view.
-- Shows only the highest-confidence match per (asset_id, distributor_id),
-- keeping the most recently seen row as the tiebreaker.
-- Uses COALESCE with match id to prevent NULL asset/distributor rows
-- from being collapsed into a single group.

DROP VIEW IF EXISTS recent_matches;

CREATE VIEW recent_matches AS
WITH ranked AS (
    SELECT
        m.*,
        a.name        AS asset_name,
        a.file_url    AS asset_url,
        d.name        AS distributor_name,
        c.name        AS campaign_name,
        COALESCE(m.screenshot_url, di.image_url) AS discovered_image_url,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(m.asset_id, m.id), COALESCE(m.distributor_id, m.id)
            ORDER BY m.confidence_score DESC, m.last_seen_at DESC NULLS LAST, m.created_at DESC
        ) AS rn
    FROM matches m
    LEFT JOIN assets a             ON m.asset_id = a.id
    LEFT JOIN distributors d       ON m.distributor_id = d.id
    LEFT JOIN campaigns c          ON a.campaign_id = c.id
    LEFT JOIN discovered_images di ON m.discovered_image_id = di.id
)
SELECT
    id, asset_id, discovered_image_id, distributor_id,
    confidence_score, match_type, is_modified, modifications,
    channel, source_url, screenshot_url, discovered_at,
    compliance_status, compliance_issues, ai_analysis,
    created_at, reviewed_at, reviewed_by,
    last_seen_at, scan_count, previous_compliance_status,
    asset_name, asset_url, distributor_name, campaign_name,
    discovered_image_url
FROM ranked
WHERE rn = 1
ORDER BY created_at DESC;
