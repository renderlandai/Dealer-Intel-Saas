"""Bright Data Web Unlocker integration.

Replaces the previous ScreenshotOne fallback path. The Web Unlocker is a
single-call REST endpoint that handles residential / mobile IP routing,
JS challenge solving, fingerprinting, CAPTCHA solving, and cookie
warm-up server-side. We POST a URL, we get back the rendered post-DOM
HTML.

For our use case (catching co-op campaign creatives on dealer sites
behind Akamai / Cloudflare / Imperva) this is structurally better than
the SS1 ladder it replaces:

* SS1 returned a full-page PNG which the cv-localizer had to crop to
  find banner-sized regions. Most "captures" of WAF-protected sites
  were Akamai challenge pages, not real content; the matcher then
  produced false-positive "modified" verdicts on hero shots. See
  log.md 2026-04-29 for the full diagnostic.
* The Unlocker returns the *real* rendered HTML the dealer's customers
  see. We parse the same image set the existing Playwright path
  extracts (``<img>``, ``<picture>``, CSS ``background-image``) and
  insert each as its own ``discovered_images`` row. The matcher sees
  individual creatives, not full-page shots.

Why parse the HTML server-side instead of feeding it through Playwright
locally
----------------------------------------------------------------------
We never navigate to the protected URL with our own browser, so all the
WAF triggers (TLS fingerprint, IP rep, sensor data) are bypassed by
construction — they're handled by Bright Data. Re-rendering the
returned HTML in a local Chromium would add ~3s per page and a second
memory budget for no gain: the DOM is already final.

Best-effort error handling: any failure logs at WARNING and returns an
``OUTCOME_BLOCKED`` ``ExtractionResult`` so the runner records the
attempt without crashing the scan. Never raises.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
from uuid import UUID

import httpx
from bs4 import BeautifulSoup

from ..config import get_settings
from .bulk_writers import DiscoveredImageBuffer

log = logging.getLogger("dealer_intel.unlocker")

settings = get_settings()


# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

# Bright Data Web Unlocker accepts POSTs at this single endpoint. The token
# lives in the Authorization header; the zone (configured in their dashboard)
# is in the body — different zones have different proxy mixes / pricing.
BRIGHTDATA_REQUEST_URL = "https://api.brightdata.com/request"

# httpx timeout — Bright Data internally retries / waits on JS challenges,
# so a successful unlock can legitimately take 15-25s on heavy sites. 60s
# is comfortable; the runner-level timeout caps the overall page budget.
DEFAULT_UNLOCK_TIMEOUT = 60.0

# How long to cache an "unlocker is unreachable" smoke-test result before
# trying again. Set short enough that a transient outage doesn't disable
# the rung for hours, but long enough that we don't hammer BD when their
# auth is genuinely broken.
SMOKE_TEST_FAILURE_TTL_SECONDS = 300


# ---------------------------------------------------------------------------
# Runtime availability flag (set by smoke test in main.py lifespan)
# ---------------------------------------------------------------------------

# When False, ``run_ladder`` should treat any unlocker rung as failed
# without making the API call. Keeps a misconfigured deploy from quietly
# burning credits on guaranteed-400 requests for hours. Set by
# :func:`smoke_test` and cleared on a successful retry.
_unlocker_available: bool = True
_unlocker_disabled_at: float = 0.0
_smoke_test_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Per-host "needs unlocker for asset downloads too" registry
# ---------------------------------------------------------------------------
#
# When the unlocker successfully renders a page, the *images* on that
# page often live on the same WAF-protected origin (e.g. rent.cat.com's
# /content/dam/ CDN is gated by the same Akamai instance as the page
# itself). A plain httpx.get() of those image URLs hangs for 30s and
# times out — exactly what we saw on 2026-04-30 for wheeler-machinery
# logos.
#
# This in-process set is populated whenever ``unlock_and_extract``
# succeeds for a hostname, and consulted by ``ai_service.download_image``
# to decide whether to fetch the image bytes via the unlocker too. The
# set lives for the worker process lifetime; an unlocker eviction (host
# stops needing it) is rare enough that we don't bother with TTLs —
# next worker restart re-learns from the first scan.
_unlocked_hosts: Set[str] = set()


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def mark_host_unlocked(url_or_host: str) -> None:
    """Record that a hostname has at least one successful unlock under
    its belt. Subsequent image downloads for that host will be routed
    via the unlocker in :func:`download_via_unlocker`.
    """
    host = url_or_host if "://" not in url_or_host else _host_of(url_or_host)
    if host:
        _unlocked_hosts.add(host)


def host_needs_unlocker(url_or_host: str) -> bool:
    """Whether asset fetches for this host should go through the
    unlocker. ``ai_service.download_image`` calls this on every image
    URL; the cost is one set lookup."""
    host = url_or_host if "://" not in url_or_host else _host_of(url_or_host)
    return bool(host) and host in _unlocked_hosts


def is_available() -> bool:
    """Whether the unlocker has passed its most recent smoke test.

    Returns True by default — smoke_test() flips this to False on auth /
    connectivity failures. After ``SMOKE_TEST_FAILURE_TTL_SECONDS`` the
    flag self-resets so the next scan re-tries (operator may have
    rotated keys in the meantime). Also honours the master
    ``unlocker_fallback_enabled`` kill switch so an operator can disable
    the rung from config without restarting.
    """
    global _unlocker_available
    if not getattr(settings, "unlocker_fallback_enabled", True):
        return False
    if _unlocker_available:
        return True
    if (time.time() - _unlocker_disabled_at) > SMOKE_TEST_FAILURE_TTL_SECONDS:
        _unlocker_available = True
        return True
    return False


def _mark_unavailable() -> None:
    global _unlocker_available, _unlocker_disabled_at
    _unlocker_available = False
    _unlocker_disabled_at = time.time()


def _mark_available() -> None:
    global _unlocker_available
    _unlocker_available = True


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _api_token() -> str:
    """Read the API token from settings, falling back to env (lets a
    runtime override in dev work without rebuilding the settings cache)."""
    tok = getattr(settings, "brightdata_api_token", "") or os.getenv(
        "BRIGHTDATA_API_TOKEN", "",
    )
    return tok.strip()


def _zone_name() -> str:
    z = getattr(settings, "brightdata_unlocker_zone", "") or os.getenv(
        "BRIGHTDATA_UNLOCKER_ZONE", "",
    )
    return z.strip()


# ---------------------------------------------------------------------------
# HTTP call
# ---------------------------------------------------------------------------

async def _post_unlocker(
    url: str,
    *,
    min_body_bytes: int = 100,
) -> Tuple[Optional[bytes], Optional[int], Optional[str]]:
    """Make one POST to Bright Data Web Unlocker, returning raw bytes.

    Returns ``(body_bytes, http_status, error_reason)``. On success, the
    first two are populated and the third is None. On failure, the first
    is None and the third carries a short human-readable reason for the
    block_details row.

    ``min_body_bytes`` rejects suspiciously-tiny responses as failures.
    100 is the right floor for HTML (any real page is many KB); for
    image downloads the caller can lower it (a 1-pixel tracking GIF is
    ~43 bytes and would be a real, if useless, image).
    """
    token = _api_token()
    zone = _zone_name()
    if not token or not zone:
        return None, None, "brightdata_unconfigured"

    payload: Dict[str, Any] = {
        "zone": zone,
        "url": url,
        # `format=raw` returns the response body verbatim (rendered HTML
        # for HTML pages, binary for media). We never request `json` —
        # that wraps the body in metadata we don't need.
        "format": "raw",
        # Country hint: US datacenters tend to mirror the typical dealer
        # site audience and avoid geo-redirects to non-English pages.
        # Override per-host later if a foreign dealer needs it.
        "country": "us",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_UNLOCK_TIMEOUT) as client:
            resp = await client.post(
                BRIGHTDATA_REQUEST_URL, json=payload, headers=headers,
            )
    except httpx.TimeoutException:
        return None, None, "brightdata_timeout"
    except httpx.HTTPError as e:
        log.warning("Bright Data network error for %s: %s", url[:80], e)
        return None, None, f"brightdata_network_error: {str(e)[:80]}"

    if resp.status_code in (401, 403):
        # Auth-style failure — disable the rung for a while so we don't
        # keep paying for guaranteed errors.
        _mark_unavailable()
        log.error(
            "Bright Data auth/permission error (%d) for %s — disabling rung for %ds",
            resp.status_code, url[:80], SMOKE_TEST_FAILURE_TTL_SECONDS,
        )
        return None, resp.status_code, f"brightdata_auth_{resp.status_code}"

    if resp.status_code >= 400:
        # Show first 200 bytes in the log for diagnostic context. Force
        # latin-1 decode (1:1 byte->char) so we never crash on binary.
        snippet = resp.content[:200].decode("latin-1", errors="replace")
        log.warning(
            "Bright Data returned HTTP %d for %s: %s",
            resp.status_code, url[:80], snippet,
        )
        return None, resp.status_code, f"brightdata_http_{resp.status_code}"

    body = resp.content
    if not body or len(body) < min_body_bytes:
        # A "successful" unlock that returns ~0 bytes is almost always a
        # JS-only page where the unlocker didn't actually wait for the
        # render. Treat as failure rather than empty content.
        return None, resp.status_code, "brightdata_empty_response"

    return body, resp.status_code, None


async def _post_unlocker_text(url: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Convenience wrapper: returns the body decoded as UTF-8 text.

    Used for HTML page unlocks. Errors (transport / non-2xx / too small)
    are passed through unchanged. Decode failures fall back to latin-1
    so a page with a misdeclared charset still parses (BeautifulSoup
    will recover from the rest)."""
    body, status, err = await _post_unlocker(url)
    if body is None:
        return None, status, err
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("latin-1", errors="replace")
    return text, status, err


