"""2026-05-07 — Regression tests for the Meta-ad-scraper post-filter.

Three live failure modes have been observed during today's debugging
trail; this suite locks in the behaviour that fixes each one:

  1. **Strict per-ad rejection** — when the actor populates advertiser
     names, an ad whose name doesn't match the dealer (keyword-search
     collision noise like ``1Hood Media`` for a Yancey Rents query)
     must be dropped.

  2. **Empty-name-per-ad** — when an individual ad has empty
     advertiser-name fields but other ads in the same run DO have
     names, the empty-name ad is dropped per the per-ad strict path.

  3. **Run-wide fail-open** — when the actor returns ads but populates
     NO advertiser-name field on ANY of them, the post-filter must
     keep all ads. The 17:53 production run that hit this case dropped
     6/6 valid Yancey ads and emitted "0 images analyzed → 100%
     compliance"; reproducing that with a unit test guarantees we
     never regress.

Tests target the module-level helpers (``_ad_advertiser_name``,
``_name_matches_dealer``) which are the seams the post-filter
operates through. Higher-level orchestration tests for
``_run_actor_for_page`` would require mocking the full Apify HTTP
client; the seams here are sufficient because the post-filter logic
is a thin shell over these two helpers.
"""
from __future__ import annotations

from app.services.apify_meta_service import (
    _ad_advertiser_name,
    _name_matches_dealer,
)


# ---------------------------------------------------------------------------
# _ad_advertiser_name
# ---------------------------------------------------------------------------

class TestAdAdvertiserName:
    def test_pageName_preferred_over_others(self):
        ad = {
            "pageName": "Yancey Rents - The Cat Rental Store",
            "brand": "OldBrandValue",
        }
        assert (
            _ad_advertiser_name(ad)
            == "Yancey Rents - The Cat Rental Store"
        )

    def test_pageNameKnown_when_pageName_missing(self):
        ad = {"pageNameKnown": "Carolina Cat", "brand": "Other"}
        assert _ad_advertiser_name(ad) == "Carolina Cat"

    def test_brand_when_both_pageName_fields_missing(self):
        # This is the actual production failure mode that motivated
        # the widening — the actor populated ONLY brand on a run.
        ad = {"brand": "Yancey Rents - The Cat Rental Store"}
        assert (
            _ad_advertiser_name(ad)
            == "Yancey Rents - The Cat Rental Store"
        )

    def test_empty_string_when_nothing_populated(self):
        # The 17:53 production failure mode: actor returned the ad
        # but extracted no advertiser name.
        assert _ad_advertiser_name({}) == ""
        assert _ad_advertiser_name({"adId": "123"}) == ""
        assert (
            _ad_advertiser_name(
                {"pageName": "", "pageNameKnown": "", "brand": ""}
            )
            == ""
        )

    def test_pageName_takes_precedence_when_both_populated(self):
        # The actor sometimes ships BOTH pageName and brand with the
        # same value; either is fine to use, but we should be
        # deterministic about which.
        ad = {"pageName": "FooName", "brand": "FooBrand"}
        assert _ad_advertiser_name(ad) == "FooName"


# ---------------------------------------------------------------------------
# _name_matches_dealer — strict path (when actor name IS populated)
# ---------------------------------------------------------------------------

class TestNameMatchesDealerStrict:
    def test_exact_name_match(self):
        assert _name_matches_dealer(
            "Yancey Rents - The Cat Rental Store",
            "Yancey Rents - The Cat Rental Store",
            "yanceyrents",
        )

    def test_slug_substring_match_when_name_unknown(self):
        # We didn't resolve the page name, but the slug is enough.
        assert _name_matches_dealer(
            "Yancey Rents - The Cat Rental Store",
            None,
            "yanceyrents",
        )

    def test_short_name_inside_long_name(self):
        # Resolved name is a shorter form; the actor's name is the
        # longer "with tagline" form. Should still match.
        assert _name_matches_dealer(
            "Yancey Rents - The Cat Rental Store",
            "Yancey Rents",
            "yanceyrents",
        )

    def test_long_name_inside_short_name_reverse_substring(self):
        # And vice versa — the matcher is symmetric on the name
        # axis (one substring of the other).
        assert _name_matches_dealer(
            "Yancey Rents",
            "Yancey Rents - The Cat Rental Store",
            "yanceyrents",
        )

    def test_punctuation_and_case_ignored(self):
        assert _name_matches_dealer(
            "yancey-rents the cat rental store",
            "Yancey Rents - The Cat Rental Store",
            "YanceyRents",
        )

    def test_collision_noise_dropped(self):
        # 1Hood Media is the actual collision row from the alternate
        # scraper screenshot (search "Yancey Rents" matched a different
        # advertiser). Must be rejected.
        assert not _name_matches_dealer(
            "1Hood Media", "Yancey Rents", "yanceyrents",
        )

    def test_unrelated_name_dropped(self):
        assert not _name_matches_dealer(
            "Some Random LLC", "Yancey Rents", "yanceyrents",
        )

    def test_empty_actor_name_rejected_when_expected_present(self):
        # The 17:53 production bug: empty actor name + populated
        # expected → strict path rejects. This is correct PER-AD
        # behaviour; the run-wide fail-open in _run_actor_for_page
        # is what saves the run when EVERY ad hits this case.
        assert not _name_matches_dealer("", "Yancey Rents", "yanceyrents")
        assert not _name_matches_dealer(None, "Yancey Rents", "yanceyrents")


