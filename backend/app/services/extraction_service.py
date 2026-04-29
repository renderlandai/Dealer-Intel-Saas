"""
Playwright-based image extraction service for dealer website and ad page scanning.

Instead of taking a single full-page screenshot and asking Claude to find assets
within it, this service loads pages in a real browser and extracts individual
<img> elements. Each extracted image URL is then compared as a regular image,
where perceptual hashing and visual comparison work at full accuracy.

A full-page screenshot is still captured as audit evidence but is NOT used
for AI matching unless extraction fails (tiling fallback).

Channels supported:
- Dealer websites: standard image extraction
- Google Ads Transparency: ad-card image extraction
- Facebook / Meta Ad Library: ad creative extraction with fallback
"""
import hashlib
import io
import logging
import time
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from urllib.parse import quote, urlparse

from PIL import Image

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

from ..config import get_settings
from ..database import supabase
from ..services import ai_service
from ..services.bulk_writers import (
    DiscoveredImageBuffer,
    _safe_insert_discovered_image,
)

log = logging.getLogger("dealer_intel.extraction")

settings = get_settings()


# ---------------------------------------------------------------------------
# Extraction outcomes (Task A: truthful counters)
# ---------------------------------------------------------------------------
#
# Every page-extraction attempt resolves to exactly one of these. The runner
# uses the outcome — not just the image count — to decide what to count as a
# real "page scanned" vs. a blocked / failed page that should be surfaced in
# the report. Adding a screenshot-fallback row no longer silently inflates
# the "pages scanned" metric.
OUTCOME_IMAGES = "images"          # got >=1 real <img>
OUTCOME_EMPTY = "empty"            # page loaded fine but had no extractable images
OUTCOME_BLOCKED = "blocked"        # WAF / anti-bot / 4xx / ERR_ABORTED
OUTCOME_TIMEOUT = "timeout"        # navigation never completed within playwright_timeout
OUTCOME_CRASHED = "crashed"        # playwright/browser exception we didn't classify


@dataclass
class ExtractionResult:
    """Structured outcome of a single page-extraction attempt.

    Fields:
      count:        number of new images inserted into ``discovered_images``
      evidence_url: URL of the full-page screenshot uploaded to storage
                    (None when even the screenshot failed)
      outcome:      one of OUTCOME_* above; the runner uses this to bin the
                    page into "scanned with images / empty page / blocked /
                    timeout / crashed"
      block_reason: short human-readable reason when outcome=BLOCKED
                    (e.g. "ERR_ABORTED", "HTTP 403", "challenge_page")
      http_status:  response status from the initial navigation, if known
    """
    count: int = 0
    evidence_url: Optional[str] = None
    outcome: str = OUTCOME_EMPTY
    block_reason: Optional[str] = None
    http_status: Optional[int] = None


# Shared browser instance to avoid repeated cold starts
_browser: Optional[Browser] = None
_pw_instance = None
_browser_lock = asyncio.Lock()
_browser_created_at: float = 0.0
# Recycle browser every 60 min. The previous 10-min cap was a defensive
# choice from the single-Chromium / single-process era — it forced a
# multi-second relaunch in the middle of nearly every long scan and risked
# tearing down an in-flight page. With per-dealer concurrency in the
# website runner and a separate worker process owning the browser, an hour
# is comfortable: contexts are short-lived and the leak surface is small.
_BROWSER_MAX_AGE_SECONDS = 3600


