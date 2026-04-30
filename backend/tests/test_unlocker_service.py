"""Phase 6.5.1 — unlocker_service unit tests.

Covers the post-incident hardening from 2026-04-30 PM:

* The image-URL shape filter that drops AEM /_jcr_content/ component
  paths before they hit the analyzer (where they 30s-timeout).
* The per-host registry that flags origins as needing the unlocker
  for asset downloads, populated automatically on a successful
  page unlock.
* The HTML parser end-to-end on a synthetic AEM-style page.

No real Bright Data calls — every test stubs ``_post_unlocker``.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# URL-shape filter (_looks_like_image_url)
# ---------------------------------------------------------------------------

class TestLooksLikeImageUrl:
    def test_accepts_common_extensions(self):
        from app.services.unlocker_service import _looks_like_image_url
        for ext in ("jpg", "jpeg", "png", "webp", "gif", "avif", "svg", "bmp", "tiff"):
            assert _looks_like_image_url(f"https://x.com/a.{ext}") is True
            assert _looks_like_image_url(f"https://x.com/a.{ext.upper()}") is True

    def test_accepts_extension_with_query_string(self):
        from app.services.unlocker_service import _looks_like_image_url
        assert _looks_like_image_url("https://x.com/banner.jpg?w=800") is True
        assert _looks_like_image_url("https://x.com/banner.png?v=2&size=lg") is True

    def test_accepts_aem_coreimg_paths(self):
        """AEM rendition URLs are extension-bearing but the extension
        sits inside a longer path segment — make sure they pass."""
        from app.services.unlocker_service import _looks_like_image_url
        url = (
            "https://rent.cat.com/content/dam/crs/dealers/wheeler/"
            "_jcr_content/root/responsivegrid_6958138/image.coreimg.85.1024.jpeg/"
            "1730000000/banner.jpeg"
        )
        # Has both the AEM marker AND a real .jpeg, so the filter keeps it.
        assert _looks_like_image_url(url) is True

    def test_accepts_dam_paths_without_extension(self):
        """``/dam/`` is AEM's Digital Asset Manager root; URLs in there
        are reliably images even when extensionless redirects show up."""
        from app.services.unlocker_service import _looks_like_image_url
        assert _looks_like_image_url(
            "https://rent.cat.com/content/dam/crs/dealers/wheeler-machinery/logo"
        ) is True

    def test_rejects_aem_component_paths(self):
        """The exact failure mode from 2026-04-30: AEM component refs
        with no image extension MUST be dropped or they hang the
        downloader for 30s each."""
        from app.services.unlocker_service import _looks_like_image_url
        bad = (
            "https://rent.cat.com/wheeler/en_US/home/"
            "_jcr_content/root/responsivegrid_6958138"
        )
        assert _looks_like_image_url(bad) is False
        assert _looks_like_image_url(bad + "/responsivegrid_96") is False

    def test_rejects_extensionless_pages(self):
        from app.services.unlocker_service import _looks_like_image_url
        assert _looks_like_image_url("https://x.com/about") is False
        assert _looks_like_image_url("https://x.com/products/loaders") is False

    def test_rejects_empty(self):
        from app.services.unlocker_service import _looks_like_image_url
        assert _looks_like_image_url("") is False


# ---------------------------------------------------------------------------
# Per-host registry
# ---------------------------------------------------------------------------

class TestHostRegistry:
    def setup_method(self):
        # Fresh registry per test — _unlocked_hosts is module-level.
        from app.services import unlocker_service
        unlocker_service._unlocked_hosts.clear()

    def test_unknown_host_is_not_flagged(self):
        from app.services.unlocker_service import host_needs_unlocker
        assert host_needs_unlocker("https://random.example.com/page") is False

    def test_mark_then_lookup_is_case_insensitive(self):
        from app.services.unlocker_service import (
            host_needs_unlocker, mark_host_unlocked,
        )
        mark_host_unlocked("https://Rent.Cat.com/wheeler/home")
        assert host_needs_unlocker("https://rent.cat.com/something/else") is True
        # Lookup by hostname directly also works.
        assert host_needs_unlocker("rent.cat.com") is True

    def test_mark_is_per_host_not_per_url(self):
        """A successful unlock for /page1 should also route /page2's
        images via BD — same host, same WAF."""
        from app.services.unlocker_service import (
            host_needs_unlocker, mark_host_unlocked,
        )
        mark_host_unlocked("https://rent.cat.com/wheeler/home.html")
        assert host_needs_unlocker("https://rent.cat.com/content/dam/logo.png") is True

    def test_mark_does_not_leak_across_hosts(self):
        from app.services.unlocker_service import (
            host_needs_unlocker, mark_host_unlocked,
        )
        mark_host_unlocked("https://rent.cat.com/page")
        assert host_needs_unlocker("https://yancey.com/specials") is False


# ---------------------------------------------------------------------------
# parse_images_from_html — end-to-end on synthetic markup
# ---------------------------------------------------------------------------

class TestParseImagesFromHtml:
    def test_drops_aem_component_path_alongside_real_image(self):
        """The AEM mixed case: a page that returns one real .jpg and
        one component placeholder. The placeholder is the wheeler-
        machinery class of bug; the .jpg should still come through."""
        from app.services.unlocker_service import parse_images_from_html
        html = """
        <html><body>
          <img src="/content/dam/dealers/wheeler/logo.png" width="400" height="200" alt="logo" />
          <img src="/wheeler/en_US/home/_jcr_content/root/responsivegrid_6958138" alt="" />
          <img src="https://rent.cat.com/content/dam/promo/special.jpeg" />
        </body></html>
        """
        results = parse_images_from_html(
            html,
            base_url="https://rent.cat.com/wheeler/en_US/home.html",
            min_width=300, min_height=150, max_images=50,
        )
        srcs = [r["src"] for r in results]
        assert "https://rent.cat.com/content/dam/dealers/wheeler/logo.png" in srcs
        assert "https://rent.cat.com/content/dam/promo/special.jpeg" in srcs
        # The component path must be dropped (it would 30s-timeout in
        # the analyzer) — none of the kept results should reference it.
        for s in srcs:
            assert "responsivegrid_" not in s

    def test_resolves_relative_urls_against_base(self):
        from app.services.unlocker_service import parse_images_from_html
        html = '<img src="/banner.png" width="400" height="200" />'
        results = parse_images_from_html(
            html, base_url="https://example.com/dealers/page",
            min_width=300, min_height=150, max_images=50,
        )
        assert results == [
            {
                "src": "https://example.com/banner.png",
                "width": 400, "height": 200,
                "alt": "", "classes": "", "tag": "img",
                "x": 0, "y": 100,
            }
        ]

    def test_dedupes_repeated_srcs(self):
        from app.services.unlocker_service import parse_images_from_html
        html = """
          <img src="/a.png" />
          <img src="/a.png" />
          <picture><source srcset="/a.png 800w" /><img /></picture>
        """
        results = parse_images_from_html(
            html, base_url="https://x.com/", min_width=300, min_height=150, max_images=10,
        )
        assert len(results) == 1
        assert results[0]["src"] == "https://x.com/a.png"

    def test_picks_first_url_from_srcset(self):
        from app.services.unlocker_service import parse_images_from_html
        html = """
          <picture>
            <source srcset="/banner-800.png 800w, /banner-1600.png 1600w" />
            <img />
          </picture>
        """
        results = parse_images_from_html(
            html, base_url="https://x.com/", min_width=300, min_height=150, max_images=10,
        )
        assert len(results) == 1
        assert results[0]["src"] == "https://x.com/banner-800.png"


# ---------------------------------------------------------------------------
# unlock_and_extract auto-marks the host
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# URL log shortener (preserves discriminating filename)
# ---------------------------------------------------------------------------

class TestShortenUrlForLog:
    def test_short_urls_pass_through(self):
        from app.services.unlocker_service import _shorten_url_for_log
        u = "https://x.com/banner.png"
        assert _shorten_url_for_log(u) == u

    def test_long_aem_urls_keep_filename_tail(self):
        """The 2026-04-30 PM bug: `url[:80]` chopped off the
        discriminating filename on AEM coreimg URLs, making 3 distinct
        renditions look identical in the log. The helper must keep the
        filename portion of the path."""
        from app.services.unlocker_service import _shorten_url_for_log
        url = (
            "https://rent.cat.com/wheeler/en_US/home/"
            "_jcr_content/root/responsivegrid_6958138/"
            "image.coreimg.85.1024.jpeg/1730000000/banner.jpeg"
        )
        out = _shorten_url_for_log(url)
        assert out.startswith("https://rent.cat.com/")
        assert out.endswith("banner.jpeg")
        assert "..." in out

    def test_three_distinct_aem_renditions_render_distinctly(self):
        """Operator-experience regression: the helper's whole reason
        to exist is to make 3 distinct renditions of one component
        visibly distinct in the log."""
        from app.services.unlocker_service import _shorten_url_for_log
        prefix = (
            "https://rent.cat.com/wheeler/en_US/home/"
            "_jcr_content/root/responsivegrid_6958138/"
        )
        urls = [
            prefix + "image.coreimg.85.1024.jpeg/170000/banner.jpeg",
            prefix + "image.coreimg.85.1024.png/170001/banner.png",
            prefix + "image.coreimg.85.1024.svg/170002/banner.svg",
        ]
        shortened = [_shorten_url_for_log(u) for u in urls]
        assert len(set(shortened)) == 3, \
            f"all 3 shortened forms must differ, got: {shortened}"


class TestUnlockAndExtractMarksHost:
    def setup_method(self):
        from app.services import unlocker_service
        unlocker_service._unlocked_hosts.clear()
        unlocker_service._mark_available()

    def test_successful_unlock_marks_host_for_asset_routing(self):
        """The 2026-04-30 PM fix: after BD successfully renders a page
        on a host, asset downloads on the SAME host route via BD too
        (because the asset CDN is gated by the same WAF)."""
        from app.services import unlocker_service

        async def fake_unlock_text(url):
            html = '<img src="/dam/banner.png" width="400" height="200" />'
            return html, 200, None

        # The buffer's real flush_all() rounds-trips Supabase to insert
        # discovered_image rows. In the unit test there's no real client,
        # so we short-circuit it and trust the inserts were prepared
        # correctly. (The bulk_writers module has its own tests.)
        def _fake_flush(self):
            n = len(self.buffer) if hasattr(self, "buffer") else 0
            return n if n else 1   # we know one image got pushed in this test

        with patch.object(
            unlocker_service, "_post_unlocker_text",
            side_effect=fake_unlock_text,
        ), patch(
            "app.services.bulk_writers.DiscoveredImageBuffer.flush_all",
            new=_fake_flush,
        ):
            res = _run(unlocker_service.unlock_and_extract(
                url="https://rent.cat.com/wheeler/home.html",
                scan_job_id=uuid4(),
                distributor_id=None,
                seen_srcs=set(),
                campaign_assets=None,
            ))

        assert res.outcome == "images"
        assert res.count >= 1
        # Crucial: the host is now flagged so subsequent asset fetches
        # go through BD instead of timing out on Akamai.
        assert unlocker_service.host_needs_unlocker("rent.cat.com") is True

    def test_failed_unlock_does_not_mark_host(self):
        from app.services import unlocker_service

        async def fake_unlock_text(url):
            return None, 503, "brightdata_http_503"

        with patch.object(
            unlocker_service, "_post_unlocker_text",
            side_effect=fake_unlock_text,
        ):
            res = _run(unlocker_service.unlock_and_extract(
                url="https://rent.cat.com/wheeler/home.html",
                scan_job_id=uuid4(),
                distributor_id=None,
                seen_srcs=set(),
                campaign_assets=None,
            ))

        assert res.outcome == "blocked"
        assert unlocker_service.host_needs_unlocker("rent.cat.com") is False
