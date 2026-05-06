-- 2026-05-06 — Persist resolved Facebook numeric page IDs on distributors.
--
-- The whoareyouanas/meta-ad-scraper actor requires a numeric pageId
-- per dealer (it accepts only one search per run). Our distributor
-- table only stores Facebook URLs in slug form
-- (``facebook.com/<slug>``), and Facebook's logged-out HTML no longer
-- exposes the numeric ID to anonymous httpx/Playwright scraping.
--
-- Production logs from 2026-05-06 22:00 UTC show the unauthenticated
-- resolver missing on every single dealer — the Meta scan is
-- effectively dead until we have a reliable resolver.
--
-- The fix is two-layered:
--
--   1. (this migration) Add a column where we can persist the
--      numeric pageId once it has been resolved, plus a timestamp so
--      we can age out stale entries if Meta ever recycles IDs.
--
--   2. (apify_meta_service.py) Resolve via apify/facebook-pages-scraper
--      (a different actor specifically built for slug→pageId lookups,
--      $6.60/1000 pages, batched input) when the column is NULL.
--      Persist the result back here. Subsequent scans hit the cache
--      and pay zero resolver cost.
--
-- This script is IDEMPOTENT — safe to re-run; uses ``IF NOT EXISTS``
-- on every operation.

ALTER TABLE distributors
  ADD COLUMN IF NOT EXISTS facebook_page_id text,
  ADD COLUMN IF NOT EXISTS facebook_page_id_resolved_at timestamptz;

-- Lookup index for the resolver. Not unique because in rare cases
-- multiple distributor rows can share the same corporate Facebook
-- page (multi-location dealer groups), and a unique constraint
-- here would block scans on a constraint violation. The resolver
-- is read-mostly so a plain b-tree is the right shape.
CREATE INDEX IF NOT EXISTS idx_distributors_facebook_page_id
  ON distributors (facebook_page_id);

-- Comment so the column's purpose is self-documenting in psql / DDL
-- dumps. ``COMMENT ON`` is idempotent.
COMMENT ON COLUMN distributors.facebook_page_id IS
  'Numeric Facebook page ID resolved from the dealer''s page URL slug. '
  'Used by apify_meta_service to feed whoareyouanas/meta-ad-scraper, '
  'which requires a pageId rather than a slug. Resolved on first '
  'successful scan via apify/facebook-pages-scraper and cached here.';
COMMENT ON COLUMN distributors.facebook_page_id_resolved_at IS
  'When facebook_page_id was last successfully populated. Used to '
  'age out stale entries (currently no automatic invalidation; '
  're-resolve manually by setting both columns to NULL).';

-- PostgREST cache reload so supabase-py sees the new columns
-- immediately after the migration applies.
NOTIFY pgrst, 'reload schema';
