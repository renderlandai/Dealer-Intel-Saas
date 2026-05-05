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


# ---------------------------------------------------------------------------
# Phase 6.5.3 — URL safety / normalization before posting to Bright Data
# ---------------------------------------------------------------------------

class TestNormalizeTargetUrl:
    """``_normalize_target_url`` is the gate between us and Bright Data.

    It exists because production scans on 2026-04-30 burned ~17 BD
    requests per scan on URLs like ``…/{{path}}.html`` (unrendered AEM
    Mustache templates leaked into discovery), and were also at risk of
    burning more on Spanish-language dealer URLs whose UTF-8 paths
    weren't percent-encoded. Both shapes return HTTP 400 with no useful
    body, so we reject them locally rather than pay BD to tell us so."""

    def test_template_placeholder_rejected(self):
        from app.services.unlocker_service import _normalize_target_url
        for bad in (
            "https://rent.cat.com/dealer/en_US/{{path}}.html",
            "https://x.com/${url}",
            "https://x.com/<%= path %>",
            "https://x.com/[% var %]",
        ):
            safe, err = _normalize_target_url(bad)
            assert safe is None, f"expected reject for {bad!r}"
            assert err == "brightdata_url_template_placeholder"

    def test_empty_or_too_long_rejected(self):
        from app.services.unlocker_service import _normalize_target_url
        assert _normalize_target_url("") == (None, "brightdata_url_empty")
        long_url = "https://x.com/" + ("a" * 3000)
        safe, err = _normalize_target_url(long_url)
        assert safe is None
        assert err == "brightdata_url_too_long"

    def test_unparseable_rejected(self):
        from app.services.unlocker_service import _normalize_target_url
        # No scheme.
        assert _normalize_target_url("rent.cat.com/home.html")[0] is None
        # No host.
        assert _normalize_target_url("https:///home.html")[0] is None

    def test_passes_through_already_clean_url_unchanged(self):
        """A URL that has no spaces, no non-ASCII, and no template
        markers must come back identical (modulo dropped fragment)."""
        from app.services.unlocker_service import _normalize_target_url
        clean = "https://rent.cat.com/wheeler/en_US/home.html"
        safe, err = _normalize_target_url(clean)
        assert err is None
        assert safe == clean

    def test_drops_fragment(self):
        """Fragments are client-only and never sent in the HTTP request,
        so it's safer to strip them than rely on Bright Data's
        canonicalization."""
        from app.services.unlocker_service import _normalize_target_url
        safe, err = _normalize_target_url("https://x.com/page#section")
        assert err is None
        assert safe == "https://x.com/page"

    def test_encodes_inline_spaces_in_path(self):
        from app.services.unlocker_service import _normalize_target_url
        safe, err = _normalize_target_url("https://x.com/promo page/spring deals")
        assert err is None
        assert " " not in safe
        assert "%20" in safe

    def test_encodes_non_ascii_path_chars(self):
        """Real example: Spanish-language dealer URL with an accented
        character in the path. UTF-8 percent-encoded bytes are what
        Bright Data expects."""
        from app.services.unlocker_service import _normalize_target_url
        safe, err = _normalize_target_url("https://rent.cat.com/finning-chile/promoción.html")
        assert err is None
        assert "ó" not in safe
        # 'ó' UTF-8: 0xC3 0xB3 → "%C3%B3"
        assert "%C3%B3" in safe

    def test_does_not_double_encode_already_encoded(self):
        """If the input already has ``%20`` we MUST keep it as ``%20``,
        not turn it into ``%2520`` (which would Bright Data canon to a
        different URL than the dealer page actually uses)."""
        from app.services.unlocker_service import _normalize_target_url
        safe, err = _normalize_target_url("https://x.com/promo%20page")
        assert err is None
        assert safe == "https://x.com/promo%20page"

    def test_preserves_query_string(self):
        from app.services.unlocker_service import _normalize_target_url
        safe, err = _normalize_target_url("https://x.com/path?a=1&b=2&c=hello+world")
        assert err is None
        # Query characters that are already URL-safe must survive untouched.
        assert "a=1" in safe and "b=2" in safe


