"""2026-05-07 — Regression tests for the curious_coder Meta-ads path.

Wired as a feature-flagged alternative to the
``whoareyouanas/meta-ad-scraper`` actor after a cost / recall review
of today's three-bug-day showed the current actor was costing ~13×
more per ad than the alternative AND missing ads on high-volume
dealers (DOM scroll-and-stall failure mode). See log.md
2026-05-07 entry "Feature flag: curious_coder/facebook-ads-library-
scraper as alternative actor" for the full review.

These tests lock in the behaviour of the seam helpers
(``_curious_coder_normalize``, ``_curious_coder_attribute_ads``,
``_curious_coder_build_input``, ``_is_curious_coder_active``) that
make the new path work without HTTP/network mocking. Higher-level
integration tests against ``_scan_meta_ads_curious_coder`` would
need the full Apify run-poll-fetch trio mocked; the seam tests here
catch every shape-mapping bug we've seen on the whoareyouanas side
(the ``imageUrls`` vs ``images``, ``adId`` vs ``libraryID``, and
empty-pageName failures) before they can ship.
"""
from __future__ import annotations

from unittest.mock import patch

from app.services.apify_meta_service import (
    CURIOUS_CODER_ACTOR_ID,
    WHOAREYOUANAS_ACTOR_ID,
    _curious_coder_attribute_ads,
    _curious_coder_build_input,
    _curious_coder_collect_creative_urls,
    _curious_coder_first,
    _curious_coder_normalize,
    _curious_coder_unix_to_iso,
    _is_curious_coder_active,
)


# ---------------------------------------------------------------------------
# _curious_coder_first — defensive multi-key reader
# ---------------------------------------------------------------------------

class TestCuriousCoderFirst:
    def test_first_present_key_wins(self):
        ad = {"pageId": "123", "pageID": "456"}
        assert _curious_coder_first(ad, "pageID", "pageId") == "456"

    def test_skips_empty_string(self):
        ad = {"pageID": "", "pageId": "123"}
        assert _curious_coder_first(ad, "pageID", "pageId") == "123"

    def test_skips_none(self):
        ad = {"pageID": None, "pageId": "123"}
        assert _curious_coder_first(ad, "pageID", "pageId") == "123"

    def test_returns_none_when_all_missing(self):
        assert _curious_coder_first({}, "pageID", "pageId") is None

    def test_zero_is_not_treated_as_missing(self):
        # Defensive: numeric zero counts as a real value (different
        # from "" / None). The actor doesn't actually emit 0 for any
        # field we care about, but locking this behaviour prevents
        # subtle bugs if it ever does.
        ad = {"isActive": 0}
        assert _curious_coder_first(ad, "isActive") == 0


# ---------------------------------------------------------------------------
# _curious_coder_unix_to_iso — date normalisation
# ---------------------------------------------------------------------------

class TestUnixToIso:
    def test_seconds_returns_iso(self):
        # 2024-01-15 12:00:00 UTC = 1705320000
        result = _curious_coder_unix_to_iso(1705320000)
        assert result.startswith("2024-01-15T12:00:00")
        assert "+00:00" in result

    def test_milliseconds_detected_and_converted(self):
        # 2024-01-15 12:00:00 UTC in ms = 1705320000000
        result = _curious_coder_unix_to_iso(1705320000000)
        assert result.startswith("2024-01-15T12:00:00")

    def test_string_numeric_accepted(self):
        result = _curious_coder_unix_to_iso("1705320000")
        assert result.startswith("2024-01-15T12:00:00")

    def test_empty_or_none_returns_empty(self):
        assert _curious_coder_unix_to_iso(None) == ""
        assert _curious_coder_unix_to_iso("") == ""

    def test_non_numeric_returns_verbatim(self):
        # If the actor ever ships an ISO string instead, just pass
        # it through.
        assert _curious_coder_unix_to_iso("2024-01-15") == "2024-01-15"


# ---------------------------------------------------------------------------
# _curious_coder_collect_creative_urls — image / video / format
# ---------------------------------------------------------------------------

