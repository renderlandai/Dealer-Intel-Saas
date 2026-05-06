"""
Apify Meta Ad Library integration for Facebook & Instagram ad scraping.

Backed by the ``whoareyouanas/meta-ad-scraper`` actor. That actor only
accepts a single search per run (one ``targetUrl``, one ``pageId``, or
one ``searchQuery``), so we fan out — one actor run per dealer page —
and merge the results before handing them to the matcher.

Pipeline overview:

    1. ``_resolve_facebook_page_id`` turns each dealer's stored
       Facebook URL (slug form, e.g. ``facebook.com/somedealer``) into
       the numeric page ID the actor needs. HTTP-first with a
       Playwright fallback when Meta serves a logged-out wall.
    2. ``_run_actor_for_page`` starts one actor run per resolved
       dealer, polls until it finishes, and pulls the dataset items.
    3. Each ad is annotated with the source ``page_url`` so the
       distributor mapping is exact (no fuzzy brand-string matching
       across multiple dealers running in the same scan).
    4. Image URL resolution still has a 3-tier fallback:
         a) ``images: [{"url": ...}]`` from the actor (preferred)
         b) ``videos: [{"url": ..., "duration": ...}]`` (poster/thumb)
         c) Playwright visits ``facebook.com/ads/library/?id=<libraryID>``
            and extracts the rendered creative

Each discovered ad image is inserted as a ``discovered_images`` row so
the existing matching pipeline (hash → CLIP → Haiku → Opus) processes
it like any other discovered image.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase
from .bulk_writers import DiscoveredImageBuffer

log = logging.getLogger("dealer_intel.apify_meta")

settings = get_settings()

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "whoareyouanas~meta-ad-scraper"

# Apify run statuses we treat as terminal (the run will not progress
# further, regardless of whether it succeeded).
_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
# Poll cadence and ceiling are configurable via settings — Meta Ad
# Library runs for high-ad-volume dealers can take 10-15 minutes.
_POLL_INTERVAL_SEC = settings.apify_poll_interval_seconds
_MAX_POLL_TIME_SEC = settings.apify_max_poll_seconds

# Playwright fallback settings (shared with the slug→pageId resolver).
_PW_AD_LIBRARY_TIMEOUT = 20_000  # 20s page load timeout
_PW_CONCURRENCY = 3  # max parallel browser pages for fallback

# ---------------------------------------------------------------------------
# Slug → numeric page ID resolution
# ---------------------------------------------------------------------------
#
# The ``whoareyouanas/meta-ad-scraper`` actor accepts only one
# search per run, identified by ``pageId`` (numeric), ``targetUrl``
# (already-formed Ad Library URL containing ``view_all_page_id``), or
# a free-text ``searchQuery``. Our distributor table only stores the
# slug form (``facebook.com/somedealer``), so we resolve slug → pageId
# at scan time.
#
# The numeric ID is embedded in several places on Facebook's
# server-rendered HTML:
#
#   * ``<meta property="al:android:url" content="fb://page/?id=NUMERIC">``
#   * ``<meta property="al:ios:url" content="fb://profile/NUMERIC">``
#   * Inline JSON: ``"pageID":"NUMERIC"`` / ``"entity_id":"NUMERIC"``
#
# We try each pattern on the desktop site, then ``m.facebook.com`` (the
# mobile site is often less aggressive about logged-out gating), and
# only spin up a Playwright session as a final fallback.

_PAGE_ID_PATTERNS = [
    re.compile(r'al:android:url"\s*content="fb://page/\?id=(\d+)"'),
    re.compile(r'al:ios:url"\s*content="fb://profile/(\d+)"'),
    re.compile(r'"pageID"\s*:\s*"(\d+)"'),
    re.compile(r'"entity_id"\s*:\s*"(\d+)"'),
    # Newer Meta surfaces use these keys interchangeably; cover all of
    # them to keep the resolver robust against minor markup churn.
    re.compile(r'"page_id"\s*:\s*"(\d+)"'),
    re.compile(r'"profile_id"\s*:\s*"(\d+)"'),
]

# Lightweight in-process cache for a single scan run. Resolving the
# same dealer twice within seconds is wasteful and slightly increases
# the chance of triggering Meta's bot heuristics. Cleared at process
# restart; we don't persist to Supabase to keep this change zero-
# schema-impact (per the input-strategy decision recorded in log.md).
_PAGE_ID_CACHE: Dict[str, str] = {}


async def _http_resolve_page_id(slug: str) -> Optional[str]:
    """First-pass resolver: a plain GET against facebook.com/<slug> and
    m.facebook.com/<slug>, scanning the response body for any of
    ``_PAGE_ID_PATTERNS``.

    Uses a desktop user-agent because Meta returns slightly different
    markup to "modern" UAs and the mobile UA path occasionally
    redirects to a barebones logged-out wall with no ID embedded.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    candidate_urls = [
        f"https://www.facebook.com/{slug}",
        f"https://m.facebook.com/{slug}",
    ]
    async with httpx.AsyncClient(
        timeout=15.0, follow_redirects=True, headers=headers,
    ) as client:
        for url in candidate_urls:
            try:
                resp = await client.get(url)
            except Exception as e:
                log.debug("HTTP page-id probe failed for %s: %s", url, e)
                continue
            if resp.status_code >= 400:
                continue
            body = resp.text
            for pattern in _PAGE_ID_PATTERNS:
                m = pattern.search(body)
                if m:
                    return m.group(1)
    return None