class TestPostUnlockerSkipsBadUrls:
    """``_post_unlocker`` must NOT make an HTTP call when the URL is
    structurally bad — that's the whole point of the local gate."""

    def test_template_placeholder_short_circuits_before_http(self):
        from app.services import unlocker_service

        # If httpx.AsyncClient is constructed at all, that's a fail. We
        # patch it to raise so any leak through the gate explodes loudly.
        class _Boom:
            def __init__(self, *a, **kw):
                raise AssertionError("HTTP client must not be constructed for bad URL")

        with patch.object(unlocker_service.httpx, "AsyncClient", _Boom), \
             patch.object(unlocker_service, "_api_token", return_value="tok"), \
             patch.object(unlocker_service, "_zone_name", return_value="zone"):
            body, status, err = _run(unlocker_service._post_unlocker(
                "https://rent.cat.com/dealer/en_US/{{path}}.html",
            ))

        assert body is None
        assert status is None
        assert err == "brightdata_url_template_placeholder"

    def test_clean_url_is_passed_through_to_payload(self):
        """End-to-end: a normal URL reaches BD with the path encoded but
        otherwise unchanged. Updated post-Phase-6.5.5 to use the
        streaming HTTP path (``client.stream(...)``) that the response
        size cap enforces."""
        from app.services import unlocker_service

        captured = {}
        client = _StreamingFakeClient(
            status_code=200,
            chunks=[b"x" * 200],
            captured=captured,
        )

        with patch.object(unlocker_service.httpx, "AsyncClient", lambda *a, **kw: client), \
             patch.object(unlocker_service, "_api_token", return_value="tok"), \
             patch.object(unlocker_service, "_zone_name", return_value="zone"):
            body, status, err = _run(unlocker_service._post_unlocker(
                "https://x.com/promo page",
            ))

        assert err is None
        assert status == 200
        assert captured["payload"]["url"] == "https://x.com/promo%20page"
        assert captured["method"] == "POST"


# ---------------------------------------------------------------------------
# Phase 6.5.5 — Response-size cap on `_post_unlocker`
# ---------------------------------------------------------------------------
#
# A pathological or malicious upstream host could return an unbounded
# body to Bright Data, which would forward every byte to us — burning
# BD bandwidth, blowing the worker's RAM, and stretching the scan
# timeout into oblivion. The cap aborts both pre-flight (Content-Length
# header) and mid-flight (chunk accumulation) so we cap actual bytes
# read, not just nominal allocation.

class _StreamingResponse:
    """Minimal stand-in for httpx.Response in a streaming context.

    Supports the four attributes/methods ``_post_unlocker`` actually
    touches: ``status_code``, ``headers`` (case-insensitive get),
    ``aiter_bytes()`` async iterator, and ``aclose()``.
    """
    def __init__(self, status_code: int, chunks, headers=None):
        self.status_code = status_code
        self._chunks = list(chunks)
        self.headers = httpx_like_headers(headers or {})

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def aclose(self):
        return None


class _StreamCtx:
    def __init__(self, response: "_StreamingResponse"):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *a):
        return False


class _StreamingFakeClient:
    """An httpx.AsyncClient look-alike that records the streamed POST."""
    def __init__(self, status_code: int, chunks, captured: dict, headers=None):
        self._status = status_code
        self._chunks = chunks
        self._captured = captured
        self._headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, *, json=None, headers=None):
        # httpx's AsyncClient.stream is sync-returning the ctx manager,
        # not async — match that contract so ``async with client.stream(...)``
        # works.
        self._captured["method"] = method
        self._captured["url"] = url
        self._captured["payload"] = json
        self._captured["headers"] = headers
        return _StreamCtx(_StreamingResponse(self._status, self._chunks, self._headers))


class httpx_like_headers(dict):
    """Tiny shim over a dict that returns case-insensitive get like
    httpx.Headers does for the one header we read (``content-length``)."""
    def get(self, name, default=None):
        target = name.lower()
        for k, v in self.items():
            if k.lower() == target:
                return v
        return default


