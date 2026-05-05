"""Phase 6.5.8 — RSS-hardening helpers in extraction_service.

Covers the JPEG/PNG branching, the page-height clip threshold, the
screenshot-concurrency semaphore, the upload helper's content-type
plumbing, and the Chromium launch-flags diet so future edits don't
silently regress any of them.

The OOM these tests guard against was:
  4 dealer pipelines × full-page PNG screenshot of a 30000-px AEM page
  + concurrent Supabase Storage upload buffers + CLIP model RSS
  = worker process gets killed by the platform.

Each test below pins one half of the fix so the contract that prevents
the recurrence is enforced by the suite, not by code review.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _take_evidence_screenshot
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_page():
    """Minimal Page stand-in with the methods the helper actually calls."""
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=2000)  # short page by default
    page.screenshot = AsyncMock(return_value=b"jpeg-bytes")
    page.viewport_size = {"width": 1920, "height": 1080}
    return page


@pytest.mark.asyncio
async def test_take_evidence_screenshot_uses_jpeg_by_default(fake_page):
    """Default config: JPEG with explicit quality, full_page=True for short pages."""
    from app.services import extraction_service as ext

    image_bytes, meta = await ext._take_evidence_screenshot(fake_page)

    fake_page.screenshot.assert_awaited_once()
    kwargs = fake_page.screenshot.await_args.kwargs
    assert kwargs["type"] == "jpeg"
    assert kwargs["full_page"] is True
    assert "quality" in kwargs and 1 <= kwargs["quality"] <= 95
    assert "clip" not in kwargs
    assert image_bytes == b"jpeg-bytes"
    assert meta["format"] == "jpeg"
    assert meta["clipped"] is False
    assert meta["bytes"] == len(b"jpeg-bytes")


@pytest.mark.asyncio
async def test_take_evidence_screenshot_clips_tall_pages(fake_page):
    """Pages taller than the cap get clipped from the top down with a flag."""
    from app.services import extraction_service as ext

    fake_page.evaluate = AsyncMock(return_value=30000)  # AEM-style mega-page

    with patch.object(ext.settings, "max_screenshot_height", 12000):
        _, meta = await ext._take_evidence_screenshot(fake_page)

    kwargs = fake_page.screenshot.await_args.kwargs
    assert "clip" in kwargs
    assert kwargs["clip"]["height"] == 12000
    assert kwargs["clip"]["x"] == 0
    assert kwargs["clip"]["y"] == 0
    assert "full_page" not in kwargs  # mutually exclusive with clip
    assert meta["clipped"] is True
    assert meta["captured_height_px"] == 12000
    assert meta["page_height_px"] == 30000


@pytest.mark.asyncio
async def test_take_evidence_screenshot_honours_png_format(fake_page):
    """Operators can flip back to PNG if they ever need lossless evidence."""
    from app.services import extraction_service as ext

    with patch.object(ext.settings, "evidence_screenshot_format", "png"):
        await ext._take_evidence_screenshot(fake_page)

    kwargs = fake_page.screenshot.await_args.kwargs
    assert kwargs["type"] == "png"
    # PNG screenshots must NOT pass `quality` — Playwright rejects it.
    assert "quality" not in kwargs


@pytest.mark.asyncio
async def test_take_evidence_screenshot_falls_back_when_height_probe_fails(fake_page):
    """If `document.body.scrollHeight` blows up, we still take the screenshot."""
    from app.services import extraction_service as ext

    fake_page.evaluate = AsyncMock(side_effect=RuntimeError("eval failed"))

    image_bytes, meta = await ext._take_evidence_screenshot(fake_page)

    assert image_bytes == b"jpeg-bytes"
    assert meta["page_height_px"] == 0
    # height=0 is below the cap, so we go full_page (the safe default)
    assert fake_page.screenshot.await_args.kwargs.get("full_page") is True


# ---------------------------------------------------------------------------
# Format / content-type / extension plumbing
# ---------------------------------------------------------------------------


def test_evidence_screenshot_extension_jpeg_uses_jpg():
    """JPEG format → '.jpg' extension on the storage path."""
    from app.services import extraction_service as ext

    with patch.object(ext.settings, "evidence_screenshot_format", "jpeg"):
        assert ext._evidence_screenshot_extension() == "jpg"


def test_evidence_screenshot_content_type_jpeg():
    from app.services import extraction_service as ext

    with patch.object(ext.settings, "evidence_screenshot_format", "jpeg"):
        assert ext._evidence_screenshot_content_type() == "image/jpeg"


def test_evidence_screenshot_extension_png():
    from app.services import extraction_service as ext

    with patch.object(ext.settings, "evidence_screenshot_format", "png"):
        assert ext._evidence_screenshot_extension() == "png"
        assert ext._evidence_screenshot_content_type() == "image/png"


# ---------------------------------------------------------------------------
# _upload_screenshot — content-type tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_screenshot_uses_jpeg_content_type_by_default():
    """The Supabase upload's content-type must match the configured format."""
    from app.services import extraction_service as ext
    from uuid import uuid4

    captured: dict = {}

    def fake_upload(path, body, options):
        captured["path"] = path
        captured["options"] = options
        return MagicMock()

    fake_storage = MagicMock()
    fake_storage.upload = fake_upload
    fake_storage.get_public_url = MagicMock(return_value="https://cdn/example.jpg")

    fake_supabase = MagicMock()
    fake_supabase.storage.from_ = MagicMock(return_value=fake_storage)

    with patch.object(ext, "supabase", fake_supabase), \
         patch.object(ext.settings, "evidence_screenshot_format", "jpeg"):
        url = await ext._upload_screenshot(b"x" * 1024, uuid4(), "https://example.com")

    assert url == "https://cdn/example.jpg"
    assert captured["options"]["content-type"] == "image/jpeg"
    assert captured["path"].endswith(".jpg")


