-- 2026-05-07 — Persist resolved Facebook page display NAME on distributors.
--
-- Why this exists:
--
-- Migration 032 added ``distributors.facebook_page_id`` (the numeric
-- page ID) on the assumption that the whoareyouanas/meta-ad-scraper
-- actor's ``view_all_page_id`` URL form is the right input shape.
-- It works for legacy Facebook *Page* entities, but on 2026-05-07
-- production scans we discovered that many of our dealers
-- (Yancey Rents, Carolina CAT, Altorfer Caterpillar, …) are not
-- Pages — they're profile-backed business accounts. Facebook's own
-- Open Graph tags expose this difference:
--
--   * Real Page:    al:android:url = "fb://page/?id=NNN"
--   * Profile-Page: al:android:url = "fb://profile/NNN"
--
-- For profile-backed accounts the slug-canonical numeric ID lives in
-- the *profile* graph namespace, not the *advertiser* namespace Ad
-- Library uses for ``view_all_page_id``. Pasting the profile ID into
-- the Ad Library URL returns "no ads match your search criteria"
-- regardless of how many active ads the dealer is actually running
-- (verified 2026-05-07 against Yancey Rents).
--
-- The fix is to switch the actor input from ``view_all_page_id=NNN``
-- to keyword-search mode (``q=<page name>&search_type=keyword_unordered``).
-- Keyword search works for both account types because Facebook's Ad
-- Library indexes by advertiser display name, not by the underlying
-- graph node ID. To make that switch we need the page's *display
-- name* on hand at scan time, not the numeric ID.
--
-- This migration adds the cache column. The resolver
-- (apify_meta_service.py) extracts the name from each page's
-- ``og:title`` meta tag (already loaded for the existing identity
-- check) at the same time it resolves the ID, persists both, and
-- prefers the name when building the actor URL.
--
-- This script is IDEMPOTENT — safe to re-run.

ALTER TABLE distributors
  ADD COLUMN IF NOT EXISTS facebook_page_name text;

COMMENT ON COLUMN distributors.facebook_page_name IS
  'Cached Facebook page display name extracted from the dealer''s '
  'page og:title meta tag (location suffix stripped). Used by '
  'apify_meta_service to build keyword-search Ad Library URLs of '
  'the form q=<name>&search_type=keyword_unordered for the '
  'whoareyouanas/meta-ad-scraper actor. Required because many of '
  'our dealers are profile-backed business accounts whose numeric '
  'IDs are not in the same namespace as Ad Library''s view_all_page_id.';

-- PostgREST cache reload so supabase-py sees the new column
-- immediately after the migration applies.
NOTIFY pgrst, 'reload schema';