async def download_via_unlocker(image_url: str) -> Optional[bytes]:
    """Fetch an image's bytes through Bright Data.

    Used by ``ai_service.download_image`` when the image's host has
    been previously unlocked (and therefore is on the same WAF that
    blocks our direct httpx fetch). Returns the raw image bytes, or
    None on any failure — caller is responsible for retry / alternate
    handling. Records the cost just like a page unlock.
    """
    if not is_available():
        return None
    body, status, err = await _post_unlocker(image_url, min_body_bytes=20)
    try:
        from . import cost_tracker
        cost_tracker.record_unlocker(
            requests=1, target=image_url, succeeded=body is not None,
        )
    except Exception as cost_err:
        log.debug("Cost capture skipped (unlocker download): %s", cost_err)
    if body is None:
        log.warning(
            "Bright Data download failed for %s (http=%s err=%s)",
            image_url[:80], status, err,
        )
        return None
    return body


# ---------------------------------------------------------------------------
# HTML → image extraction
# ---------------------------------------------------------------------------

# These mirror the JS extraction in
# ``extraction_service._extract_images_from_page`` so the unlocker rung
# inserts the same shape of image rows as the Playwright rung. CSS
# selectors are the union of "ad-ish" container patterns we look for.
_BG_IMAGE_SELECTORS: Tuple[str, ...] = (
    '[class*="hero"]', '[class*="banner"]', '[class*="promo"]',
    '[class*="ad-"]', '[class*="ad_"]', '[class*="campaign"]',
    '[class*="slide"]', '[class*="carousel"]',
    '[class*="special"]', '[class*="deal"]', '[class*="offer"]',
    '[class*="feature"]', '[class*="incentive"]', '[class*="rebate"]',
    '[class*="savings"]', '[class*="coupon"]',
    '[role="banner"]', "header", ".jumbotron",
    'section[id*="special"]', 'section[id*="promo"]',
    'section[id*="deal"]', 'section[id*="offer"]',
    'div[id*="special"]', 'div[id*="promo"]',
    'div[id*="deal"]', 'div[id*="offer"]',
)