class TestCollectCreativeUrls:
    def test_image_only(self):
        snapshot = {
            "images": [
                {"original_image_url": "https://x/o.jpg",
                 "resized_image_url": "https://x/r.jpg"},
            ],
            "videos": [],
            "cards": [],
        }
        images, videos, fmt = _curious_coder_collect_creative_urls(snapshot)
        # original_image_url is preferred over resized.
        assert images == ["https://x/o.jpg"]
        assert videos == []
        assert fmt == "image"

    def test_video_only(self):
        snapshot = {
            "videos": [
                {"video_hd_url": "https://x/hd.mp4",
                 "video_sd_url": "https://x/sd.mp4",
                 "video_preview_image_url": "https://x/p.jpg"},
            ],
        }
        images, videos, fmt = _curious_coder_collect_creative_urls(snapshot)
        assert images == []
        assert videos == ["https://x/hd.mp4"]  # HD preferred
        assert fmt == "video"

    def test_video_falls_back_to_preview_when_no_video_url(self):
        snapshot = {
            "videos": [
                {"video_preview_image_url": "https://x/preview.jpg"},
            ],
        }
        images, videos, fmt = _curious_coder_collect_creative_urls(snapshot)
        assert videos == ["https://x/preview.jpg"]

    def test_carousel_flattens_cards(self):
        snapshot = {
            "cards": [
                {"original_image_url": "https://x/a.jpg",
                 "title": "Card A"},
                {"image_url": "https://x/b.jpg", "title": "Card B"},
            ],
        }
        images, videos, fmt = _curious_coder_collect_creative_urls(snapshot)
        assert images == ["https://x/a.jpg", "https://x/b.jpg"]
        assert fmt == "carousel"

    def test_carousel_takes_precedence_over_image(self):
        # If both top-level images AND cards exist, format=carousel
        # because that's the dominant ad type signal.
        snapshot = {
            "images": [{"original_image_url": "https://x/main.jpg"}],
            "cards": [{"image_url": "https://x/card.jpg"}],
        }
        _images, _videos, fmt = _curious_coder_collect_creative_urls(snapshot)
        assert fmt == "carousel"

    def test_empty_snapshot_returns_empties(self):
        images, videos, fmt = _curious_coder_collect_creative_urls({})
        assert images == [] and videos == [] and fmt == ""

    def test_invalid_snapshot_type_returns_empties(self):
        # Defensive — actor sometimes ships ``snapshot=null`` for
        # ads that didn't render.
        images, videos, fmt = _curious_coder_collect_creative_urls(None)
        assert images == [] and videos == [] and fmt == ""

    def test_invalid_url_strings_dropped(self):
        # Non-http strings (like "data:image/...") get skipped.
        snapshot = {
            "images": [
                {"original_image_url": "data:image/jpg;base64,abc"},
                {"original_image_url": "https://x/ok.jpg"},
            ],
        }
        images, _, _ = _curious_coder_collect_creative_urls(snapshot)
        assert images == ["https://x/ok.jpg"]


# ---------------------------------------------------------------------------
# _curious_coder_normalize — full-shape mapping
# ---------------------------------------------------------------------------

