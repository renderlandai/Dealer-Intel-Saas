-- Phase 6.5 — replace ScreenshotOne strategies with Bright Data Web Unlocker.
--
-- Why
-- ---
-- The 2026-04-30 incident (zero discovered_images for rent.cat.com) was
-- traced to two compounding flaws:
--
--   1. ScreenshotOne does not actually offer a built-in residential proxy
--      option. The `proxy_type=residential` parameter we were sending got
--      a 400 on every call — silent failure across the whole ladder.
--   2. The `screenshotone_residential` ladder had a single rung. When that
--      rung 400'd there was no fallback, so a single broken provider
--      integration produced zero rows for every Akamai-protected dealer.
--
-- The structural fix is to replace SS1 with Bright Data Web Unlocker
-- (the actual product designed for "bypass any WAF") and to require every
-- ladder to have at least two rungs. The application code in
-- backend/app/services/render_strategies.py and unlocker_service.py
-- implements both halves of that fix; this migration bumps the SQL CHECK
-- constraint to match the new strategy set and migrates any existing
-- rows.
--
-- What this migration does
-- ------------------------
--   - Drops the old strategy CHECK so we can rewrite stored values.
--   - Maps every existing row to its new strategy:
--       playwright_then_screenshotone   -> playwright_then_unlocker
--       screenshotone_only              -> unlocker_only
--       screenshotone_residential       -> unlocker_only
--                                          (residential is now the default
--                                           for the unlocker rung; the
--                                           old "promote past everything"
--                                           rung becomes unreachable on
--                                           the next failure)
--   - Re-adds the CHECK with the new five-strategy enum.
--   - Idempotent: safe to re-run, safe on a fresh DB (no rows to migrate).

BEGIN;

ALTER TABLE host_scan_policy
    DROP CONSTRAINT IF EXISTS host_scan_policy_strategy_check;

UPDATE host_scan_policy
   SET strategy = 'playwright_then_unlocker'
 WHERE strategy = 'playwright_then_screenshotone';

UPDATE host_scan_policy
   SET strategy = 'unlocker_only'
 WHERE strategy IN ('screenshotone_only', 'screenshotone_residential');

ALTER TABLE host_scan_policy
    ADD CONSTRAINT host_scan_policy_strategy_check CHECK (
        strategy IN (
            'playwright_desktop',
            'playwright_mobile_first',
            'playwright_then_unlocker',
            'unlocker_only',
            'unreachable'
        )
    );

-- Reset the failure confidence on rows we just migrated so the first
-- post-migration scan starts with a clean slate. Otherwise a host that
-- was at confidence=1 with the old screenshotone_residential strategy
-- would auto-promote to `unreachable` after a single more failure even
-- though the new unlocker rung deserves a fresh chance.
UPDATE host_scan_policy
   SET confidence = 0,
       last_block_reason = COALESCE(last_block_reason, '') ||
                           ' [migrated to unlocker @ 2026-04-30]',
       updated_at = now()
 WHERE strategy IN ('playwright_then_unlocker', 'unlocker_only')
   AND last_block_reason IS NOT NULL
   AND last_block_reason NOT LIKE '%[migrated to unlocker%';

COMMENT ON COLUMN host_scan_policy.strategy IS
    'Render strategy for this hostname. Walked by services/render_strategies.run_ladder. Auto-promoted up PROMOTION_ORDER by host_policy_service.record_host_outcomes; pinned when manual_override=true.';

COMMIT;