async def _playwright_resolve_page_id(slug: str) -> Optional[str]:
    """Fallback resolver. Reuses the existing Playwright browser pool.

    Many Facebook pages serve a logged-out wall to anonymous HTTP
    clients but render the underlying page metadata when JS executes.
    We don't need to interact with anything — once the page has loaded
    we read ``window.__INITIAL_STATE__`` / meta tags directly.
    """
    try:
        from .extraction_service import _get_browser, _new_page
    except Exception as e:
        log.debug("Playwright unavailable for page-id resolution: %s", e)
        return None

    page = None
    try:
        browser = await _get_browser()
        page = await _new_page(browser, mobile=True)
        await page.goto(
            f"https://m.facebook.com/{slug}",
            wait_until="domcontentloaded",
            timeout=_PW_AD_LIBRARY_TIMEOUT,
        )
        # Brief settle so Meta's client-side hydration drops the page id
        # into a meta tag or inline script.
        await asyncio.sleep(2)
        page_id = await page.evaluate(
            """() => {
                const sel = (q) => document.querySelector(q)?.content || null;
                const m1 = sel('meta[property="al:android:url"]');
                if (m1) {
                    const m = m1.match(/id=(\\d+)/);
                    if (m) return m[1];
                }
                const m2 = sel('meta[property="al:ios:url"]');
                if (m2) {
                    const m = m2.match(/profile\\/(\\d+)/);
                    if (m) return m[1];
                }
                const html = document.documentElement.outerHTML;
                const patterns = [
                    /"pageID"\\s*:\\s*"(\\d+)"/,
                    /"entity_id"\\s*:\\s*"(\\d+)"/,
                    /"page_id"\\s*:\\s*"(\\d+)"/,
                    /"profile_id"\\s*:\\s*"(\\d+)"/,
                ];
                for (const p of patterns) {
                    const m = html.match(p);
                    if (m) return m[1];
                }
                return null;
            }"""
        )
        if page_id and str(page_id).isdigit():
            return str(page_id)
    except Exception as e:
        log.debug("Playwright page-id resolution failed for %s: %s", slug, e)
    finally:
        if page is not None:
            try:
                await page.context.close()
            except Exception:
                pass
    return None


async def _resolve_facebook_page_id(page_url: str) -> Optional[str]:
    """Resolve a Facebook page URL/slug to its numeric page ID.

    Returns ``None`` if neither the HTTP probe nor Playwright fallback
    can find one — the caller is expected to skip that dealer with a
    warning rather than fail the entire scan.
    """
    slug = _extract_page_slug(page_url)
    if not slug:
        return None
    if slug in _PAGE_ID_CACHE:
        return _PAGE_ID_CACHE[slug]

    page_id = await _http_resolve_page_id(slug)
    if not page_id:
        log.info(
            "HTTP page-id probe missed for %s — falling back to Playwright",
            slug,
        )
        page_id = await _playwright_resolve_page_id(slug)

    if page_id:
        _PAGE_ID_CACHE[slug] = page_id
        log.info("Resolved %s -> pageId=%s", slug, page_id)
    else:
        log.warning(
            "Could not resolve numeric page ID for %s. The "
            "whoareyouanas/meta-ad-scraper actor requires a pageId. "
            "Skipping this dealer for the current scan.", slug,
        )
    return page_id


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _normalize_fb_url(url: str) -> str:
    """Ensure a Facebook URL is well-formed."""
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://www.facebook.com/{url}"
    return url