class TestCuriousCoderNormalize:
    def _make_raw_ad(self, **overrides):
        # Realistic curious_coder payload shape based on the actor's
        # README field table + observed schema across the actor's
        # 24,730 users / 100% success-rate runs.
        base = {
            "adArchiveID": "1234567890",
            "pageID": "108047081396228",
            "pageName": "Yancey Rents",
            "isActive": True,
            "startDate": 1705320000,
            "endDate": None,
            "publisherPlatform": ["FACEBOOK", "INSTAGRAM"],
            "snapshot": {
                "body": {"text": "Rent the Cat machine you need today."},
                "title": "Yancey Rents",
                "link_url": "https://yanceyrents.com/equipment",
                "cta_text": "Learn More",
                "cta_type": "LEARN_MORE",
                "images": [
                    {"original_image_url": "https://scontent/o.jpg",
                     "resized_image_url": "https://scontent/r.jpg"},
                ],
                "videos": [],
                "cards": [],
            },
            "currency": "USD",
        }
        base.update(overrides)
        return base

    def test_canonical_fields_populated(self):
        canonical = _curious_coder_normalize(self._make_raw_ad())
        assert canonical["adId"] == "1234567890"
        assert canonical["pageName"] == "Yancey Rents"
        assert canonical["brand"] == "Yancey Rents"
        assert canonical["pageID"] == "108047081396228"
        assert canonical["active"] is True
        assert canonical["platforms"] == ["facebook", "instagram"]
        assert canonical["format"] == "image"
        assert canonical["imageUrls"] == [
            {"url": "https://scontent/o.jpg"}
        ]
        assert canonical["videoUrls"] == []
        assert canonical["body"] == "Rent the Cat machine you need today."
        assert canonical["linkTitle"] == "Yancey Rents"
        assert canonical["linkUrl"] == "https://yanceyrents.com/equipment"
        assert canonical["ctaText"] == "Learn More"
        assert canonical["adUrl"] == (
            "https://www.facebook.com/ads/library/?id=1234567890"
        )
        assert canonical["_curious_coder"] is True

    def test_iso_start_date(self):
        canonical = _curious_coder_normalize(self._make_raw_ad())
        assert canonical["startDate"].startswith("2024-01-15T12:00:00")

    def test_alternative_id_field_names(self):
        # Some actor builds ship adID instead of adArchiveID.
        ad = self._make_raw_ad()
        del ad["adArchiveID"]
        ad["adID"] = "alt-id-form"
        canonical = _curious_coder_normalize(ad)
        assert canonical["adId"] == "alt-id-form"

    def test_alternative_pageid_field_names(self):
        ad = self._make_raw_ad()
        del ad["pageID"]
        ad["pageId"] = "lowercase-d-form"
        canonical = _curious_coder_normalize(ad)
        assert canonical["pageID"] == "lowercase-d-form"

    def test_body_as_plain_string(self):
        # Older actor builds emit body as a plain string (not
        # {"text": "..."}). The downstream uses .get("body") so we
        # must produce a string regardless.
        ad = self._make_raw_ad()
        ad["snapshot"]["body"] = "Plain string body"
        canonical = _curious_coder_normalize(ad)
        assert canonical["body"] == "Plain string body"

    def test_inactive_ad(self):
        ad = self._make_raw_ad(isActive=False)
        canonical = _curious_coder_normalize(ad)
        assert canonical["active"] is False

    def test_carousel_ad_format(self):
        ad = self._make_raw_ad()
        ad["snapshot"] = {
            "body": {"text": "Multi-card promo"},
            "cards": [
                {"original_image_url": "https://x/a.jpg",
                 "title": "A"},
                {"original_image_url": "https://x/b.jpg",
                 "title": "B"},
            ],
        }
        canonical = _curious_coder_normalize(ad)
        assert canonical["format"] == "carousel"
        assert canonical["imageUrls"] == [
            {"url": "https://x/a.jpg"},
            {"url": "https://x/b.jpg"},
        ]

    def test_video_ad_format(self):
        ad = self._make_raw_ad()
        ad["snapshot"]["images"] = []
        ad["snapshot"]["videos"] = [
            {"video_hd_url": "https://x/hd.mp4",
             "video_preview_image_url": "https://x/p.jpg"},
        ]
        canonical = _curious_coder_normalize(ad)
        assert canonical["format"] == "video"
        assert canonical["videoUrls"] == [{"url": "https://x/hd.mp4"}]

    def test_missing_snapshot(self):
        # The actor occasionally ships ads with snapshot=null for
        # campaigns that fully-finished — still need to produce a
        # valid canonical shape (downstream image-fallback path
        # handles the no-image case).
        ad = self._make_raw_ad()
        ad["snapshot"] = None
        canonical = _curious_coder_normalize(ad)
        assert canonical["adId"] == "1234567890"
        assert canonical["imageUrls"] == []
        assert canonical["videoUrls"] == []
        assert canonical["body"] == ""

    def test_empty_platforms(self):
        ad = self._make_raw_ad()
        ad["publisherPlatform"] = []
        canonical = _curious_coder_normalize(ad)
        assert canonical["platforms"] == []

    def test_no_archive_id_yields_empty_adurl(self):
        # If the actor somehow ships an ad with no identifier, we
        # produce empty adUrl rather than a malformed Ad Library link.
        # The downstream insertion loop drops such ads as having no
        # library_id.
        ad = self._make_raw_ad()
        del ad["adArchiveID"]
        canonical = _curious_coder_normalize(ad)
        assert canonical["adId"] == ""
        assert canonical["adUrl"] == ""