def _absolutize(src: str, base_url: str) -> Optional[str]:
    """Join a possibly-relative URL against ``base_url``. Returns None
    for unusable inputs (data: URIs, javascript:, empty)."""
    if not src:
        return None
    s = src.strip()
    if not s:
        return None
    if s.startswith("data:"):
        return None
    if s.startswith("javascript:"):
        return None
    try:
        abs_url = urljoin(base_url, s)
    except Exception:
        return None
    parsed = urlparse(abs_url)
    if parsed.scheme not in ("http", "https"):
        return None
    return abs_url


# Recognised image extensions, optionally followed by a query string or
# end-of-URL. Case-insensitive; matched anywhere in the path.
_IMAGE_EXT_RE = re.compile(
    r"\.(jpe?g|png|webp|gif|avif|svg|bmp|tiff?)(?:\?|$|/)",
    re.IGNORECASE,
)

# Substrings strongly suggestive of an image asset on enterprise CMSes.
# AEM (Adobe Experience Manager) — what cat.com uses — names rendered
# image variants `image.coreimg.<width>.<height>.<format>/...` so
# ``.coreimg.`` is a near-perfect signal. ``/dam/`` is AEM's Digital
# Asset Manager root. ``/image.`` covers other CMS conventions.
_IMAGE_HINT_SUBSTRINGS: Tuple[str, ...] = (
    ".coreimg.",
    "/image.",
    "/dam/",
)