def _extract_page_slug(url: str) -> str:
    """Extract the Facebook page slug/ID from a URL for matching purposes."""
    parsed = urlparse(_normalize_fb_url(url))
    path = parsed.path.strip("/").split("/")[0] if parsed.path else ""
    return path.lower()


def _ad_library_url_for(library_id: str) -> str:
    """Construct a permalink Ad Library URL from a libraryID. The new
    actor doesn't return one directly; we synthesise the canonical
    form used by Meta itself."""
    return f"https://www.facebook.com/ads/library/?id={library_id}"


# ---------------------------------------------------------------------------
# Apify run wrappers
# ---------------------------------------------------------------------------

async def _start_actor_run(
    *,
    page_id: str,
    country: str = "US",
    active_status: str = "all",
    media_type: str = "all",
    sort_mode: str = "start_date",
    sort_direction: str = "desc",
    max_concurrency: int = 1,
    request_timeout_secs: int = 900,
) -> dict:
    """Start a single actor run keyed on ``page_id``.

    The new actor accepts exactly one search per run — see the actor
    docs at https://apify.com/whoareyouanas/meta-ad-scraper. We sort
    by ``start_date`` descending so freshest creatives come first;
    this is the most useful default for scanning live campaigns.
    """
    actor_input: Dict[str, Any] = {
        "pageId": str(page_id),
        "country": country,
        "activeStatus": active_status,
        "adType": "all",
        "mediaType": media_type,
        "isTargetedCountry": False,
        "sortMode": sort_mode,
        "sortDirection": sort_direction,
        "maxConcurrency": max_concurrency,
        "requestHandlerTimeoutSecs": request_timeout_secs,
    }
    if settings.apify_meta_proxy_url:
        actor_input["proxyUrl"] = settings.apify_meta_proxy_url

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs",
            params={"token": settings.apify_api_key},
            json=actor_input,
        )
        resp.raise_for_status()
        return resp.json()["data"]


async def _poll_run(run_id: str) -> dict:
    """Poll until the actor run reaches a terminal status."""
    elapsed = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while elapsed < _MAX_POLL_TIME_SEC:
            resp = await client.get(
                f"{APIFY_BASE}/actor-runs/{run_id}",
                params={"token": settings.apify_api_key},
            )
            resp.raise_for_status()
            run_data = resp.json()["data"]

            status = run_data.get("status", "UNKNOWN")
            log.debug("Run %s status: %s (elapsed %ds)", run_id, status, elapsed)

            if status in _TERMINAL_STATUSES:
                return run_data

            await asyncio.sleep(_POLL_INTERVAL_SEC)
            elapsed += _POLL_INTERVAL_SEC

    raise TimeoutError(
        f"Apify run {run_id} did not complete within {_MAX_POLL_TIME_SEC}s"
    )


