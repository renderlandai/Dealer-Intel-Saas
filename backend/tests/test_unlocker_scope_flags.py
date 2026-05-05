"""Phase 6.5.9 — Bright Data scope-tightening flag tests.

Covers the two flags that take BD back to "fallback only" outside the
rendering ladder:

* ``unlocker_asset_fetch_enabled`` — when False (the new default),
  ``ai_service.download_image`` MUST NOT route through the unlocker
  even on hosts that have been BD-unlocked this worker.
* ``unlocker_discovery_enabled`` — when False, page-discovery's
  homepage-link crawl MUST NOT call the unlocker, regardless of how
  few links the direct crawl returned.

Each test pins one half of the contract so a future regression
(e.g. someone removes the gate, or flips the default back to True
without thinking) fails immediately at the suite level.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# ai_service.download_image — asset-fetch routing
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clear_image_cache():
    """download_image memoises results; clear between tests so the
    routing assertions actually re-execute the host-needs-unlocker
    branch."""
    from app.services import ai_service
    ai_service._image_cache.clear()
    yield
    ai_service._image_cache.clear()


def _png_bytes() -> bytes:
    """Smallest possible valid PNG so `_is_valid_image` accepts it."""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_download_image_skips_unlocker_when_asset_fetch_disabled():
    """Default state (flag=False): even an unlocked host bypasses BD entirely.

    We mock the bottom-of-function ``httpx.AsyncClient`` so the test
    doesn't actually hit the network, then assert that BD's
    ``download_via_unlocker`` was never even reached.
    """
    from app.services import ai_service, unlocker_service

    unlocker_service.mark_host_unlocked("dealer.example.com")
    assert unlocker_service.host_needs_unlocker("https://dealer.example.com/img.png")

    bd_mock = AsyncMock(return_value=_png_bytes())
    direct_probe_mock = AsyncMock(return_value=_png_bytes())

    # Build a fake AsyncClient that returns valid PNG bytes for the
    # final fall-through fetch — its presence tells us the code took
    # the direct-only path instead of the BD branch.
    fake_response = MagicMock()
    fake_response.content = _png_bytes()
    fake_response.headers = {"content-type": "image/png"}
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=fake_response)

    with patch.object(ai_service.settings, "unlocker_asset_fetch_enabled", False), \
         patch.object(ai_service, "_try_direct_image_fetch", direct_probe_mock), \
         patch.object(ai_service, "_is_valid_image", return_value=True), \
         patch.object(unlocker_service, "download_via_unlocker", bd_mock), \
         patch.object(ai_service.httpx, "AsyncClient", return_value=fake_client):
        result = _run(ai_service.download_image("https://dealer.example.com/img.png"))

    assert result == _png_bytes()
    # Both BD entry points must have been bypassed entirely. The
    # direct-probe is part of the BD branch (the "try direct first
    # before paying BD" optimization) so it should NOT fire when the
    # whole BD branch is gated off.
    bd_mock.assert_not_awaited()
    direct_probe_mock.assert_not_awaited()


def test_download_image_uses_unlocker_when_asset_fetch_enabled(monkeypatch):
    """Opt-in: flag=True restores the pre-6.5.9 BD-with-direct-probe path."""
    from app.services import ai_service, unlocker_service

    unlocker_service.mark_host_unlocked("dealer-bd.example.com")
    bd_bytes = b"BD-edge-rendition" + _png_bytes()

    async def _fail_direct(url, *, timeout=4.0):
        return None  # force fall-through to BD

    bd_mock = AsyncMock(return_value=bd_bytes)

    # Bypass the magic-bytes validator so the BD payload above is accepted.
    with patch.object(ai_service.settings, "unlocker_asset_fetch_enabled", True), \
         patch.object(ai_service, "_try_direct_image_fetch", _fail_direct), \
         patch.object(ai_service, "_is_valid_image", return_value=True), \
         patch.object(unlocker_service, "download_via_unlocker", bd_mock):
        result = _run(ai_service.download_image("https://dealer-bd.example.com/img.png"))

    assert result == bd_bytes
    bd_mock.assert_awaited_once()


def test_download_image_unmarked_host_is_unaffected_by_asset_flag():
    """Hosts that were never BD-unlocked must use the direct path
    regardless of the asset-fetch flag value."""
    from app.services import ai_service, unlocker_service

    # Sanity: this host is NOT in the unlocked set.
    assert not unlocker_service.host_needs_unlocker("https://fresh.example.com/x.png")

    bd_mock = AsyncMock(return_value=_png_bytes())

    fake_response = MagicMock()
    fake_response.content = _png_bytes()
    fake_response.headers = {"content-type": "image/png"}
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.get = AsyncMock(return_value=fake_response)

    # Even with the flag flipped ON, an unmarked host must skip BD —
    # the gate is `flag AND host_needs_unlocker`, both halves required.
    with patch.object(ai_service.settings, "unlocker_asset_fetch_enabled", True), \
         patch.object(ai_service, "_is_valid_image", return_value=True), \
         patch.object(unlocker_service, "download_via_unlocker", bd_mock), \
         patch.object(ai_service.httpx, "AsyncClient", return_value=fake_client):
        _run(ai_service.download_image("https://fresh.example.com/x.png"))

    bd_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# page_discovery — discovery routing
# ---------------------------------------------------------------------------


def test_page_discovery_skips_unlocker_when_discovery_disabled():
    """Default state (flag=False): even when the direct crawl returns
    only the base URL, no BD discovery call is made."""
    from app.services import page_discovery

    crawl_via_unlocker = AsyncMock(return_value=["https://dealer.example.com/promo"])

    async def _empty_direct_crawl(*_args, **_kwargs):
        return []

    async def _empty_sitemap(*_args, **_kwargs):
        return []

    async def _empty_probe(*_args, **_kwargs):
        return []

    fake_settings = MagicMock()
    fake_settings.unlocker_discovery_enabled = False

    with patch.object(page_discovery, "_crawl_homepage_links_via_unlocker", crawl_via_unlocker), \
         patch.object(page_discovery, "_crawl_homepage_links", _empty_direct_crawl), \
         patch.object(page_discovery, "_fetch_sitemap_urls", _empty_sitemap), \
         patch.object(page_discovery, "_probe_common_paths", _empty_probe), \
         patch("app.config.get_settings", return_value=fake_settings):
        result = _run(page_discovery.discover_pages("https://dealer.example.com/"))

    crawl_via_unlocker.assert_not_called()
    assert any("dealer.example.com" in u for u in result)


def test_page_discovery_uses_unlocker_when_discovery_enabled():
    """Opt-in: flag=True restores the pre-6.5.9 'BD homepage crawl'
    fallback when the direct crawl returns nothing useful."""
    from app.services import page_discovery

    crawl_via_unlocker = AsyncMock(return_value=[
        "https://dealer-bd.example.com/promo",
        "https://dealer-bd.example.com/specials",
    ])

    async def _empty_direct_crawl(*_args, **_kwargs):
        return []

    async def _empty_sitemap(*_args, **_kwargs):
        return []

    async def _empty_probe(*_args, **_kwargs):
        return []

    fake_settings = MagicMock()
    fake_settings.unlocker_discovery_enabled = True

    with patch.object(page_discovery, "_crawl_homepage_links_via_unlocker", crawl_via_unlocker), \
         patch.object(page_discovery, "_crawl_homepage_links", _empty_direct_crawl), \
         patch.object(page_discovery, "_fetch_sitemap_urls", _empty_sitemap), \
         patch.object(page_discovery, "_probe_common_paths", _empty_probe), \
         patch("app.config.get_settings", return_value=fake_settings):
        result = _run(page_discovery.discover_pages("https://dealer-bd.example.com/"))

    crawl_via_unlocker.assert_called_once()
    assert any("/promo" in u for u in result)


# ---------------------------------------------------------------------------
# Default values — these are the load-bearing defaults of 6.5.9
# ---------------------------------------------------------------------------


def test_unlocker_asset_fetch_default_is_off():
    """The whole point of 6.5.9. If this flips back to True by accident,
    every BD-unlocked host's asset bytes start coming from BD's edge
    again and match scores quietly regress."""
    from app.config import Settings
    s = Settings(
        supabase_url="https://x.test",
        supabase_anon_key="k",
        supabase_service_role_key="k",
        anthropic_api_key="k",
    )
    assert s.unlocker_asset_fetch_enabled is False


def test_unlocker_discovery_default_is_off():
    """Same contract for the discovery path."""
    from app.config import Settings
    s = Settings(
        supabase_url="https://x.test",
        supabase_anon_key="k",
        supabase_service_role_key="k",
        anthropic_api_key="k",
    )
    assert s.unlocker_discovery_enabled is False


def test_unlocker_fallback_default_stays_on():
    """The master rendering-ladder switch must remain ON — 6.5.9 is
    about scoping BD's reach OUTSIDE the ladder, not killing the ladder
    rung itself. Genuinely WAF-blocked hosts must still get BD evidence
    via the rendering ladder."""
    from app.config import Settings
    s = Settings(
        supabase_url="https://x.test",
        supabase_anon_key="k",
        supabase_service_role_key="k",
        anthropic_api_key="k",
    )
    assert s.unlocker_fallback_enabled is True
