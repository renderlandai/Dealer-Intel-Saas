-- Update recent_matches view to include discovered image URL
-- This ensures we always have the image for visual comparison

CREATE OR REPLACE VIEW recent_matches AS
SELECT 
    m.*,
    a.name as asset_name,
    a.file_url as asset_url,
    d.name as distributor_name,
    c.name as campaign_name,
    -- Fallback to discovered_images.image_url if screenshot_url is null
    COALESCE(m.screenshot_url, di.image_url) as discovered_image_url
FROM matches m
LEFT JOIN assets a ON m.asset_id = a.id
LEFT JOIN distributors d ON m.distributor_id = d.id
LEFT JOIN campaigns c ON a.campaign_id = c.id
LEFT JOIN discovered_images di ON m.discovered_image_id = di.id
ORDER BY m.created_at DESC;