async def _fetch_dataset_items(dataset_id: str) -> List[Dict[str, Any]]:
    """Fetch all items from an Apify dataset."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"token": settings.apify_api_key, "format": "json"},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Distributor resolution (per fan-out)
# ---------------------------------------------------------------------------

def _build_url_to_distributor_map(
    page_urls: List[str],
    distributor_mapping: Dict[str, UUID],
) -> Dict[str, UUID]:
    """Build a slug→distributor_id lookup. The router passes
    ``distributor_mapping`` keyed by lowercased dealer name; we add a
    secondary index by Facebook URL slug so the per-page fan-out path
    can resolve via the source URL with zero ambiguity."""
    slug_map: Dict[str, UUID] = {}
    slug_map.update(distributor_mapping)

    for url in page_urls:
        slug = _extract_page_slug(url)
        if slug:
            for name, dist_id in distributor_mapping.items():
                if slug in name or name in slug:
                    slug_map[slug] = dist_id
                    break

    return slug_map


def _resolve_distributor_from_source(
    source_page_url: str,
    slug_map: Dict[str, UUID],
) -> Optional[UUID]:
    """Each ad now carries the dealer page URL that triggered its
    actor run, so distributor resolution is just slug-to-id (no fuzzy
    brand-name matching across multiple dealers in one scan)."""
    slug = _extract_page_slug(source_page_url)
    if slug and slug in slug_map:
        return slug_map[slug]
    return None


def _resolve_distributor_by_brand(
    ad: Dict[str, Any],
    slug_map: Dict[str, UUID],
) -> Optional[UUID]:
    """Fallback: match the ad's ``brand`` string against the dealer
    name index. Used only if the source-URL path failed (which
    shouldn't normally happen but is worth defending against in case
    we ever change how fan-outs are dispatched)."""
    brand = (ad.get("brand") or "").lower()
    if not brand:
        return None
    if brand in slug_map:
        return slug_map[brand]
    for key, dist_id in slug_map.items():
        if key in brand or brand in key:
            return dist_id
    return None


# ---------------------------------------------------------------------------
# Media URL extraction (new actor's shape)
# ---------------------------------------------------------------------------

def _collect_media_urls(ad: Dict[str, Any]) -> List[str]:
    """Pull http(s) URLs out of an ad item produced by the new actor.

    Schema:
        images: [{"url": "https://..."}]
        videos: [{"url": "https://...", "duration": 30}]

    Falls back from images to videos because Meta sometimes serves the
    poster image only via the video object."""
    urls: List[str] = []

    for img in (ad.get("images") or []):
        url = (img or {}).get("url") if isinstance(img, dict) else img
        if isinstance(url, str) and url.startswith("http"):
            urls.append(url)

    if not urls:
        for vid in (ad.get("videos") or []):
            url = (vid or {}).get("url") if isinstance(vid, dict) else vid
            if isinstance(url, str) and url.startswith("http"):
                urls.append(url)

    return urls


# ---------------------------------------------------------------------------
# Playwright tier-3 image extraction (kept as-is — operates on the
# permalink ad library URL, which is identical for both actors)
# ---------------------------------------------------------------------------

async def _extract_image_from_ad_library(ad_library_url: str) -> List[str]:
    """Tier 3: visit the Meta Ad Library page in Playwright and extract
    the rendered ad creative image URL(s) from the DOM."""
    from .extraction_service import _get_browser, _new_page

    extracted: List[str] = []
    browser = await _get_browser()
    page = await _new_page(browser, mobile=False)

    try:
        await page.goto(ad_library_url, wait_until="domcontentloaded", timeout=_PW_AD_LIBRARY_TIMEOUT)
        await asyncio.sleep(4)

        image_urls = await page.evaluate("""() => {
            const seen = new Set();
            const results = [];

            const adImages = document.querySelectorAll(
                'img[src*="scontent"], img[src*="fbcdn"], img[src*="facebook"]'
            );
            for (const img of adImages) {
                const src = img.currentSrc || img.src;
                if (!src || seen.has(src) || src.startsWith('data:')) continue;
                const w = img.naturalWidth || img.width;
                const h = img.naturalHeight || img.height;
                if (w < 100 || h < 100) continue;
                seen.add(src);
                results.push(src);
            }

            if (results.length === 0) {
                for (const img of document.querySelectorAll('img')) {
                    const src = img.currentSrc || img.src;
                    if (!src || seen.has(src) || src.startsWith('data:')) continue;
                    const w = img.naturalWidth || img.width;
                    const h = img.naturalHeight || img.height;
                    if (w < 150 || h < 150) continue;
                    seen.add(src);
                    results.push(src);
                }
            }

            return results;
        }""")

        extracted = [u for u in image_urls if u and u.startswith("http")]
        log.info(
            "Playwright extracted %d image(s) from Ad Library page: %s",
            len(extracted), ad_library_url[:80],
        )

    except Exception as e:
        log.warning(
            "Playwright fallback failed for %s: %s", ad_library_url[:80], e,
        )
    finally:
        try:
            await page.context.close()
        except Exception:
            pass

    return extracted


async def _resolve_images_for_ads(
    ads: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Resolve image URLs for ads where ``images`` and ``videos`` were
    both empty. Keyed by ``libraryID`` (the new actor's identifier)."""
    sem = asyncio.Semaphore(_PW_CONCURRENCY)
    results: Dict[str, List[str]] = {}

    async def _resolve_one(ad: Dict[str, Any]):
        library_id = str(ad.get("libraryID") or "")
        if not library_id:
            return
        ad_url = _ad_library_url_for(library_id)
        async with sem:
            urls = await _extract_image_from_ad_library(ad_url)
            if urls:
                results[library_id] = urls

    needs_fallback = [
        ad for ad in ads
        if not _collect_media_urls(ad) and ad.get("libraryID")
    ]

    if not needs_fallback:
        return results

    log.info(
        "Playwright fallback needed for %d/%d ads with missing image URLs",
        len(needs_fallback), len(ads),
    )

    await asyncio.gather(*[_resolve_one(ad) for ad in needs_fallback])
    log.info("Playwright fallback resolved images for %d ads", len(results))
    return results