@pytest.mark.asyncio
async def test_upload_screenshot_explicit_overrides_win():
    """Callers can pin a specific format regardless of settings."""
    from app.services import extraction_service as ext
    from uuid import uuid4

    captured: dict = {}

    def fake_upload(path, body, options):
        captured["path"] = path
        captured["options"] = options
        return MagicMock()

    fake_storage = MagicMock()
    fake_storage.upload = fake_upload
    fake_storage.get_public_url = MagicMock(return_value="https://cdn/example.png")

    fake_supabase = MagicMock()
    fake_supabase.storage.from_ = MagicMock(return_value=fake_storage)

    with patch.object(ext, "supabase", fake_supabase):
        await ext._upload_screenshot(
            b"x" * 1024, uuid4(), "https://example.com",
            content_type="image/png", extension="png",
        )

    assert captured["options"]["content-type"] == "image/png"
    assert captured["path"].endswith(".png")


# ---------------------------------------------------------------------------
# Screenshot-concurrency semaphore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_screenshot_semaphore_caps_concurrent_screenshots():
    """The global semaphore must cap how many screenshots are in-flight at once."""
    from app.services import extraction_service as ext

    # Reset the cached semaphore so this test sees a fresh one.
    ext._screenshot_semaphore = None

    active = 0
    peak = 0
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def hold_one():
        nonlocal active, peak
        async with ext._get_screenshot_semaphore():
            active += 1
            peak = max(peak, active)
            started.set()
            await proceed.wait()
            active -= 1

    with patch.object(ext.settings, "max_concurrent_screenshots", 2):
        ext._screenshot_semaphore = None  # force re-init at the new cap
        tasks = [asyncio.create_task(hold_one()) for _ in range(5)]
        # wait for the first 2 to start
        await started.wait()
        await asyncio.sleep(0.05)
        # at this point at most `cap=2` should be inside the semaphore
        assert peak <= 2
        proceed.set()
        await asyncio.gather(*tasks)

    # Reset for downstream tests
    ext._screenshot_semaphore = None


# ---------------------------------------------------------------------------
# RSS observability
# ---------------------------------------------------------------------------


def test_rss_mb_returns_positive_float():
    from app.services import extraction_service as ext

    rss = ext._rss_mb()
    assert isinstance(rss, float)
    assert rss > 0  # any running Python process has nonzero RSS


def test_log_rss_never_raises(monkeypatch):
    """Observability must be safe — a broken `resource` call must not break a scan."""
    from app.services import extraction_service as ext

    monkeypatch.setattr(ext.resource, "getrusage", MagicMock(side_effect=RuntimeError("boom")))
    # If this raised, prod scans would break. The helper swallows.
    ext._log_rss("test")


# ---------------------------------------------------------------------------
# Chromium launch-flags diet
# ---------------------------------------------------------------------------


def _read_launch_args() -> list[str]:
    """Pull the literal `args=` list from `_get_browser` so we can assert
    on the flags without launching a real browser. Uses inspect.getsource
    + a tiny string scan, which is plenty for the assertions we want."""
    import inspect
    from app.services import extraction_service as ext

    source = inspect.getsource(ext._get_browser)
    # Grab everything between `args=[` and the matching `]`. The function
    # body is short and the list is the only one inside it, so this is
    # safe for our purpose without dragging in a Python parser.
    start = source.index("args=[")
    end = source.index("]", start)
    flag_block = source[start:end]
    return [
        line.strip().strip(",").strip('"')
        for line in flag_block.splitlines()
        if line.strip().startswith('"--')
    ]


def test_chromium_launch_args_include_rss_diet():
    """Every flag we added is load-bearing — losing one regresses RSS."""
    args = _read_launch_args()
    rss_flags = {
        "--js-flags=--max-old-space-size=512",
        "--disable-background-networking",
        "--disable-extensions",
        "--disable-sync",
        "--no-default-browser-check",
        "--no-first-run",
        "--mute-audio",
    }
    missing = rss_flags - set(args)
    assert not missing, f"RSS-diet flags missing from launch args: {missing}"


def test_chromium_launch_args_keep_existing_stealth_flags():
    """The RSS diet must NOT have removed the WAF-bypass stealth flag."""
    args = _read_launch_args()
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--no-sandbox" in args
    assert "--disable-dev-shm-usage" in args
