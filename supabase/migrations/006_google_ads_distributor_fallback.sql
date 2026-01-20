-- Migration: Add fallback distributor lookup for Google Ads matches
-- When distributor_id is null but the match is from google_ads channel,
-- look up the distributor by matching advertiser_id from discovered_images metadata

CREATE OR REPLACE VIEW recent_matches AS
SELECT 
    m.*,
    a.name as asset_name,
    a.file_url as asset_url,
    -- Fallback: if no direct distributor link, try to match via Google Ads advertiser_id
    COALESCE(
        d.name, 
        d_fallback.name
    ) as distributor_name,
    c.name as campaign_name,
    -- Fallback to discovered_images.image_url if screenshot_url is null
    COALESCE(m.screenshot_url, di.image_url) as discovered_image_url
FROM matches m
LEFT JOIN assets a ON m.asset_id = a.id
LEFT JOIN distributors d ON m.distributor_id = d.id
LEFT JOIN campaigns c ON a.campaign_id = c.id
LEFT JOIN discovered_images di ON m.discovered_image_id = di.id
-- Fallback join: match Google Ads advertiser_id from metadata to distributor's google_ads_advertiser_id
LEFT JOIN distributors d_fallback ON (
    m.distributor_id IS NULL 
    AND m.channel = 'google_ads'
    AND di.metadata->>'advertiser_id' IS NOT NULL
    AND (
        LOWER(d_fallback.google_ads_advertiser_id) = LOWER(di.metadata->>'advertiser_id')
    )
)
ORDER BY m.created_at DESC;


-- Also create a function to bulk-link orphaned Google Ads matches
-- This can be called to fix existing data
CREATE OR REPLACE FUNCTION link_google_ads_matches()
RETURNS TABLE(updated_count INTEGER, total_orphans INTEGER) AS $$
DECLARE
    v_updated INTEGER := 0;
    v_total INTEGER := 0;
BEGIN
    -- Count orphans
    SELECT COUNT(*) INTO v_total
    FROM matches m
    WHERE m.channel = 'google_ads' AND m.distributor_id IS NULL;
    
    -- Update matches by joining through discovered_images metadata
    WITH updates AS (
        UPDATE matches m
        SET distributor_id = d.id
        FROM discovered_images di, distributors d
        WHERE m.discovered_image_id = di.id
          AND m.channel = 'google_ads'
          AND m.distributor_id IS NULL
          AND di.metadata->>'advertiser_id' IS NOT NULL
          AND LOWER(d.google_ads_advertiser_id) = LOWER(di.metadata->>'advertiser_id')
        RETURNING m.id
    )
    SELECT COUNT(*) INTO v_updated FROM updates;
    
    -- Also update discovered_images that are missing distributor_id
    UPDATE discovered_images di
    SET distributor_id = d.id
    FROM distributors d
    WHERE di.channel = 'google_ads'
      AND di.distributor_id IS NULL
      AND di.metadata->>'advertiser_id' IS NOT NULL
      AND LOWER(d.google_ads_advertiser_id) = LOWER(di.metadata->>'advertiser_id');
    
    RETURN QUERY SELECT v_updated, v_total;
END;
$$ LANGUAGE plpgsql;