# Substrings that almost always signal a non-image: AEM component paths
# like /_jcr_content/root/responsivegrid_<id> end at the component
# boundary, never at a file. Without this filter every AEM page leaks
# 4-12 component URLs that hang the downloader for 30s each.
_NON_IMAGE_SUBSTRINGS: Tuple[str, ...] = (
    "/_jcr_content/",
)


def _looks_like_image_url(url: str) -> bool:
    """Coarse heuristic: does this URL plausibly point at an image
    rather than a CMS component reference?

    Returns True for anything with a known image extension OR a known
    CMS asset-path marker. Returns False for AEM component paths
    (``/_jcr_content/.../responsivegrid_*``) and other ``-but-no-
    extension`` URLs.

    False positives (real image URLs we drop) cost us a missed match;
    false negatives (component URLs we keep) cost us a 30-second
    timeout in the analyzer. The asymmetry justifies the strict filter
    — operators can widen it if they see the funnel reject real images.
    """
    if not url:
        return False
    lower = url.lower()
    # Hard reject: AEM component paths can have an image extension at the
    # end (e.g. .../responsivegrid_*.html), but the typical leak is
    # extension-less. We only reject when the path contains the AEM
    # marker AND has no image extension downstream.
    if any(s in lower for s in _NON_IMAGE_SUBSTRINGS) and not _IMAGE_EXT_RE.search(lower):
        return False
    if _IMAGE_EXT_RE.search(lower):
        return True
    if any(s in lower for s in _IMAGE_HINT_SUBSTRINGS):
        return True
    return False


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        s = str(value).strip().rstrip("px").strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None


def _first_srcset_url(srcset: str) -> Optional[str]:
    """Pick the first URL out of a srcset attribute. (We could pick the
    largest, but the matcher is size-tolerant and the first descriptor
    is almost always the base resource.)"""
    if not srcset:
        return None
    first = srcset.split(",")[0].strip()
    if not first:
        return None
    return first.split()[0]


def _extract_bg_image_url(style_attr: str) -> Optional[str]:
    """Pull a single URL out of an inline ``background-image`` declaration.
    Returns None if the style attr doesn't carry one."""
    if not style_attr or "background" not in style_attr:
        return None
    # Cheap scan for url(...) — handles the four quoting forms (none,
    # single, double, no-quotes) without spinning up a real CSS parser.
    lower = style_attr
    idx = lower.find("url(")
    if idx == -1:
        return None
    end = lower.find(")", idx + 4)
    if end == -1:
        return None
    raw = lower[idx + 4:end].strip().strip('"').strip("'")
    if raw.startswith("data:"):
        return None
    return raw or None


