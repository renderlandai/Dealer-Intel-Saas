-- 2026-05-07 — Clear poisoned facebook_page_id values written by the
-- loose-regex tier-4 resolver (commit 61727ee, deployed earlier today).
--
-- That resolver fell through to non-page-typed regex patterns
-- ("actorID", "entity_id", "page_id", "profile_id", /profile.php?id=)
-- when the page-typed deep-link patterns missed, and ended up
-- persisting numeric IDs that were not actually Facebook Page IDs —
-- they were viewer session IDs, user IDs, or unrelated entities
-- embedded in the rendered DOM of a logged-out wall.
--
-- Production verification: feeding one of those IDs to the
-- whoareyouanas/meta-ad-scraper produced an Ad Library page where
-- the transparency block read literally "ID: undefined" (Meta's
-- signal that the supplied view_all_page_id is not a Page entity in
-- their graph). Apify run completed cleanly with 0 ads found.
--
-- The follow-up code change (commit shipping with this migration)
-- tightens the regex set to four page-typed patterns and adds an
-- identity check (og:url canonical slug must match the input slug)
-- before persisting any resolved ID. With those guards in place,
-- the only safe path forward is to wipe every existing cached value
-- and force re-resolution with the new strict resolver. Dealers
-- whose pages won't render cleanly to anonymous Playwright will
-- skip-with-warning rather than poison the cache again.
--
-- Idempotent. If migration 032 hasn't been applied yet, this is a
-- no-op (the column doesn't exist yet, so there's nothing to
-- clear). Re-running after every value is already NULL is also a
-- no-op.

DO $$
DECLARE
  cleared_count INTEGER := 0;
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'distributors'
      AND column_name = 'facebook_page_id'
  ) THEN
    UPDATE distributors
       SET facebook_page_id = NULL,
           facebook_page_id_resolved_at = NULL
     WHERE facebook_page_id IS NOT NULL;
    GET DIAGNOSTICS cleared_count = ROW_COUNT;
    RAISE NOTICE
      'Cleared % poisoned facebook_page_id value(s); next Meta scan '
      'will re-resolve every dealer with the strict-regex + identity-'
      'check resolver.', cleared_count;
  ELSE
    RAISE NOTICE
      'distributors.facebook_page_id column does not exist — '
      'migration 032 has not been applied yet; nothing to clean.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
