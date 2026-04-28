-- Allow creatives (assets) to declare which channels they actually run on.
--
-- Today every asset is fed into every source scan (Google Ads, Facebook,
-- Instagram, Website, YouTube), which is wasteful and produces false
-- positives when an Instagram-only graphic happens to resemble a website
-- hero. Tagging assets with their target platforms lets the scan runner
-- filter the candidate set per source and turns "appeared on a channel I
-- wasn't approved for" into a first-class compliance signal.
--
-- Backwards compatibility rule (enforced in code): an EMPTY array means
-- "all channels". Existing rows default to '{}' so behaviour is unchanged
-- until users start tagging.
--
-- Allowed values mirror app.models.ScanSource:
--   google_ads | facebook | instagram | youtube | website

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS target_platforms TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

COMMENT ON COLUMN assets.target_platforms IS
    'Channels this creative is approved for. Empty array = all channels. Values: google_ads, facebook, instagram, youtube, website.';

-- GIN index so per-source scan queries (`target_platforms && ARRAY['facebook']`)
-- stay fast even on orgs with thousands of creatives.
CREATE INDEX IF NOT EXISTS idx_assets_target_platforms
    ON assets USING GIN (target_platforms);