# ---------------------------------------------------------------------------
# _curious_coder_attribute_ads — pageName → source URL mapping
# ---------------------------------------------------------------------------

class TestCuriousCoderAttribution:
    def test_exact_slug_match(self):
        ads = [{"pageName": "yanceyrents", "adId": "1"}]
        page_urls = [
            "https://www.facebook.com/YanceyRents/",
            "https://www.facebook.com/CarolinaCAT/",
        ]
        out = _curious_coder_attribute_ads(ads, page_urls, {})
        assert len(out) == 1
        assert out[0][0] == "https://www.facebook.com/YanceyRents/"

    def test_substring_match_name_to_slug(self):
        # pageName="Yancey Rents - The Cat Rental Store"
        # slug="yanceyrents" — slug-norm "yanceyrents" is a substring
        # of name-norm "yanceyrentsthecatrentalstore".
        ads = [{
            "pageName": "Yancey Rents - The Cat Rental Store",
            "adId": "1",
        }]
        page_urls = [
            "https://www.facebook.com/CarolinaCAT/",
            "https://www.facebook.com/YanceyRents/",
        ]
        out = _curious_coder_attribute_ads(ads, page_urls, {})
        assert out[0][0] == "https://www.facebook.com/YanceyRents/"

    def test_substring_match_slug_to_name(self):
        # Reverse: pageName="Yancey" is shorter than slug
        # "yanceyrents" — name-norm "yancey" is a substring of
        # slug-norm "yanceyrents".
        ads = [{"pageName": "Yancey", "adId": "1"}]
        page_urls = [
            "https://www.facebook.com/CarolinaCAT/",
            "https://www.facebook.com/YanceyRents/",
        ]
        out = _curious_coder_attribute_ads(ads, page_urls, {})
        assert out[0][0] == "https://www.facebook.com/YanceyRents/"

    def test_unmatched_falls_through_to_first(self):
        # Foreign advertiser collision — fall through to the first
        # input URL. Downstream brand-fallback / matcher veto is
        # what keeps this from polluting results.
        ads = [{"pageName": "Some Random LLC", "adId": "1"}]
        page_urls = [
            "https://www.facebook.com/YanceyRents/",
            "https://www.facebook.com/CarolinaCAT/",
        ]
        out = _curious_coder_attribute_ads(ads, page_urls, {})
        assert out[0][0] == "https://www.facebook.com/YanceyRents/"

    def test_multiple_ads_attributed_separately(self):
        ads = [
            {"pageName": "Yancey Rents", "adId": "1"},
            {"pageName": "Carolina CAT", "adId": "2"},
            {"pageName": "Yancey Rents", "adId": "3"},
        ]
        page_urls = [
            "https://www.facebook.com/YanceyRents/",
            "https://www.facebook.com/CarolinaCAT/",
        ]
        out = _curious_coder_attribute_ads(ads, page_urls, {})
        sources = [src for src, _ in out]
        assert sources == [
            "https://www.facebook.com/YanceyRents/",
            "https://www.facebook.com/CarolinaCAT/",
            "https://www.facebook.com/YanceyRents/",
        ]

    def test_empty_pagename_falls_through(self):
        # Like the whoareyouanas post-filter fail-open case — if the
        # actor extraction failed and pageName is empty, we just
        # pass the ad through to the first dealer rather than dropping
        # it. The matcher pipeline will reject foreign ads on visual
        # similarity grounds.
        ads = [{"pageName": "", "adId": "1"}]
        page_urls = ["https://www.facebook.com/YanceyRents/"]
        out = _curious_coder_attribute_ads(ads, page_urls, {})
        assert len(out) == 1
        assert out[0][0] == "https://www.facebook.com/YanceyRents/"

    def test_empty_inputs_return_empty(self):
        assert _curious_coder_attribute_ads([], ["x"], {}) == []
        assert _curious_coder_attribute_ads([{"adId": "1"}], [], {}) == []