def parse_images_from_html(
    html_text: str,
    base_url: str,
    min_width: int,
    min_height: int,
    max_images: int,
) -> List[Dict[str, Any]]:
    """Walk the rendered DOM and return a list of image dicts compatible
    with the rest of the extraction pipeline.

    Each dict has the same keys the Playwright JS extractor produces:
    ``src, width, height, alt, classes, tag, x, y``. Coordinates come
    from the DOM order (rough proxy — we don't have layout info because
    we never rendered) and are good enough for the
    ``_classify_location`` header/footer split downstream.
    """
    if not html_text:
        return []

    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception as e:
        log.warning("BeautifulSoup parse failed for %s: %s", base_url[:80], e)
        return []

    seen: Set[str] = set()
    results: List[Dict[str, Any]] = []
    rough_y = 0  # Monotonic counter — gives downstream a deterministic
    # ordering even though we have no layout info.

    def _push(src: str, width: Any, height: Any, alt: str, classes: str, tag: str) -> None:
        nonlocal rough_y
        if len(results) >= max_images:
            return
        abs_src = _absolutize(src, base_url)
        if not abs_src or abs_src in seen:
            return
        # URL-shape filter: drops AEM /_jcr_content/.../responsivegrid_*
        # placeholder paths and other extension-less component refs that
        # would 30s-timeout in ai_service.download_image. See
        # _looks_like_image_url for the heuristic.
        if not _looks_like_image_url(abs_src):
            return
        w = _parse_int(width) or 0
        h = _parse_int(height) or 0
        # Hard size gate: same defaults the JS extractor uses
        # (min_extracted_image_*). Unknown dims (w=0, h=0) pass through —
        # the downstream pipeline has its own size checks once it
        # downloads the actual bytes.
        if w and h and (w < min_width or h < min_height):
            return
        seen.add(abs_src)
        rough_y += 100
        results.append({
            "src": abs_src,
            "width": w or min_width,
            "height": h or min_height,
            "alt": alt or "",
            "classes": classes or "",
            "tag": tag,
            "x": 0,
            "y": rough_y,
        })

    # 1) <img> elements
    for img in soup.find_all("img"):
        src = img.get("currentsrc") or img.get("src") or ""
        if not src:
            # data-src lazy-loading fallback. BD typically fires lazy
            # observers during render so most of these will already have
            # ``src`` populated, but a few hand-rolled lazy implementations
            # don't.
            src = img.get("data-src") or img.get("data-original") or ""
        if not src:
            srcset = img.get("srcset") or ""
            picked = _first_srcset_url(srcset)
            if picked:
                src = picked
        _push(
            src=src,
            width=img.get("width"),
            height=img.get("height"),
            alt=img.get("alt", ""),
            classes=" ".join(img.get("class") or []),
            tag="img",
        )
        if len(results) >= max_images:
            return results

    # 2) <picture><source srcset=...>
    for pic in soup.find_all("picture"):
        for source in pic.find_all("source"):
            picked = _first_srcset_url(source.get("srcset", ""))
            if not picked:
                continue
            inner_img = pic.find("img")
            _push(
                src=picked,
                width=(inner_img.get("width") if inner_img else None),
                height=(inner_img.get("height") if inner_img else None),
                alt=(inner_img.get("alt", "") if inner_img else ""),
                classes=" ".join(pic.get("class") or []),
                tag="picture-source",
            )
            if len(results) >= max_images:
                return results
            break

    # 3) Inline-style background-image on common ad/promo containers.
    # We only catch *inline* background URLs; <style>-declared backgrounds
    # would require a CSS parser + computed-style resolver which we
    # decided to skip (cost > value at this stage).
    for selector in _BG_IMAGE_SELECTORS:
        try:
            elements = soup.select(selector)
        except Exception:
            continue
        for el in elements:
            url = _extract_bg_image_url(el.get("style", "") or "")
            if not url:
                continue
            _push(
                src=url,
                width=None,
                height=None,
                alt="",
                classes=" ".join(el.get("class") or []),
                tag="bg-image",
            )
            if len(results) >= max_images:
                return results

    return results


# ---------------------------------------------------------------------------
# Public orchestrator — called from render_strategies._UnlockerAttempt
# ---------------------------------------------------------------------------