async def _get_browser() -> Browser:
    """Return a shared headless Chromium instance, launching if needed."""
    global _browser, _pw_instance, _browser_created_at
    async with _browser_lock:
        stale = (time.monotonic() - _browser_created_at) > _BROWSER_MAX_AGE_SECONDS
        if _browser is None or not _browser.is_connected() or stale:
            if _browser is not None:
                try:
                    await _browser.close()
                except Exception:
                    pass
            if _pw_instance is not None:
                try:
                    await _pw_instance.stop()
                except Exception:
                    pass
            _pw_instance = await async_playwright().start()
            _browser = await _pw_instance.chromium.launch(
                headless=True,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    # Stealth: hide the "I'm an automation" flag that many
                    # WAFs (Akamai/Cloudflare/Imperva, including the one
                    # protecting rent.cat.com) check in the very first
                    # navigator probe.
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            _browser_created_at = time.monotonic()
            log.info("Launched fresh Playwright browser")
    return _browser


# Lightweight stealth init script — applied to every new context. This is
# *not* full evasion, but it bypasses the cheapest WAF fingerprints
# (navigator.webdriver === true, empty navigator.plugins, languages mismatch)
# without pulling in playwright-stealth as a dependency.
_STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map(() => ({name: 'Chrome PDF Plugin'}))
});
window.chrome = window.chrome || {runtime: {}};
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : originalQuery(parameters)
    );
}
"""


async def _new_page(browser: Browser, mobile: bool = False) -> Page:
    """Create a page with desktop or mobile viewport and matching user-agent."""
    if mobile:
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.4 Mobile/15E148 Safari/604.1"
            ),
            is_mobile=True,
            has_touch=True,
            device_scale_factor=3,
            locale="en-US",
            timezone_id="America/New_York",
        )
    else:
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
    try:
        await context.add_init_script(_STEALTH_INIT_JS)
    except Exception:
        # Stealth is best-effort — a Playwright/Chromium version mismatch
        # shouldn't block extraction.
        pass
    page = await context.new_page()
    return page


async def _scroll_to_bottom(page: Page, max_scrolls: int = 20) -> None:
    """Scroll the page to trigger lazy-loaded images."""
    previous_height = 0
    for _ in range(max_scrolls):
        current_height = await page.evaluate("document.body.scrollHeight")
        if current_height == previous_height:
            break
        previous_height = current_height
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(settings.playwright_scroll_delay)
    # Return to top so the evidence screenshot starts from the top
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.3)


async def _dismiss_overlays(page: Page) -> None:
    """Best-effort click away cookie banners and chat widgets."""
    dismiss_selectors = [
        "button[id*='accept']", "button[id*='cookie']",
        "button[class*='accept']", "button[class*='cookie']",
        "button[class*='consent']", "button[aria-label*='close']",
        "[class*='cookie'] button", "[id*='cookie'] button",
        "[class*='banner'] button[class*='close']",
    ]
    for sel in dismiss_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                await btn.click(timeout=1000)
                await asyncio.sleep(0.3)
                break
        except Exception:
            continue


async def _advance_carousels(
    page: Page,
    max_clicks: int = 5,
    extract_per_step: bool = True,
) -> List[Dict[str, Any]]:
    """Click carousel/slider 'next' buttons to reveal hidden slides.

    Many dealer sites use carousels for promotional banners.  The creative
    might only be visible after clicking forward.  We extract images after
    each click so that every slide's content is captured, not just the
    final state.

    Returns a list of image dicts collected across all carousel steps
    (deduplicated by src).
    """
    next_selectors = [
        "button[class*='next']", "button[class*='slick-next']",
        "button[aria-label*='next' i]", "button[aria-label*='Next' i]",
        "[class*='carousel'] [class*='next']",
        "[class*='slider'] [class*='next']",
        "[class*='swiper-button-next']",
        ".owl-next", ".carousel-control-next",
        "button[data-slide='next']",
        "[class*='arrow-right']", "[class*='arrow_right']",
    ]
    collected: List[Dict[str, Any]] = []
    seen_srcs: set = set()

    for sel in next_selectors:
        try:
            btn = page.locator(sel).first
            if not await btn.is_visible(timeout=500):
                continue
            for _ in range(max_clicks):
                await btn.click(timeout=1000)
                await asyncio.sleep(0.6)
                if extract_per_step:
                    step_images = await _extract_images_from_page(page)
                    for img in step_images:
                        if img["src"] not in seen_srcs:
                            seen_srcs.add(img["src"])
                            collected.append(img)
            break
        except Exception:
            continue

    return collected


async def _upload_screenshot(
    image_bytes: bytes,
    scan_job_id: UUID,
    source_url: str,
    bucket: str = "scan-screenshots",
) -> Optional[str]:
    """Upload screenshot bytes to Supabase storage. Returns the public URL."""
    try:
        url_hash = hashlib.md5(source_url.encode()).hexdigest()[:12]
        timestamp = int(time.time() * 1000)
        path = f"screenshots/{scan_job_id}/{url_hash}-{timestamp}.png"

        supabase.storage.from_(bucket).upload(
            path, image_bytes, {"content-type": "image/png"}
        )
        public_url = supabase.storage.from_(bucket).get_public_url(path)
        log.info("Evidence screenshot saved: %s", public_url[:80])
        return public_url
    except Exception as e:
        log.error("Evidence screenshot upload failed: %s", e)
        return None


async def _capture_evidence_screenshot(
    page: Page,
    scan_job_id: UUID,
    source_url: str,
    bucket: str = "scan-screenshots",
) -> Optional[str]:
    """Take a full-page screenshot and upload to Supabase for audit evidence."""
    try:
        image_bytes = await page.screenshot(full_page=True, type="png")
        return await _upload_screenshot(image_bytes, scan_job_id, source_url, bucket)
    except Exception as e:
        log.error("Evidence screenshot failed: %s", e)
        return None


async def _screenshotone_fallback(url: str, scan_job_id: UUID) -> Optional[str]:
    """Capture a blocked page via ScreenshotOne's hosted renderer.

    Used when both Playwright viewports came back BLOCKED — ScreenshotOne
    runs from rotating residential-style IPs that are typically not on
    Cat/Akamai's headless-Chromium denylist. Returns the storage URL of
    the uploaded PNG, or None on any failure.
    """
    if not getattr(settings, "screenshotone_access_key", ""):
        return None
    # Late import to avoid a circular dependency between services.
    from . import screenshot_service
    return await screenshot_service.capture_and_upload(url, scan_job_id)


async def _extract_images_from_page(page: Page) -> List[Dict[str, Any]]:
    """
    Extract all meaningful images from the current page.

    Returns a list of dicts with image metadata. Filters out tiny images
    (icons, tracking pixels) and deduplicates by src URL.
    """
    min_w = settings.min_extracted_image_width
    min_h = settings.min_extracted_image_height
    max_imgs = settings.max_images_per_page

    images = await page.evaluate(f"""() => {{
        const seen = new Set();
        const results = [];

        // 1) <img> elements
        for (const img of document.querySelectorAll('img')) {{
            const src = img.currentSrc || img.src;
            if (!src || src.startsWith('data:image/svg') || seen.has(src)) continue;
            const w = img.naturalWidth || img.width;
            const h = img.naturalHeight || img.height;
            if (w < {min_w} || h < {min_h}) continue;
            seen.add(src);
            const rect = img.getBoundingClientRect();
            results.push({{
                src: src,
                width: w,
                height: h,
                alt: img.alt || '',
                classes: img.className || '',
                tag: 'img',
                x: Math.round(rect.x),
                y: Math.round(rect.y + window.scrollY),
            }});
            if (results.length >= {max_imgs}) return results;
        }}

        // 2) <picture> / <source> elements (responsive images)
        for (const pic of document.querySelectorAll('picture')) {{
            const sources = pic.querySelectorAll('source');
            for (const s of sources) {{
                const srcset = s.srcset || '';
                const firstUrl = srcset.split(',')[0]?.trim().split(/\\s+/)[0];
                if (!firstUrl || seen.has(firstUrl)) continue;
                const img = pic.querySelector('img');
                const w = img ? (img.naturalWidth || img.width) : 0;
                const h = img ? (img.naturalHeight || img.height) : 0;
                if (w < {min_w} || h < {min_h}) continue;
                seen.add(firstUrl);
                const rect = pic.getBoundingClientRect();
                results.push({{
                    src: firstUrl,
                    width: w,
                    height: h,
                    alt: img ? (img.alt || '') : '',
                    classes: pic.className || '',
                    tag: 'picture-source',
                    x: Math.round(rect.x),
                    y: Math.round(rect.y + window.scrollY),
                }});
                if (results.length >= {max_imgs}) return results;
                break;
            }}
        }}

        // 3) CSS background-image on common ad/promo containers
        const bgSelectors = [
            '[class*="hero"]', '[class*="banner"]', '[class*="promo"]',
            '[class*="ad-"]', '[class*="ad_"]', '[class*="campaign"]',
            '[class*="slide"]', '[class*="carousel"]',
            '[class*="special"]', '[class*="deal"]', '[class*="offer"]',
            '[class*="feature"]', '[class*="incentive"]', '[class*="rebate"]',
            '[class*="savings"]', '[class*="coupon"]',
            '[role="banner"]', 'header', '.jumbotron',
            'section[id*="special"]', 'section[id*="promo"]',
            'section[id*="deal"]', 'section[id*="offer"]',
            'div[id*="special"]', 'div[id*="promo"]',
            'div[id*="deal"]', 'div[id*="offer"]',
        ];
        for (const sel of bgSelectors) {{
            for (const el of document.querySelectorAll(sel)) {{
                const bg = getComputedStyle(el).backgroundImage;
                if (!bg || bg === 'none') continue;
                const match = bg.match(/url\\(["']?(https?:\\/\\/[^"')]+)["']?\\)/);
                if (!match) continue;
                const src = match[1];
                if (seen.has(src)) continue;
                seen.add(src);
                const rect = el.getBoundingClientRect();
                const w = rect.width;
                const h = rect.height;
                if (w < {min_w} || h < {min_h}) continue;
                results.push({{
                    src: src,
                    width: Math.round(w),
                    height: Math.round(h),
                    alt: '',
                    classes: el.className || '',
                    tag: 'bg-image',
                    x: Math.round(rect.x),
                    y: Math.round(rect.y + window.scrollY),
                }});
                if (results.length >= {max_imgs}) return results;
            }}
        }}

        return results;
    }}""")

    return images


async def _localize_and_crop_assets(
    screenshot_bytes: bytes,
    scan_job_id: UUID,
    campaign_assets: List[Dict[str, Any]],
    bucket: str = "scan-screenshots",
) -> List[Dict[str, Any]]:
    """
    Use OpenCV template matching + feature matching to locate campaign
    creatives within a full-page screenshot, then crop and upload each
    one as an isolated discovered image.

    This is pixel-precise and doesn't depend on HTML structure or AI
    bounding-box guesswork.
    """
    from . import cv_matching

    if not campaign_assets:
        log.debug("No campaign assets provided — skipping")
        return []

    full_img = Image.open(io.BytesIO(screenshot_bytes))
    if full_img.mode != "RGB":
        full_img = full_img.convert("RGB")
    page_w, page_h = full_img.size

    cropped: List[Dict[str, Any]] = []

    for asset in campaign_assets:
        asset_url = asset.get("file_url", "")
        asset_name = asset.get("name", "unnamed")
        if not asset_url:
            continue

        try:
            asset_bytes = await ai_service.download_image(asset_url)
        except Exception as e:
            log.error("Failed to download asset '%s': %s", asset_name, e)
            continue

        log.debug("Searching for '%s' on page (%dx%d)", asset_name, page_w, page_h)
        matches = cv_matching.find_asset_on_page(screenshot_bytes, asset_bytes)

        if not matches:
            log.info("'%s' not found on page", asset_name)
            continue

        for match in matches:
            x = max(0, match["x"])
            y = max(0, match["y"])
            w = match["width"]
            h = match["height"]
            if w < 50 or h < 30:
                continue

            right = min(x + w, page_w)
            bottom = min(y + h, page_h)

            crop = full_img.crop((x, y, right, bottom))
            buf = io.BytesIO()
            crop.save(buf, format="PNG", optimize=True)
            crop_bytes = buf.getvalue()

            if len(crop_bytes) < 2000:
                continue

            url_hash = hashlib.md5(f"crop-{x}-{y}-{w}-{h}".encode()).hexdigest()[:12]
            ts = int(time.time() * 1000)
            path = f"crops/{scan_job_id}/{url_hash}-{ts}.png"

            try:
                supabase.storage.from_(bucket).upload(path, crop_bytes, {"content-type": "image/png"})
                public_url = supabase.storage.from_(bucket).get_public_url(path)
            except Exception as e:
                log.error("Upload failed for crop at (%d,%d): %s", x, y, e)
                continue

            cropped.append({
                "src": public_url,
                "width": right - x,
                "height": bottom - y,
                "alt": "",
                "classes": f"cv-crop:{asset_name}",
                "tag": "cv-localized-crop",
                "x": x,
                "y": y,
            })
            log.debug(
                "Cropped '%s' at (%d,%d) %dx%d conf=%.3f method=%s",
                asset_name, x, y, right - x, bottom - y,
                match["confidence"], match["method"],
            )

    log.info("Created %d cropped creative(s)", len(cropped))
    return cropped


async def localize_screenshot_capture(
    evidence_url: str,
    scan_job_id: UUID,
    page_url: str,
    distributor_id: Optional[UUID],
    campaign_assets: Optional[List[Dict[str, Any]]],
) -> int:
    """Run CV localization on a captured full-page screenshot and insert
    each cropped creative as its own ``discovered_images`` row.

    Used when a page was captured via the ScreenshotOne fallback (Playwright
    couldn't reach it). The matcher is then comparing real banner-sized
    crops against the campaign assets instead of comparing a 1920x3000
    full-page screenshot against a 320x50 banner — which previously
    produced "STRONG MATCH (modified)" verdicts on hosts like
    ``rent.cat.com`` because the page literally contained the campaign
    artwork at hero size. See log.md 2026-04-29 for the diagnostic.

    Returns the number of crops inserted. Zero is a valid result (no
    campaign creatives detected on the page) and is not an error.

    Best-effort: a download failure or a localization failure logs at
    WARNING and returns 0. The full-page evidence row is unaffected.
    """
    if not campaign_assets:
        return 0
    if not evidence_url:
        return 0

    try:
        screenshot_bytes = await ai_service.download_image(evidence_url)
    except Exception as e:
        log.warning(
            "Could not fetch SS1 capture %s for CV localization: %s",
            evidence_url[:80], e,
        )
        return 0

    try:
        crops = await _localize_and_crop_assets(
            screenshot_bytes, scan_job_id, campaign_assets,
        )
    except Exception as e:
        log.warning(
            "CV localization failed for %s: %s", evidence_url[:80], e,
        )
        return 0

    if not crops:
        return 0

    inserted = 0
    for crop in crops:
        try:
            _safe_insert_discovered_image({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": page_url,
                "image_url": crop["src"],
                "source_type": "extracted_image",
                "channel": "website",
                "metadata": {
                    "extraction_method": "cv_localized_from_screenshot",
                    "viewport": "screenshotone_full_page",
                    "element_tag": crop.get("tag", "cv-localized-crop"),
                    "original_width": crop.get("width"),
                    "original_height": crop.get("height"),
                    "position": {
                        "x": crop.get("x", 0),
                        "y": crop.get("y", 0),
                    },
                    "css_classes": crop.get("classes", ""),
                    "evidence_screenshot_url": evidence_url,
                },
            })
            inserted += 1
        except Exception as e:
            log.warning("Failed to insert CV crop row: %s", e)

    log.info(
        "CV localization inserted %d crop(s) from SS1 capture of %s",
        inserted, page_url,
    )
    return inserted


def _classify_location(y: int, page_height: int) -> str:
    """Classify an image's position on the page."""
    ratio = y / max(page_height, 1)
    if ratio < 0.15:
        return "header"
    elif ratio < 0.5:
        return "main_content"
    elif ratio < 0.8:
        return "mid_page"
    return "footer"


# --- Block / failure classification helpers ---------------------------------
#
# These are heuristics that turn raw Playwright/Chromium errors into the
# normalized OUTCOME_* values the runner can act on. The strings come from
# Chromium's net error names; full list:
# https://chromium.googlesource.com/chromium/src/+/refs/heads/main/net/base/net_error_list.h
_BLOCK_NET_ERRORS = (
    "ERR_ABORTED",                  # WAF / cancelled by server
    "ERR_BLOCKED_BY_CLIENT",
    "ERR_BLOCKED_BY_RESPONSE",
    "ERR_HTTP_RESPONSE_CODE_FAILURE",
    "ERR_TOO_MANY_REDIRECTS",
    "ERR_SSL_PROTOCOL_ERROR",
    "ERR_CERT_",                    # any cert error
)

_TARGET_CLOSED_MARKERS = (
    "Target page, context or browser has been closed",
    "Target closed",
    "TargetClosedError",
)


def _classify_playwright_error(exc: BaseException) -> Tuple[str, Optional[str]]:
    """Map a Playwright exception to (outcome, block_reason).

    Returns (OUTCOME_TIMEOUT, None) for navigation timeouts,
    (OUTCOME_BLOCKED, "ERR_XYZ") for known anti-bot signatures,
    (OUTCOME_CRASHED, "browser_closed") if the browser was torn down under
    us, or (OUTCOME_CRASHED, str(exc)[:200]) for anything else.
    """
    if isinstance(exc, PlaywrightTimeout):
        return OUTCOME_TIMEOUT, None
    msg = str(exc)
    for marker in _TARGET_CLOSED_MARKERS:
        if marker in msg:
            return OUTCOME_CRASHED, "browser_closed"
    for sig in _BLOCK_NET_ERRORS:
        if sig in msg:
            return OUTCOME_BLOCKED, sig
    return OUTCOME_CRASHED, msg.splitlines()[0][:200] if msg else "unknown"


async def _attempt_extraction(
    url: str,
    scan_job_id: UUID,
    distributor_id: Optional[UUID],
    mobile: bool,
    seen_srcs: set,
    campaign_assets: Optional[List[Dict[str, Any]]],
    img_buffer: DiscoveredImageBuffer,
) -> ExtractionResult:
    """Single end-to-end attempt: open page, navigate, extract, screenshot.

    Always closes its own context. Never recycles the shared browser.
    The caller decides whether to retry, switch viewport, or fall back to
    a hosted screenshot service.
    """
    viewport_label = "mobile" if mobile else "desktop"
    browser = await _get_browser()
    try:
        page = await _new_page(browser, mobile=mobile)
    except Exception as e:
        # Most commonly: TargetClosedError because another task triggered
        # a recycle. Re-acquire and try one more time before giving up.
        outcome, reason = _classify_playwright_error(e)
        if outcome == OUTCOME_CRASHED and reason == "browser_closed":
            browser = await _get_browser()
            try:
                page = await _new_page(browser, mobile=mobile)
            except Exception as e2:
                outcome2, reason2 = _classify_playwright_error(e2)
                return ExtractionResult(
                    outcome=outcome2, block_reason=reason2 or reason,
                )
        else:
            return ExtractionResult(outcome=outcome, block_reason=reason)

    evidence_url: Optional[str] = None
    nav_status: Optional[int] = None
    nav_outcome: Optional[str] = None
    nav_reason: Optional[str] = None
    added = 0

    try:
        try:
            response = await page.goto(
                url, wait_until="domcontentloaded",
                timeout=settings.playwright_timeout,
            )
            if response is not None:
                nav_status = response.status
                if nav_status >= 400:
                    nav_outcome = OUTCOME_BLOCKED
                    nav_reason = f"HTTP {nav_status}"
        except Exception as nav_exc:
            outcome, reason = _classify_playwright_error(nav_exc)
            log.error(
                "Navigation failed for %s (%s) — outcome=%s reason=%s",
                url, viewport_label, outcome, reason,
            )
            return ExtractionResult(outcome=outcome, block_reason=reason)

        await asyncio.sleep(2)
        await _dismiss_overlays(page)
        await _scroll_to_bottom(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        images = await _extract_images_from_page(page)
        pre_carousel_srcs = {img["src"] for img in images}
        carousel_images = await _advance_carousels(page)
        for img in carousel_images:
            if img["src"] not in pre_carousel_srcs:
                images.append(img)

        page_height = await page.evaluate("document.body.scrollHeight")
        screenshot_bytes = await page.screenshot(full_page=True, type="png")
        evidence_url = await _upload_screenshot(
            screenshot_bytes, scan_job_id, f"{url}#_{viewport_label}",
        )

        if campaign_assets:
            localized = await _localize_and_crop_assets(
                screenshot_bytes, scan_job_id, campaign_assets,
            )
            images.extend(localized)
            log.info("CV localization added %d cropped creative(s)", len(localized))

        log.info(
            "Found %d images+sections (%s) on %s",
            len(images), viewport_label, url,
        )

        for img in images:
            if img["src"] in seen_srcs:
                continue
            seen_srcs.add(img["src"])
            location = _classify_location(img["y"], page_height)
            img_buffer.add({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": url,
                "image_url": img["src"],
                "source_type": "extracted_image",
                "channel": "website",
                "metadata": {
                    "extraction_method": "playwright",
                    "viewport": viewport_label,
                    "element_tag": img["tag"],
                    "original_width": img["width"],
                    "original_height": img["height"],
                    "position": {"x": img["x"], "y": img["y"]},
                    "page_location": location,
                    "alt_text": img["alt"],
                    "css_classes": img["classes"],
                    "evidence_screenshot_url": evidence_url,
                },
            })
            added += 1

    except Exception as e:
        outcome, reason = _classify_playwright_error(e)
        log.error(
            "Mid-extraction error on %s (%s): %s (outcome=%s)",
            url, viewport_label, e, outcome,
        )
        return ExtractionResult(
            count=added, evidence_url=evidence_url,
            outcome=outcome, block_reason=reason,
            http_status=nav_status,
        )
    finally:
        try:
            await page.context.close()
        except Exception:
            pass

    if nav_outcome == OUTCOME_BLOCKED:
        # Navigation returned 4xx/5xx. We may have a screenshot of the
        # error page; surface that as block evidence rather than as a
        # successful scan.
        return ExtractionResult(
            count=0, evidence_url=evidence_url,
            outcome=OUTCOME_BLOCKED, block_reason=nav_reason,
            http_status=nav_status,
        )

    if added > 0:
        return ExtractionResult(
            count=added, evidence_url=evidence_url,
            outcome=OUTCOME_IMAGES, http_status=nav_status,
        )
    return ExtractionResult(
        count=0, evidence_url=evidence_url,
        outcome=OUTCOME_EMPTY, http_status=nav_status,
    )


async def _extract_from_viewport(
    url: str,
    scan_job_id: UUID,
    distributor_id: Optional[UUID],
    mobile: bool,
    seen_srcs: set,
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> ExtractionResult:
    """Try once, retry once on transient failure, return a structured result.

    The retry uses a fresh BrowserContext — and re-acquires the shared
    browser if a TargetClosedError was raised — but never tears down the
    process-wide browser singleton. That avoids the friendly-fire cascade
    where one slow site's recycle would close every other in-flight page.
    """
    img_buffer = DiscoveredImageBuffer()

    result = await _attempt_extraction(
        url=url, scan_job_id=scan_job_id, distributor_id=distributor_id,
        mobile=mobile, seen_srcs=seen_srcs, campaign_assets=campaign_assets,
        img_buffer=img_buffer,
    )

    # Retry once if the first attempt was transient (timeout / crashed /
    # blocked-with-no-evidence). We do NOT retry blocks that already have
    # a screenshot — those are real WAF responses, not flakes.
    transient = (
        result.outcome in (OUTCOME_TIMEOUT, OUTCOME_CRASHED)
        or (result.outcome == OUTCOME_BLOCKED and result.evidence_url is None)
    )
    if transient and result.count == 0:
        log.info(
            "Retrying %s (%s) — first attempt outcome=%s reason=%s",
            url, "mobile" if mobile else "desktop",
            result.outcome, result.block_reason,
        )
        retry = await _attempt_extraction(
            url=url, scan_job_id=scan_job_id, distributor_id=distributor_id,
            mobile=mobile, seen_srcs=seen_srcs, campaign_assets=campaign_assets,
            img_buffer=img_buffer,
        )
        # Prefer the retry result, but keep the more informative
        # block_reason if the retry didn't find one.
        if retry.outcome != OUTCOME_CRASHED or result.outcome == OUTCOME_CRASHED:
            result = retry
        if result.block_reason is None:
            result.block_reason = retry.block_reason or result.block_reason

    flushed = img_buffer.flush_all()
    if flushed and result.outcome == OUTCOME_EMPTY:
        # Retry succeeded after first-pass empty.
        result.count = flushed
        result.outcome = OUTCOME_IMAGES
    else:
        result.count = max(result.count, flushed)
    return result


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


async def extract_dealer_website(
    url: str,
    scan_job_id: UUID,
    distributor_id: Optional[UUID] = None,
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> ExtractionResult:
    """Load a dealer page, extract images, and return a structured outcome.

    Delegates to :mod:`render_strategies` and :mod:`host_policy_service`
    so the choice of renderer (Playwright desktop, mobile-first,
    ScreenshotOne, ScreenshotOne+residential) is per-host learned data,
    not a hand-curated env var. First scan of a brand-new host pays for
    a 5s preflight probe + the full ladder; every scan after that goes
    straight to whatever already worked.

    The returned :class:`ExtractionResult` carries an optional
    ``ladder_attempts`` list on its ``block_reason`` when more than one
    rung was tried — the runner aggregates these into ``pipeline_stats``
    so the operator can see the escalation path.
    """
    log.info("Dealer website: %s", url)

    # Late imports to avoid a circular at module load (render_strategies
    # imports back into this file via late-import-inside-method).
    from . import host_policy_service, render_strategies

    try:
        strategy = await host_policy_service.ensure_policy(url)
    except Exception as e:
        # Never block a scan on a policy-table outage.
        log.warning("Host policy lookup failed for %s: %s", url, e)
        strategy = render_strategies.STRATEGY_PLAYWRIGHT_DESKTOP

    ctx = render_strategies.RenderContext(
        url=url,
        scan_job_id=scan_job_id,
        distributor_id=distributor_id,
        campaign_assets=campaign_assets,
    )
    ladder = await render_strategies.run_ladder(ctx, strategy=strategy)
    final = ladder.final

    # Stamp the attempt trail onto the block_reason so it lands in the
    # runner's per-page ``block_details`` row. Cheap to read in the
    # operator UI, and harmless when only one rung was tried.
    if len(ladder.attempts) > 1 and final.block_reason is None:
        trail = " -> ".join(
            f"{a.attempt}={a.outcome}" for a in ladder.attempts
        )
        final.block_reason = f"ladder({strategy}): {trail}"

    log.info(
        "Dealer page %s — strategy=%s succeeded=%s outcome=%s count=%d",
        url, strategy, ladder.succeeded_attempt or "<none>",
        final.outcome, final.count,
    )
    return final


async def discover_website_urls(
    website_urls: List[str],
) -> List[str]:
    """Expand base URLs into sub-pages via page discovery.

    Returns a deduplicated list of page URLs to scan, with promotional
    pages prioritized first.
    """
    from . import page_discovery

    if not settings.enable_page_discovery:
        return list(website_urls)

    expanded: List[str] = []
    seen: set = set()
    for url in website_urls:
        try:
            discovered = await page_discovery.discover_pages(
                url, max_pages=settings.max_pages_per_site,
            )
            for page_url in discovered:
                if page_url not in seen:
                    seen.add(page_url)
                    expanded.append(page_url)
        except Exception as e:
            log.error("Page discovery failed for %s: %s", url, e)
            if url not in seen:
                seen.add(url)
                expanded.append(url)

    log.info(
        "Page discovery: %d base URL(s) -> %d page(s)",
        len(website_urls), len(expanded),
    )
    return expanded


async def scan_dealer_websites(
    website_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Scan dealer websites by extracting individual images via Playwright
    and using OpenCV localization to find composed creatives.

    When page discovery is enabled, each base URL is expanded into
    multiple subpages (promotions, deals, etc.) before extraction.

    Falls back to full-page screenshot (tiling path) when a page yields
    zero extracted images and tiling fallback is enabled.

    Returns total discovered image count.
    """
    from . import page_discovery

    # Expand URLs via page discovery if enabled
    if settings.enable_page_discovery:
        expanded_urls: List[str] = []
        seen_urls: set = set()
        for url in website_urls:
            try:
                discovered = await page_discovery.discover_pages(
                    url, max_pages=settings.max_pages_per_site,
                )
                for page_url in discovered:
                    if page_url not in seen_urls:
                        seen_urls.add(page_url)
                        expanded_urls.append(page_url)
            except Exception as e:
                log.error("Page discovery failed for %s: %s", url, e)
                if url not in seen_urls:
                    seen_urls.add(url)
                    expanded_urls.append(url)
        log.info(
            "Page discovery: %d base URL(s) -> %d page(s)",
            len(website_urls), len(expanded_urls),
        )
        website_urls = expanded_urls

    log.info("Starting website scan for %d URLs", len(website_urls))
    if campaign_assets:
        log.info("CV localization enabled with %d campaign asset(s)", len(campaign_assets))
    total = 0
    semaphore = asyncio.Semaphore(settings.max_concurrent_pages)

    async def _process_url(url: str) -> int:
        async with semaphore:
            distributor_id = _match_distributor_by_domain(url, distributor_mapping)
            res = await extract_dealer_website(
                url, scan_job_id, distributor_id, campaign_assets=campaign_assets,
            )

            if (
                res.count == 0
                and settings.enable_tiling_fallback
                and res.evidence_url
                and res.outcome != OUTCOME_BLOCKED
            ):
                log.info("Zero images extracted from %s — inserting screenshot for tiling fallback", url)
                _safe_insert_discovered_image({
                    "scan_job_id": str(scan_job_id),
                    "distributor_id": str(distributor_id) if distributor_id else None,
                    "source_url": url,
                    "image_url": res.evidence_url,
                    "source_type": "page_screenshot",
                    "channel": "website",
                    "metadata": {
                        "capture_method": "playwright_fallback",
                        "full_page": True,
                        "reason": "no_images_extracted",
                    },
                })
                return 1
            return res.count

    results = await asyncio.gather(
        *[_process_url(url) for url in website_urls],
        return_exceptions=True,
    )
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            log.error("Error processing %s: %s", website_urls[i], r)
        else:
            total += r

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": total,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    log.info("Website scan complete: %d discovered images", total)
    return total


async def _extract_ads_from_viewport(
    target_url: str,
    scan_job_id: UUID,
    distributor_id: Optional[UUID],
    channel: str,
    mobile: bool,
    seen_srcs: set,
    extra_metadata: Optional[Dict[str, Any]] = None,
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[int, Optional[str], set]:
    """
    Generic ad-page extraction for a single viewport. Works for Google Ads
    Transparency and Meta Ad Library pages.
    """
    viewport_label = "mobile" if mobile else "desktop"
    browser = await _get_browser()
    page = await _new_page(browser, mobile=mobile)
    img_buffer = DiscoveredImageBuffer()
    evidence_url = None

    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=settings.playwright_timeout)
        await asyncio.sleep(5)
        await _dismiss_overlays(page)
        await _scroll_to_bottom(page, max_scrolls=10)

        page_height = await page.evaluate("document.body.scrollHeight")

        screenshot_bytes = await page.screenshot(full_page=True, type="png")
        evidence_url = await _upload_screenshot(screenshot_bytes, scan_job_id, f"{target_url}#_{viewport_label}")

        ad_images = await _extract_images_from_page(page)

        if campaign_assets:
            localized = await _localize_and_crop_assets(
                screenshot_bytes, scan_job_id, campaign_assets,
            )
            ad_images.extend(localized)

        log.info("Found %d images (%s) for %s", len(ad_images), viewport_label, target_url[:60])

        for img in ad_images:
            if img["src"] in seen_srcs:
                continue
            seen_srcs.add(img["src"])

            location = _classify_location(img["y"], page_height)
            meta = {
                "extraction_method": "playwright",
                "viewport": viewport_label,
                "element_tag": img["tag"],
                "original_width": img["width"],
                "original_height": img["height"],
                "position": {"x": img["x"], "y": img["y"]},
                "page_location": location,
                "alt_text": img["alt"],
                "evidence_screenshot_url": evidence_url,
            }
            if extra_metadata:
                meta.update(extra_metadata)

            img_buffer.add({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": target_url,
                "image_url": img["src"],
                "source_type": "extracted_image",
                "channel": channel,
                "metadata": meta,
            })

    except PlaywrightTimeout:
        log.error("Timeout loading %s (%s)", target_url[:60], viewport_label)
    except Exception as e:
        log.error("Error on %s (%s): %s", target_url[:60], viewport_label, e, exc_info=True)
    finally:
        try:
            await page.context.close()
        except Exception:
            pass

    extracted_count = img_buffer.flush_all()
    return extracted_count, evidence_url, seen_srcs


async def extract_google_ads_page(
    advertiser_id: str,
    scan_job_id: UUID,
    distributor_id: Optional[UUID] = None,
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[int, Optional[str]]:
    """
    Load a Google Ads Transparency page in a desktop viewport
    and extract individual ad creative images.

    Returns (count_of_extracted_images, evidence_screenshot_url).
    """
    transparency_url = (
        f"https://adstransparency.google.com/advertiser/{advertiser_id}"
        f"?region=anywhere"
    )
    log.info("Google Ads: %s", advertiser_id)
    seen_srcs: set = set()
    extra = {"advertiser_id": advertiser_id}

    count, evidence_url, seen_srcs = await _extract_ads_from_viewport(
        transparency_url, scan_job_id, distributor_id,
        channel="google_ads", mobile=False,
        seen_srcs=seen_srcs, extra_metadata=extra,
        campaign_assets=campaign_assets,
    )

    log.info("Extracted %d unique images for advertiser %s", count, advertiser_id)
    return count, evidence_url


async def scan_google_ads(
    advertiser_ids: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Scan Google Ads Transparency pages by extracting ad creative images.

    Validates advertiser IDs (must be AR-prefixed) and falls back to
    screenshot tiling when extraction yields zero images.

    Returns total discovered image count.
    """
    log.info("Starting Google Ads scan for %d advertisers", len(advertiser_ids))
    total = 0
    skipped = []

    for adv_id in advertiser_ids:
        if not adv_id or not adv_id.strip():
            continue

        adv_id = adv_id.strip()

        if not (adv_id.startswith("AR") and len(adv_id) > 2 and adv_id[2:].isdigit()):
            skipped.append(adv_id)
            log.warning("SKIPPED '%s' — not a valid advertiser ID", adv_id)
            continue

        distributor_id = (
            distributor_mapping.get(adv_id.lower())
            or distributor_mapping.get(adv_id)
        )

        count, evidence_url = await extract_google_ads_page(
            adv_id, scan_job_id, distributor_id,
            campaign_assets=campaign_assets,
        )

        if count == 0 and settings.enable_tiling_fallback and evidence_url:
            log.info("Zero images for %s — inserting screenshot for tiling fallback", adv_id)
            _safe_insert_discovered_image({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": f"https://adstransparency.google.com/advertiser/{adv_id}?region=anywhere",
                "image_url": evidence_url,
                "source_type": "page_screenshot",
                "channel": "google_ads",
                "metadata": {
                    "advertiser_id": adv_id,
                    "capture_method": "playwright_fallback",
                    "reason": "no_images_extracted",
                },
            })
            total += 1
        else:
            total += count

    if skipped:
        log.warning(
            "%d entries skipped — need valid AR-prefixed advertiser IDs",
            len(skipped),
        )

    if total == 0 and not skipped:
        error_msg = "No distributors found to scan"
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": error_msg,
        }).eq("id", str(scan_job_id)).execute()
        raise ValueError(error_msg)

    if total == 0 and skipped:
        error_msg = (
            f"No valid Google Ads Advertiser IDs found. "
            f"Distributors need IDs like 'AR18135649662495883265'. "
            f"Skipped: {', '.join(skipped[:3])}{'...' if len(skipped) > 3 else ''}"
        )
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": error_msg,
        }).eq("id", str(scan_job_id)).execute()
        raise ValueError(error_msg)

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": total,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    log.info("Google Ads scan complete: %d discovered images", total)
    return total


async def extract_facebook_ads_page(
    page_url: str,
    scan_job_id: UUID,
    distributor_id: Optional[UUID] = None,
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[int, Optional[str]]:
    """
    Load a Meta Ad Library page in a desktop viewport
    and extract individual ad creative images.

    Returns (count_of_extracted_images, evidence_screenshot_url).
    """
    page_name = page_url.rstrip("/").split("/")[-1]
    ad_library_url = (
        f"https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all"
        f"&country=US&q={quote(page_name)}&media_type=all"
    )
    log.info("Facebook Ads: %s", page_name)
    seen_srcs: set = set()
    extra = {"page_name": page_name, "original_url": page_url}

    count, evidence_url, seen_srcs = await _extract_ads_from_viewport(
        ad_library_url, scan_job_id, distributor_id,
        channel="facebook", mobile=False,
        seen_srcs=seen_srcs, extra_metadata=extra,
        campaign_assets=campaign_assets,
    )

    log.info("Extracted %d unique images for %s", count, page_name)
    return count, evidence_url


async def scan_facebook_ads(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Scan Facebook Ad Library pages by extracting ad creative images.

    Falls back to screenshot tiling when extraction yields zero images
    (common with Meta's anti-bot protections).

    Returns total discovered image count.
    """
    log.info("Starting Facebook scan for %d pages", len(page_urls))
    total = 0

    for page_url in page_urls:
        page_name = page_url.rstrip("/").split("/")[-1]

        distributor_id = None
        for name, dist_id in distributor_mapping.items():
            if name.lower() in page_name.lower() or page_name.lower() in name.lower():
                distributor_id = dist_id
                break

        count, evidence_url = await extract_facebook_ads_page(
            page_url, scan_job_id, distributor_id,
            campaign_assets=campaign_assets,
        )

        if count == 0 and settings.enable_tiling_fallback and evidence_url:
            log.info("Zero images for %s — inserting screenshot for tiling fallback", page_name)
            ad_library_url = (
                f"https://www.facebook.com/ads/library/"
                f"?active_status=active&ad_type=all"
                f"&country=US&q={quote(page_name)}&media_type=all"
            )
            _safe_insert_discovered_image({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": ad_library_url,
                "image_url": evidence_url,
                "source_type": "page_screenshot",
                "channel": "facebook",
                "metadata": {
                    "page_name": page_name,
                    "original_url": page_url,
                    "capture_method": "playwright_fallback",
                    "reason": "no_images_extracted",
                },
            })
            total += 1
        else:
            total += count

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": total,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    log.info("Facebook scan complete: %d discovered images", total)
    return total


def _match_distributor_by_domain(
    url: str,
    distributor_mapping: Dict[str, UUID],
) -> Optional[UUID]:
    """Match a URL to a distributor ID using domain-based lookup."""
    domain = url.replace("https://", "").replace("http://", "").split("/")[0].lower()
    for key, dist_id in distributor_mapping.items():
        if key.lower() in domain or domain in key.lower():
            return dist_id
    return None
