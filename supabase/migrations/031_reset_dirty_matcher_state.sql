-- 2026-05-06 — Reset dirty database state from the BD-era / 6.5.x regression.
--
-- The Phase 6.5 (Bright Data swap) and 6.5.x phases auto-promoted many
-- hosts up the render-strategy ladder because BD wasn't extracting
-- images cleanly. After the rollback to eb48184 those promotions stuck:
-- the Python code was back at 4/29 but the database was still on 5/5,
-- so every blocked-host scan went straight to ScreenshotOne and into
-- the CV-localize confirmation-bias loop that produced 80% STRONG
-- MATCHES on navigation bars.
--
-- This migration is the database half of the recovery. The code half
-- lives in the same commit:
--   * cv_matching.template_match threshold 0.40 -> 0.70
--   * cv_matching.feature_match  min_good_matches 8 -> 18
--   * ai_service.process_discovered_image: asset_visible final gate
--   * ai_service.ensemble_match:           hash-veto on hallucinated visual
--   * ai_service.verify_borderline_match:  4-of-5 gates, compressed score curve
--   * ai_service strict prefilters for cv_localized_from_screenshot crops
--   * extraction_service.localize_screenshot_capture: feature-flagged OFF
--   * scan_runners page_hit_cache only learns STRONG-or-better matches
--
-- This script is IDEMPOTENT — safe to re-run.

-- 1) Reset every non-overridden host_scan_policy row back to the
--    default ladder. The next scan will re-probe each host via
--    `host_policy_service.preflight_probe`, so legitimately-blocked
--    Akamai/Cloudflare hosts will end up where they belong without
--    carrying the BD-era promotion forward.
UPDATE host_scan_policy
   SET strategy             = 'playwright_desktop',
       confidence            = 0,
       last_outcome          = NULL,
       last_block_reason     = NULL,
       last_http_status      = NULL,
       last_promoted_at      = NULL,
       updated_at            = now()
 WHERE manual_override = FALSE;

-- 2) Wipe the page_hit_cache. Any "hot" pages recorded during the
--    regression window were recorded because the matcher hallucinated
--    matches on them; replaying those pages on the next scan would just
--    re-mint the same false positives. Clearing the cache forces every
--    distributor's first post-fix scan to do full discovery, which is
--    the correct conservative behavior. Subsequent scans re-populate
--    the cache from the new (post-fix) match pipeline, which now
--    refuses to enter borderline (60-79) matches into the cache at all.
DELETE FROM page_hit_cache;

-- 3) Audit signal: surface counts so the operator can see what changed.
DO $$
DECLARE
  reset_hosts        INTEGER;
  remaining_overrides INTEGER;
BEGIN
  SELECT count(*) INTO reset_hosts
    FROM host_scan_policy
   WHERE strategy = 'playwright_desktop' AND confidence = 0;
  SELECT count(*) INTO remaining_overrides
    FROM host_scan_policy
   WHERE manual_override = TRUE;
  RAISE NOTICE
    'Matcher recovery: % host_scan_policy rows reset to default; % manual_override rows preserved; page_hit_cache truncated.',
    reset_hosts, remaining_overrides;
END $$;

-- PostgREST cache reload so supabase-py sees the updated rows immediately.
NOTIFY pgrst, 'reload schema';