# ---------------------------------------------------------------------------
# Per-page fan-out
# ---------------------------------------------------------------------------

async def _run_actor_for_page(
    page_url: str,
    *,
    country: str = "US",
    active_status: str = "all",
    media_type: str = "all",
) -> Tuple[str, List[Dict[str, Any]], Optional[float], Optional[str]]:
    """Run one actor invocation for one dealer page.

    Returns ``(page_url, ads, usage_total_usd, run_id)``. Always
    returns — actor / network failures degrade to an empty ad list and
    a logged WARNING rather than raising, so one dealer's outage
    doesn't fail the whole multi-dealer scan.
    """
    page_id = await _resolve_facebook_page_id(page_url)
    if not page_id:
        return page_url, [], None, None

    try:
        run_info = await _start_actor_run(
            page_id=page_id,
            country=country,
            active_status=active_status,
            media_type=media_type,
        )
        run_id = run_info["id"]
        log.info(
            "Apify Meta run started for %s (pageId=%s): %s",
            _extract_page_slug(page_url), page_id, run_id,
        )

        completed = await _poll_run(run_id)
    except TimeoutError:
        log.error("Apify run for %s timed out", page_url)
        return page_url, [], None, None
    except Exception as e:
        log.warning("Apify run for %s failed to start/poll: %s", page_url, e)
        return page_url, [], None, None

    if completed.get("status") != "SUCCEEDED":
        log.warning(
            "Apify run for %s ended with status %s (run_id=%s)",
            page_url, completed.get("status"), completed.get("id"),
        )
        return page_url, [], completed.get("usageTotalUsd"), completed.get("id")

    dataset_id = completed.get("defaultDatasetId")
    if not dataset_id:
        log.warning("Run for %s succeeded but no dataset id returned", page_url)
        return page_url, [], completed.get("usageTotalUsd"), completed.get("id")

    try:
        ads = await _fetch_dataset_items(dataset_id)
    except Exception as e:
        log.warning("Dataset fetch for %s failed: %s", page_url, e)
        ads = []

    log.info("Apify Meta run for %s returned %d ad(s)", page_url, len(ads))
    return page_url, ads, completed.get("usageTotalUsd"), completed.get("id")


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def scan_meta_ads(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    *,
    channel: str = "facebook",
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Scan Meta Ad Library via the ``whoareyouanas/meta-ad-scraper``
    actor for Facebook/Instagram ad creatives.

    The signature is unchanged from the previous actor — callers pass a
    list of dealer Facebook URLs and we fan out internally.

    Steps:
        1. Resolve every page URL to its numeric Facebook pageId.
        2. Fan out actor runs in parallel (bounded by
           ``settings.apify_meta_max_parallel_runs``).
        3. For each ad, pull image URLs (3-tier fallback).
        4. Insert each image as a ``discovered_images`` row, tagging
           the source dealer via the page_url that triggered the run.

    Returns the total number of discovered images inserted.
    """
    if not settings.apify_api_key:
        raise ValueError(
            "APIFY_API_KEY is not configured. "
            "Set it in your .env file to enable Meta Ads scanning."
        )

    if not page_urls:
        raise ValueError("No Facebook page URLs provided for Meta Ads scan.")

    log.info(
        "Starting Apify Meta Ads scan (%s, actor=%s) for %d page(s) "
        "[fan-out parallelism=%d]",
        channel, ACTOR_ID, len(page_urls), settings.apify_meta_max_parallel_runs,
    )

    supabase.table("scan_jobs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    # 1+2: Fan out — bounded parallel actor runs.
    fan_sem = asyncio.Semaphore(max(1, settings.apify_meta_max_parallel_runs))

    async def _bounded(page_url: str):
        async with fan_sem:
            return await _run_actor_for_page(page_url, active_status="all")

    fan_results = await asyncio.gather(
        *[_bounded(u) for u in page_urls],
        return_exceptions=True,
    )

    # Aggregate ads from every fan-out, tagged with their source page.
    ads_by_source: List[Tuple[str, Dict[str, Any]]] = []
    total_actor_cost = 0.0
    successful_runs = 0
    for result in fan_results:
        if isinstance(result, BaseException):
            log.warning("Fan-out task crashed: %s", result)
            continue
        page_url, ads, cost_usd, run_id = result
        if cost_usd is not None:
            try:
                total_actor_cost += float(cost_usd)
            except Exception:
                pass
        if run_id:
            try:
                from . import cost_tracker
                cost_tracker.record_apify_run(
                    actor_or_task=ACTOR_ID,
                    run_id=run_id,
                    usage_total_usd=cost_usd,
                    items_returned=len(ads),
                )
            except Exception as cost_err:
                log.debug("Cost capture skipped (apify meta): %s", cost_err)
        if ads:
            successful_runs += 1
            for ad in ads:
                ads_by_source.append((page_url, ad))

    log.info(
        "Apify Meta fan-out complete: %d/%d dealers returned ads, "
        "%d ads total, $%.4f reported cost",
        successful_runs, len(page_urls), len(ads_by_source), total_actor_cost,
    )

    if not ads_by_source:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        log.warning("No ads found for any provided Facebook pages")
        return 0

    # Sample payload for debugging the wire format on first ad only.
    sample = ads_by_source[0][1]
    log.info(
        "Sample ad payload keys: %s | images=%d, videos=%d, brand=%s, libraryID=%s",
        list(sample.keys()),
        len(sample.get("images") or []),
        len(sample.get("videos") or []),
        sample.get("brand"),
        sample.get("libraryID"),
    )
    log.debug("Full sample ad payload: %s", json.dumps(sample, default=str)[:2000])

    # 3: Resolve images for ads missing imageUrls/videoUrls (Playwright tier).
    raw_ads = [ad for _, ad in ads_by_source]
    pw_resolved = await _resolve_images_for_ads(raw_ads)

    # 4: Distributor resolution + insertion.
    slug_map = _build_url_to_distributor_map(page_urls, distributor_mapping)
    img_buffer = DiscoveredImageBuffer()
    ads_with_images = 0
    ads_skipped = 0

    for source_page_url, ad in ads_by_source:
        library_id = str(ad.get("libraryID") or "")
        if not library_id:
            ads_skipped += 1
            continue

        ad_url = _ad_library_url_for(library_id)
        brand = ad.get("brand") or ""
        platforms = ad.get("platforms") or []
        active = ad.get("active")
        ad_status = "active" if active else ("inactive" if active is False else "")
        start_date = ad.get("startDate")
        media_format = ad.get("format") or ""

        # 3-tier image resolution.
        image_urls = _collect_media_urls(ad)
        extraction_method = "apify_meta"
        if not image_urls and library_id in pw_resolved:
            image_urls = pw_resolved[library_id]
            extraction_method = "apify_meta+playwright_fallback"

        if not image_urls:
            log.warning(
                "No images resolved for ad %s (%s) — skipping",
                library_id, brand,
            )
            ads_skipped += 1
            continue

        ads_with_images += 1

        # If the actor reports the ad ran ONLY on Instagram, surface
        # that — keeps the existing `instagram` channel split working.
        ad_channel = channel
        platforms_lc = [str(p).lower() for p in platforms]
        if "instagram" in platforms_lc and "facebook" not in platforms_lc:
            ad_channel = "instagram"

        distributor_id = (
            _resolve_distributor_from_source(source_page_url, slug_map)
            or _resolve_distributor_by_brand(ad, slug_map)
        )

        for img_url in image_urls:
            img_buffer.add({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": ad_url,
                "image_url": img_url,
                "source_type": "extracted_image",
                "channel": ad_channel,
                "metadata": {
                    "extraction_method": extraction_method,
                    "apify_actor": ACTOR_ID,
                    "library_id": library_id,
                    "brand": brand,
                    "ad_status": ad_status,
                    "media_format": media_format,
                    "platforms": platforms,
                    "start_date": start_date,
                    "link_title": ad.get("linkTitle", ""),
                    "link_url": ad.get("linkUrl", ""),
                    "cta_text": ad.get("ctaText", ""),
                    "cta_url": ad.get("ctaUrl", ""),
                    "body": (ad.get("body") or "")[:500],
                    "source_page_url": source_page_url,
                },
            })

    total_inserted = img_buffer.flush_all()

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": total_inserted,
    }).eq("id", str(scan_job_id)).execute()

    log.info(
        "Apify Meta Ads scan complete: %d images from %d ads "
        "(%d skipped, %d resolved via Playwright)",
        total_inserted, ads_with_images, ads_skipped, len(pw_resolved),
    )
    return total_inserted