class TestPostUnlockerResponseSizeCap:
    """Belt-and-suspenders cap: BD will faithfully forward whatever the
    upstream host returns, including a malicious or misconfigured body
    of arbitrary size. We refuse to buffer past the cap (HTML default
    8 MB, image override 25 MB)."""

    def test_content_length_header_over_cap_short_circuits(self):
        """Cheap pre-flight: when the upstream advertises a too-large
        body via Content-Length, we don't drain a single chunk."""
        from app.services import unlocker_service

        captured = {}
        # Body chunks below the cap, but Content-Length lies and says
        # the body is huge. We must trust the header and bail.
        client = _StreamingFakeClient(
            status_code=200,
            chunks=[b"x" * 100],
            captured=captured,
            headers={"content-length": str(unlocker_service._MAX_UNLOCKER_HTML_BYTES + 1)},
        )

        with patch.object(unlocker_service.httpx, "AsyncClient", lambda *a, **kw: client), \
             patch.object(unlocker_service, "_api_token", return_value="tok"), \
             patch.object(unlocker_service, "_zone_name", return_value="zone"):
            body, status, err = _run(unlocker_service._post_unlocker(
                "https://x.com/page",
            ))

        assert body is None
        assert status == 200
        assert err == "brightdata_response_too_large"

    def test_streamed_overflow_is_aborted_mid_flight(self):
        """When Content-Length isn't present (or lies low), streaming
        accumulation must catch the overflow and abort."""
        from app.services import unlocker_service

        captured = {}
        # Each chunk is 1 MB; with a 3 MB cap, the 4th chunk triggers
        # the overflow.
        chunks = [b"x" * (1024 * 1024)] * 4
        client = _StreamingFakeClient(
            status_code=200,
            chunks=chunks,
            captured=captured,
        )

        with patch.object(unlocker_service.httpx, "AsyncClient", lambda *a, **kw: client), \
             patch.object(unlocker_service, "_api_token", return_value="tok"), \
             patch.object(unlocker_service, "_zone_name", return_value="zone"):
            body, status, err = _run(unlocker_service._post_unlocker(
                "https://x.com/page",
                max_body_bytes=3 * 1024 * 1024,
            ))

        assert body is None
        assert status == 200
        assert err == "brightdata_response_too_large"

    def test_body_within_cap_is_returned_intact(self):
        """A body well under the cap must round-trip with no truncation."""
        from app.services import unlocker_service

        captured = {}
        chunks = [b"hello", b" ", b"world", b"!" * 200]
        client = _StreamingFakeClient(
            status_code=200,
            chunks=chunks,
            captured=captured,
        )

        with patch.object(unlocker_service.httpx, "AsyncClient", lambda *a, **kw: client), \
             patch.object(unlocker_service, "_api_token", return_value="tok"), \
             patch.object(unlocker_service, "_zone_name", return_value="zone"):
            body, status, err = _run(unlocker_service._post_unlocker(
                "https://x.com/page",
            ))

        assert err is None
        assert status == 200
        assert body == b"".join(chunks)

    def test_image_path_uses_larger_cap(self):
        """``download_via_unlocker`` overrides the HTML cap with the
        image cap so a 10 MB hero PNG (which is over the HTML cap but
        under the image cap) still comes through."""
        from app.services import unlocker_service

        unlocker_service._mark_available()
        captured = {}
        # 10 MB: would overflow the 8 MB HTML cap, but should pass the
        # 25 MB image cap that download_via_unlocker passes through.
        chunks = [b"x" * (1024 * 1024)] * 10
        client = _StreamingFakeClient(
            status_code=200,
            chunks=chunks,
            captured=captured,
        )

        with patch.object(unlocker_service.httpx, "AsyncClient", lambda *a, **kw: client), \
             patch.object(unlocker_service, "_api_token", return_value="tok"), \
             patch.object(unlocker_service, "_zone_name", return_value="zone"), \
             patch.object(unlocker_service, "is_available", return_value=True):
            result = _run(unlocker_service.download_via_unlocker(
                "https://rent.cat.com/dam/banner.png",
            ))

        assert result is not None
        assert len(result) == 10 * 1024 * 1024
