"""Phase 6.5.2 — page discovery unit tests.

Covers the post-incident fix from 2026-04-30:

* WAF-protected hosts (Akamai/Cloudflare/Imperva) — direct httpx
  probes silently 0-result so discovery used to return only the base
  URL. The runner then processed exactly 1 page regardless of the
  per-site budget. The fix routes those hosts through Bright Data Web
  Unlocker for homepage link extraction. These tests assert the
  routing decision is taken from ``host_policy_service.get_strategy``
  and that the unlocker fallback also kicks in when direct discovery
  produced only the base URL.
* The fallback is monetary (~$0.0015 per affected dealer per scan), so
  we also assert it is NOT triggered for hosts on a non-WAF strategy
  whose direct discovery worked.

No real httpx or Bright Data calls — every test stubs the relevant
collaborator.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple
from unittest.mock import AsyncMock, patch

import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Strategy-driven routing of discovery
# ---------------------------------------------------------------------------

class TestDiscoverPagesStrategyRouting:
    """``discover_pages`` should consult ``host_policy_service`` and skip
    direct probes on WAF-grade strategies."""

    def test_unlocker_only_strategy_skips_direct_probes(self):
        """A host on ``unlocker_only`` should never call _probe_common_paths
        / _fetch_sitemap_urls / _crawl_homepage_links — those are
        guaranteed-zero on the same WAF that earned the strategy."""
        from app.services import page_discovery

        async def _empty_probe(_url):
            raise AssertionError("direct probe must NOT run for unlocker_only host")

        async def _empty_sitemap(_url):
            raise AssertionError("direct sitemap fetch must NOT run for unlocker_only host")

        async def _empty_homepage_crawl(_url, _domain):
            raise AssertionError("direct homepage crawl must NOT run for unlocker_only host")

        async def _fake_unlocker_crawl(_url, _domain):
            return [
                "https://rent.cat.com/wheeler/specials",
                "https://rent.cat.com/wheeler/inventory",
                "https://rent.cat.com/wheeler/financing",
            ]

        with patch.object(page_discovery, "_probe_common_paths", side_effect=_empty_probe), \
             patch.object(page_discovery, "_fetch_sitemap_urls", side_effect=_empty_sitemap), \
             patch.object(page_discovery, "_crawl_homepage_links", side_effect=_empty_homepage_crawl), \
             patch.object(page_discovery, "_crawl_homepage_links_via_unlocker", side_effect=_fake_unlocker_crawl), \
             patch("app.services.host_policy_service.get_strategy", return_value="unlocker_only"):

            urls = _run(page_discovery.discover_pages(
                "https://rent.cat.com/wheeler/en_US/home.html",
                max_pages=15,
            ))

        # Base URL + 3 unlocker-discovered pages.
        assert len(urls) == 4
        assert "https://rent.cat.com/wheeler/specials" in urls

    def test_playwright_then_unlocker_strategy_also_skips_direct(self):
        from app.services import page_discovery

        called = {"direct": 0, "unlocker": 0}

        async def _direct(_url):
            called["direct"] += 1
            return []

        async def _unlocker(_url, _domain):
            called["unlocker"] += 1
            return ["https://x.com/a", "https://x.com/b"]

        with patch.object(page_discovery, "_probe_common_paths", side_effect=_direct), \
             patch.object(page_discovery, "_fetch_sitemap_urls", side_effect=_direct), \
             patch.object(page_discovery, "_crawl_homepage_links", side_effect=lambda u, d: _direct(u)), \
             patch.object(page_discovery, "_crawl_homepage_links_via_unlocker", side_effect=_unlocker), \
             patch("app.services.host_policy_service.get_strategy", return_value="playwright_then_unlocker"):

            urls = _run(page_discovery.discover_pages(
                "https://x.com/", max_pages=15,
            ))

        assert called["direct"] == 0, "direct probes must NOT run on WAF-grade strategy"
        assert called["unlocker"] == 1
        assert len(urls) >= 1

    def test_playwright_desktop_strategy_uses_direct_only(self):
        """Healthy hosts (default strategy) MUST NOT pay the $0.0015 BD
        cost on every scan — direct discovery is free."""
        from app.services import page_discovery

        called = {"unlocker": 0}

        async def _direct_probe(_url):
            return ["https://healthy.com/specials"]

        async def _direct_sitemap(_url):
            return ["https://healthy.com/dealspage"]

        async def _direct_homepage(_url, _domain):
            return ["https://healthy.com/inventory"]

        async def _unlocker(_url, _domain):
            called["unlocker"] += 1
            return []

        with patch.object(page_discovery, "_probe_common_paths", side_effect=_direct_probe), \
             patch.object(page_discovery, "_fetch_sitemap_urls", side_effect=_direct_sitemap), \
             patch.object(page_discovery, "_crawl_homepage_links", side_effect=_direct_homepage), \
             patch.object(page_discovery, "_crawl_homepage_links_via_unlocker", side_effect=_unlocker), \
             patch("app.services.host_policy_service.get_strategy", return_value="playwright_desktop"):

            urls = _run(page_discovery.discover_pages(
                "https://healthy.com/", max_pages=15,
            ))

        assert called["unlocker"] == 0, \
            "unlocker fallback must NOT trigger when direct discovery succeeded"
        assert len(urls) >= 2  # base + at least one direct-discovered URL


# ---------------------------------------------------------------------------
# Fallback when direct returned only the base URL
# ---------------------------------------------------------------------------

class TestUnlockerFallbackOnEmptyDirect:
    """Even on a default-strategy host, if direct discovery silently
    produced 0 results we should fall back to the unlocker — that's the
    exact symptom rent.cat.com showed before its policy row existed."""

    def test_fallback_triggers_when_direct_returns_only_base(self):
        from app.services import page_discovery

        called = {"unlocker": 0}

        async def _empty(*_args, **_kwargs):
            return []

        async def _empty_homepage(_url, _domain):
            return []

        async def _unlocker(_url, _domain):
            called["unlocker"] += 1
            return [
                "https://newhost.com/specials",
                "https://newhost.com/inventory",
            ]

        with patch.object(page_discovery, "_probe_common_paths", side_effect=_empty), \
             patch.object(page_discovery, "_fetch_sitemap_urls", side_effect=_empty), \
             patch.object(page_discovery, "_crawl_homepage_links", side_effect=_empty_homepage), \
             patch.object(page_discovery, "_crawl_homepage_links_via_unlocker", side_effect=_unlocker), \
             patch("app.services.host_policy_service.get_strategy", return_value="playwright_desktop"):

            urls = _run(page_discovery.discover_pages(
                "https://newhost.com/", max_pages=15,
            ))

        assert called["unlocker"] == 1, \
            "unlocker fallback must run when direct discovery only returned the base URL"
        # Base + 2 unlocker pages
        assert len(urls) == 3

    def test_promo_links_from_unlocker_are_promoted_first(self):
        """Same ordering rules as the direct path: promo-keyword URLs
        get filled into the result list before non-promo URLs."""
        from app.services import page_discovery

        async def _empty(*_args, **_kwargs):
            return []

        async def _empty_homepage(_url, _domain):
            return []

        async def _unlocker(_url, _domain):
            # Mix of promo and non-promo URLs in arbitrary order — the
            # filler logic should hoist /specials and /deals first.
            return [
                "https://x.com/about",
                "https://x.com/specials/loaders",
                "https://x.com/contact",
                "https://x.com/deals/spring",
                "https://x.com/team",
            ]

        with patch.object(page_discovery, "_probe_common_paths", side_effect=_empty), \
             patch.object(page_discovery, "_fetch_sitemap_urls", side_effect=_empty), \
             patch.object(page_discovery, "_crawl_homepage_links", side_effect=_empty_homepage), \
             patch.object(page_discovery, "_crawl_homepage_links_via_unlocker", side_effect=_unlocker), \
             patch("app.services.host_policy_service.get_strategy", return_value="unlocker_only"):

            urls = _run(page_discovery.discover_pages(
                "https://x.com/", max_pages=4,
            ))

        # Base URL is always slot 0; the next two slots must be the
        # promo URLs, not /about or /contact. _normalize_url keeps a
        # trailing slash for the bare-host form.
        assert urls[0] == "https://x.com/"
        promo_set = {"https://x.com/specials/loaders", "https://x.com/deals/spring"}
        assert set(urls[1:3]) == promo_set


# ---------------------------------------------------------------------------
# _crawl_homepage_links_via_unlocker behavior
# ---------------------------------------------------------------------------

class TestUnlockerHomepageCrawl:
    def test_filters_to_same_domain_and_scannable(self):
        from app.services import page_discovery, unlocker_service

        # Mixed links: same-domain pages, off-domain ad, an asset, a tel:
        html = """
          <a href="/specials">Specials</a>
          <a href="https://x.com/inventory">Inventory</a>
          <a href="https://other.com/leaving-domain">Other</a>
          <a href="/banner.png">img link</a>
          <a href="tel:+15551234">call</a>
          <a href="javascript:void(0)">js</a>
          <a href="#top">top</a>
        """

        async def _fake_post_text(url):
            return html, 200, None

        with patch.object(
            unlocker_service, "_post_unlocker_text", side_effect=_fake_post_text,
        ), patch.object(unlocker_service, "is_available", return_value=True):
            urls = _run(page_discovery._crawl_homepage_links_via_unlocker(
                "https://x.com/home", "x.com",
            ))

        # Only same-domain scannable pages survive.
        assert "https://x.com/specials" in urls
        assert "https://x.com/inventory" in urls
        assert all("other.com" not in u for u in urls)
        assert all(not u.endswith(".png") for u in urls)

    def test_unlocker_unavailable_returns_empty(self):
        from app.services import page_discovery, unlocker_service

        with patch.object(unlocker_service, "is_available", return_value=False):
            urls = _run(page_discovery._crawl_homepage_links_via_unlocker(
                "https://x.com/", "x.com",
            ))

        assert urls == []

    def test_unlocker_failure_returns_empty(self):
        from app.services import page_discovery, unlocker_service

        async def _fail(_url):
            return None, 503, "brightdata_http_503"

        with patch.object(
            unlocker_service, "_post_unlocker_text", side_effect=_fail,
        ), patch.object(unlocker_service, "is_available", return_value=True):
            urls = _run(page_discovery._crawl_homepage_links_via_unlocker(
                "https://x.com/", "x.com",
            ))

        assert urls == []

    def test_successful_unlock_marks_host_for_asset_routing(self):
        """Side effect: a successful unlock during discovery should
        also flag the host so subsequent image downloads route via BD,
        without waiting for the per-page extraction phase to do its
        own first unlock."""
        from app.services import page_discovery, unlocker_service

        unlocker_service._unlocked_hosts.clear()

        async def _ok(_url):
            return '<a href="/specials">Specials</a>', 200, None

        with patch.object(
            unlocker_service, "_post_unlocker_text", side_effect=_ok,
        ), patch.object(unlocker_service, "is_available", return_value=True):
            _run(page_discovery._crawl_homepage_links_via_unlocker(
                "https://rent.cat.com/wheeler/home", "rent.cat.com",
            ))

        assert unlocker_service.host_needs_unlocker("rent.cat.com") is True


# ---------------------------------------------------------------------------
# Phase 6.5.3 — template-placeholder href filter
# ---------------------------------------------------------------------------

class TestHrefIsSafe:
    """``_href_is_safe`` is the gate that drops unrendered template
    placeholders before they become bogus URLs in the discovery list.
    The 2026-04-30 production scan recorded HTTP 400 from Bright Data
    on 17 dealer URLs, every one of which was a literal
    ``…/{{path}}.html`` href the AEM page failed to substitute."""

    def test_rejects_mustache_placeholders(self):
        from app.services.page_discovery import _href_is_safe
        assert _href_is_safe("/{{path}}.html") is False
        assert _href_is_safe("{{url}}") is False
        assert _href_is_safe("/page/{{slug}}/sub") is False

    def test_rejects_es6_template_literals(self):
        from app.services.page_discovery import _href_is_safe
        assert _href_is_safe("/promo/${name}") is False

    def test_rejects_asp_jsp_scriptlets(self):
        from app.services.page_discovery import _href_is_safe
        assert _href_is_safe("/<%= var %>") is False
        assert _href_is_safe("/[% page %]/foo") is False

    def test_rejects_inline_whitespace(self):
        from app.services.page_discovery import _href_is_safe
        assert _href_is_safe("/promo page.html") is False
        assert _href_is_safe("/promo\tpage.html") is False
        assert _href_is_safe("/promo\npage.html") is False

    def test_rejects_control_characters(self):
        from app.services.page_discovery import _href_is_safe
        assert _href_is_safe("/promo\x00page.html") is False
        assert _href_is_safe("/promo\x07page.html") is False

    def test_rejects_overlong_urls(self):
        from app.services.page_discovery import _href_is_safe
        # 2049 chars = beyond the limit. AEM has been known to leak
        # entire JSON blobs into href on broken templates.
        assert _href_is_safe("/" + ("a" * 2049)) is False

    def test_accepts_normal_urls(self):
        from app.services.page_discovery import _href_is_safe
        assert _href_is_safe("/specials") is True
        assert _href_is_safe("/promo-2026") is True
        assert _href_is_safe("https://x.com/inventory?type=loader") is True
        assert _href_is_safe("/products/aerial-equipment/boom-lifts") is True


class TestUnlockerCrawlerDropsTemplateHrefs:
    """Integration: the unlocker discovery path must drop template-leak
    hrefs BEFORE they reach the unlocker request in run_ladder.

    This is the exact bug shape from the 2026-04-30 production scan."""

    def test_template_hrefs_filtered_from_results(self):
        from app.services import page_discovery, unlocker_service

        # Real-world AEM-style HTML with both a clean link and the
        # leaked Mustache placeholder side-by-side.
        html = """
          <a href="/altorfer-rents/en_US/promotions.html">Promotions</a>
          <a href="/altorfer-rents/en_US/{{path}}.html">Broken template</a>
          <a href="/altorfer-rents/en_US/about.html">About</a>
          <a href="https://rent.cat.com/altorfer-rents/en_US/${section}/index">Broken template 2</a>
        """

        async def _ok(_url):
            return html, 200, None

        with patch.object(
            unlocker_service, "_post_unlocker_text", side_effect=_ok,
        ), patch.object(unlocker_service, "is_available", return_value=True):
            urls = _run(page_discovery._crawl_homepage_links_via_unlocker(
                "https://rent.cat.com/altorfer-rents/en_US/home.html",
                "rent.cat.com",
            ))

        joined = " ".join(urls)
        assert "promotions" in joined
        assert "about" in joined
        assert "{{" not in joined
        assert "${" not in joined
        assert "%7B%7B" not in joined  # no encoded leak either