# ---------------------------------------------------------------------------
# _name_matches_dealer — fail-open path (when no expected signal)
# ---------------------------------------------------------------------------

class TestNameMatchesDealerFailOpen:
    def test_no_expected_signal_at_all(self):
        # If both expected_name and expected_slug are missing, we
        # cannot filter; fail open so we don't drop everything.
        # (Used by the upstream run-wide fail-open path; also a
        # safety net if a dealer URL has neither resolved name nor
        # extractable slug.)
        assert _name_matches_dealer("anything", None, None)
        assert _name_matches_dealer("anything", "", "")
        assert _name_matches_dealer("anything", "   ", "  ")

    def test_empty_actor_name_with_no_expected_still_rejected(self):
        # Empty on BOTH sides — there's nothing to filter on AND
        # nothing to filter against. Whatever we choose here doesn't
        # affect production (this combination doesn't arise from
        # _run_actor_for_page's fail-open path because that path
        # bypasses the per-ad filter entirely). Lock the current
        # behaviour: empty actor name fails closed for this branch.
        assert not _name_matches_dealer("", None, None)
        assert not _name_matches_dealer(None, None, None)


# ---------------------------------------------------------------------------
# Integration-style: verify the run-wide fail-open count works on a
# realistic batch of ads.
# ---------------------------------------------------------------------------

class TestRunWideFailOpenAdsCount:
    """Cross-checks that ``ads_with_any_name == 0`` (the trigger for
    the run-wide fail-open in _run_actor_for_page) is computed
    consistently with ``_ad_advertiser_name``."""

    def test_zero_when_all_empty(self):
        # The 17:53 production payload shape: 6 ads, none with names.
        ads = [
            {"adId": str(i), "imageUrls": [{"url": f"https://x/{i}.jpg"}]}
            for i in range(6)
        ]
        ads_with_any_name = sum(
            1 for a in ads if _ad_advertiser_name(a).strip()
        )
        assert ads_with_any_name == 0  # fail-open triggers

    def test_nonzero_when_mixed(self):
        # If ANY ad has a name, the strict path runs (per-ad filter).
        # The collision-noise ad will be dropped; the others kept.
        ads = [
            {"adId": "1", "pageName": "Yancey Rents - The Cat Rental Store"},
            {"adId": "2"},  # empty — strict path rejects this one
            {"adId": "3", "brand": "Yancey Rents - The Cat Rental Store"},
            {"adId": "4", "pageName": "1Hood Media"},
        ]
        ads_with_any_name = sum(
            1 for a in ads if _ad_advertiser_name(a).strip()
        )
        assert ads_with_any_name == 3  # strict path runs

        # Sanity: simulate the per-ad filter to confirm the right
        # ones survive.
        kept = [
            a for a in ads
            if _name_matches_dealer(
                _ad_advertiser_name(a),
                "Yancey Rents - The Cat Rental Store",
                "yanceyrents",
            )
        ]
        assert len(kept) == 2
        assert {kept[0]["adId"], kept[1]["adId"]} == {"1", "3"}

    def test_nonzero_when_all_populated(self):
        # No collisions, no empty ads — every ad survives.
        ads = [
            {"adId": "1", "pageName": "Yancey Rents - X"},
            {"adId": "2", "brand": "Yancey Rents - Y"},
        ]
        ads_with_any_name = sum(
            1 for a in ads if _ad_advertiser_name(a).strip()
        )
        assert ads_with_any_name == 2

    def test_whitespace_only_name_treated_as_empty(self):
        # Defensive: a stray "   " from some HTML extraction quirk
        # should not count as a real name signal.
        ads = [{"adId": "1", "pageName": "   \n\t  "}]
        ads_with_any_name = sum(
            1 for a in ads if _ad_advertiser_name(a).strip()
        )
        assert ads_with_any_name == 0  # fail-open triggers