# ---------------------------------------------------------------------------
# _curious_coder_build_input — actor input shape
# ---------------------------------------------------------------------------

class TestCuriousCoderBuildInput:
    def test_basic_shape(self):
        body = _curious_coder_build_input(
            ["https://www.facebook.com/YanceyRents/"],
        )
        assert body["urls"] == [
            {"url": "https://www.facebook.com/YanceyRents"},
        ]
        assert body["scrapeAdDetails"] is True
        assert body["scrapePageAds.activeStatus"] == "active"
        assert body["scrapePageAds.countryCode"] == "US"
        assert body["scrapePageAds.sortBy"] == "most_recent"
        # No cap by default — full-recall mode.
        assert "limitPerSource" not in body

    def test_normalises_bare_slugs(self):
        # ``_normalize_fb_url`` turns slug-only inputs into full URLs.
        body = _curious_coder_build_input(["yanceyrents"])
        assert body["urls"][0]["url"].startswith("https://www.facebook.com/")

    def test_limit_per_source_applied_when_set(self):
        body = _curious_coder_build_input(
            ["https://www.facebook.com/YanceyRents/"],
            limit_per_source=200,
        )
        assert body["limitPerSource"] == 200

    def test_country_and_status_pluged_through(self):
        body = _curious_coder_build_input(
            ["https://www.facebook.com/YanceyRents/"],
            country="GB",
            active_status="all",
        )
        assert body["scrapePageAds.countryCode"] == "GB"
        assert body["scrapePageAds.activeStatus"] == "all"

    def test_multiple_urls(self):
        body = _curious_coder_build_input([
            "https://www.facebook.com/YanceyRents/",
            "https://www.facebook.com/CarolinaCAT/",
            "https://www.facebook.com/AltorferCaterpillar/",
        ])
        assert len(body["urls"]) == 3


# ---------------------------------------------------------------------------
# _is_curious_coder_active — dispatcher predicate
# ---------------------------------------------------------------------------

class TestActorDispatch:
    def test_default_is_whoareyouanas(self):
        # Default config means whoareyouanas, NOT curious_coder.
        # Production safety: the swap must be opt-in.
        with patch(
            "app.services.apify_meta_service.settings",
        ) as mock_settings:
            mock_settings.apify_meta_actor_id = WHOAREYOUANAS_ACTOR_ID
            assert not _is_curious_coder_active()

    def test_curious_coder_canonical_form(self):
        with patch(
            "app.services.apify_meta_service.settings",
        ) as mock_settings:
            mock_settings.apify_meta_actor_id = CURIOUS_CODER_ACTOR_ID
            assert _is_curious_coder_active()

    def test_curious_coder_publication_form_tolerated(self):
        # Operators who copy/paste the slug from Apify's website get
        # the slash form. We accept it without forcing them to know
        # about the tilde quirk.
        with patch(
            "app.services.apify_meta_service.settings",
        ) as mock_settings:
            mock_settings.apify_meta_actor_id = (
                "curious_coder/facebook-ads-library-scraper"
            )
            assert _is_curious_coder_active()

    def test_curious_coder_with_whitespace(self):
        with patch(
            "app.services.apify_meta_service.settings",
        ) as mock_settings:
            mock_settings.apify_meta_actor_id = (
                f"  {CURIOUS_CODER_ACTOR_ID}  "
            )
            assert _is_curious_coder_active()

    def test_unknown_actor_falls_back_to_whoareyouanas(self):
        # Typo'd actor id → not curious_coder → whoareyouanas path.
        with patch(
            "app.services.apify_meta_service.settings",
        ) as mock_settings:
            mock_settings.apify_meta_actor_id = "some_other/actor"
            assert not _is_curious_coder_active()

    def test_empty_actor_id_falls_back_to_whoareyouanas(self):
        # Defensive — env unset or blank shouldn't activate the
        # alternative path.
        with patch(
            "app.services.apify_meta_service.settings",
        ) as mock_settings:
            mock_settings.apify_meta_actor_id = ""
            assert not _is_curious_coder_active()