async def unlock_and_extract(
    url: str,
    scan_job_id: UUID,
    distributor_id: Optional[UUID],
    seen_srcs: Set[str],
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
):
    """One pass of: unlocker → HTML parse → discovered_images inserts.

    Returns an ``ExtractionResult`` so the ladder can decide whether to
    stop. Late-imports ``extraction_service`` to avoid a circular dep at
    module load time.
    """
    from . import extraction_service  # noqa: F401  (circular-safe late import)

    if not is_available():
        log.info("Skipping unlocker for %s — rung disabled by smoke test", url[:80])
        return extraction_service.ExtractionResult(
            count=0,
            outcome=extraction_service.OUTCOME_BLOCKED,
            block_reason="brightdata_disabled_by_smoke_test",
        )

    token = _api_token()
    zone = _zone_name()
    if not token or not zone:
        log.warning(
            "Bright Data not configured (token=%s zone=%s); skipping unlocker for %s",
            "set" if token else "missing",
            "set" if zone else "missing",
            url[:80],
        )
        return extraction_service.ExtractionResult(
            count=0,
            outcome=extraction_service.OUTCOME_BLOCKED,
            block_reason="brightdata_unconfigured",
        )

    html_text, http_status, error = await _post_unlocker_text(url)

    # Cost recording: BD only bills successful unlocks but we record
    # every attempt with its outcome so the operator can see what they
    # spent vs. what they tried.
    try:
        from . import cost_tracker
        if html_text:
            cost_tracker.record_unlocker(
                requests=1, target=url, succeeded=True,
            )
    except Exception as cost_err:
        log.debug("Cost capture skipped (unlocker): %s", cost_err)

    if not html_text:
        return extraction_service.ExtractionResult(
            count=0,
            outcome=extraction_service.OUTCOME_BLOCKED,
            block_reason=error or "brightdata_unknown",
            http_status=http_status,
        )

    # Mark available again on any successful unlock (transient outages clear).
    _mark_available()

    # Tell ai_service.download_image to route image fetches for this
    # host through the unlocker too — the same WAF that gated the page
    # almost certainly gates the asset CDN. Without this, every <img>
    # we just extracted would 30s-timeout in the analyzer (the
    # 2026-04-30 wheeler-machinery symptom).
    mark_host_unlocked(url)

    # Mirror the size gates Playwright uses. Pull from settings so a
    # later operator change to those numbers stays in sync.
    images = parse_images_from_html(
        html_text,
        base_url=url,
        min_width=settings.min_extracted_image_width,
        min_height=settings.min_extracted_image_height,
        max_images=settings.max_images_per_page,
    )

    if not images:
        log.info(
            "Bright Data unlocked %s but found 0 matchable images (post-render DOM had no <img>/picture/bg matches)",
            url[:80],
        )
        return extraction_service.ExtractionResult(
            count=0,
            outcome=extraction_service.OUTCOME_EMPTY,
            http_status=http_status,
        )

    img_buffer = DiscoveredImageBuffer()
    added = 0
    for img in images:
        if img["src"] in seen_srcs:
            continue
        seen_srcs.add(img["src"])
        img_buffer.add({
            "scan_job_id": str(scan_job_id),
            "distributor_id": str(distributor_id) if distributor_id else None,
            "source_url": url,
            "image_url": img["src"],
            "source_type": "extracted_image",
            "channel": "website",
            "metadata": {
                # extraction_method tags the row so the operator can
                # trace which path produced it. ``brightdata_unlocker``
                # is the new sibling of ``playwright`` and
                # ``cv_localized_from_screenshot``.
                "extraction_method": "brightdata_unlocker",
                "viewport": "brightdata_render",
                "element_tag": img["tag"],
                "original_width": img["width"],
                "original_height": img["height"],
                "alt_text": img["alt"],
                "css_classes": img["classes"],
            },
        })
        added += 1

    flushed = img_buffer.flush_all()

    log.info(
        "Bright Data unlocked %s → %d image(s) inserted (parsed=%d, http=%s)",
        url[:80], flushed, len(images), http_status,
    )
    if flushed > 0:
        return extraction_service.ExtractionResult(
            count=flushed,
            outcome=extraction_service.OUTCOME_IMAGES,
            http_status=http_status,
        )
    return extraction_service.ExtractionResult(
        count=0,
        outcome=extraction_service.OUTCOME_EMPTY,
        http_status=http_status,
    )


# ---------------------------------------------------------------------------
# Boot-time smoke test (called from main.py lifespan)
# ---------------------------------------------------------------------------

# A short, cheap, predictable URL that should always unlock cleanly.
# example.com is owned by IANA, has no JS, and isn't WAF-protected, so
# a 200 from BD against it proves the auth + zone work end-to-end.
_SMOKE_TEST_URL = "https://example.com/"


async def smoke_test() -> Tuple[bool, str]:
    """Verify the unlocker actually authenticates and renders.

    Called once at API startup. On failure we keep the process running
    (fail-soft) but flip ``is_available()`` to False so every ladder
    that includes the unlocker rung will skip it cleanly. The flag
    self-resets after ``SMOKE_TEST_FAILURE_TTL_SECONDS`` so the next
    scan probes again — no full restart needed after fixing the key.
    """
    async with _smoke_test_lock:
        token = _api_token()
        zone = _zone_name()
        if not token or not zone:
            _mark_unavailable()
            return False, "BRIGHTDATA_API_TOKEN or BRIGHTDATA_UNLOCKER_ZONE missing"

        html_text, status, error = await _post_unlocker_text(_SMOKE_TEST_URL)
        if html_text and (status or 200) < 400:
            _mark_available()
            return True, f"OK (http={status}, len={len(html_text)})"
        _mark_unavailable()
        return False, f"smoke test failed (http={status}, error={error})"
