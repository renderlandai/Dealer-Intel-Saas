"""
Apify Meta Ad Library integration for Facebook & Instagram ad scraping.

Uses the nourishing_courier/meta-ads-scraper-pro actor to pull ad creatives
from Meta's Ad Library via GraphQL interception (more reliable than DOM scraping).

Each discovered ad image is inserted as a discovered_image so the existing
matching pipeline (hash → CLIP → Haiku → Opus) processes it like any other
discovered image.

Image URL resolution follows a 3-tier fallback:
  1. imageUrls from Apify (fastest, but Meta often omits them)
  2. videoUrls from Apify (sometimes contains thumbnail/poster)
  3. Playwright visits the Ad Library page and extracts the rendered creative
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.apify_meta")

settings = get_settings()

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "nourishing_courier~meta-ads-scraper-pro"

# Apify run statuses
_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
_POLL_INTERVAL_SEC = 5
_MAX_POLL_TIME_SEC = 300  # 5 minute ceiling per run

# Playwright fallback settings
_PW_AD_LIBRARY_TIMEOUT = 20_000  # 20s page load timeout
_PW_CONCURRENCY = 3  # max parallel browser pages for fallback


def _normalize_fb_url(url: str) -> str:
    """Ensure a Facebook URL is well-formed for the scraper."""
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://www.facebook.com/{url}"
    return url


def _extract_page_slug(url: str) -> str:
    """Extract the Facebook page slug/ID from a URL for matching purposes."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").split("/")[0] if parsed.path else ""
    return path.lower()


async def _start_actor_run(
    page_urls: List[str],
    *,
    max_ads: int = 200,
    country: str = "ALL",
    ad_status: str = "all",
    media_type: str = "all",
) -> dict:
    """Start an Apify actor run and return the run metadata."""
    actor_input = {
        "urls": [{"url": _normalize_fb_url(u)} for u in page_urls],
        "maxAds": max_ads,
        "country": country,
        "adStatus": ad_status,
        "mediaType": media_type,
        "includePageInsights": False,
        "includeCreativeDetails": True,
        "includeSpendData": False,
        "proxyConfiguration": {"useApifyProxy": True},
    }

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


def _build_url_to_distributor_map(
    page_urls: List[str],
    distributor_mapping: Dict[str, UUID],
) -> Dict[str, UUID]:
    """
    Build a slug→distributor_id lookup so we can match Apify results
    (which return pageName / pageId) back to our distributor records.

    The router passes distributor_mapping keyed by dealer *name* (lowercased).
    We also index by Facebook URL slug for a secondary match path.
    """
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


def _resolve_distributor(
    ad: Dict[str, Any],
    slug_map: Dict[str, UUID],
) -> Optional[UUID]:
    """Try to resolve which distributor this ad belongs to."""
    page_name = (ad.get("pageName") or "").lower()
    page_id = str(ad.get("pageId") or "")

    if page_name in slug_map:
        return slug_map[page_name]

    for key, dist_id in slug_map.items():
        if key in page_name or page_name in key:
            return dist_id

    if page_id and page_id in slug_map:
        return slug_map[page_id]

    return None


def _collect_media_urls(ad: Dict[str, Any]) -> List[str]:
    """
    Tier 1+2: collect image URLs from Apify response, falling back to
    videoUrls if imageUrls is empty.
    """
    urls: List[str] = []

    for img_url in (ad.get("imageUrls") or []):
        if img_url and img_url.startswith("http"):
            urls.append(img_url)

    if not urls:
        for vid_url in (ad.get("videoUrls") or []):
            if vid_url and vid_url.startswith("http"):
                urls.append(vid_url)

    return urls


async def _extract_image_from_ad_library(ad_library_url: str) -> List[str]:
    """
    Tier 3: visit the Meta Ad Library page in Playwright and extract the
    rendered ad creative image URL(s) from the DOM.

    The Ad Library is public — no login required.
    """
    from .extraction_service import _get_browser, _new_page

    extracted: List[str] = []
    browser = await _get_browser()
    page = await _new_page(browser, mobile=False)

    try:
        await page.goto(ad_library_url, wait_until="domcontentloaded", timeout=_PW_AD_LIBRARY_TIMEOUT)
        await asyncio.sleep(4)

        # Meta Ad Library renders creatives inside specific containers.
        # We look for large images inside the ad card area.
        image_urls = await page.evaluate("""() => {
            const seen = new Set();
            const results = [];

            // Primary: images inside the ad creative container
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

            // Fallback: any large image on the page
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
    """
    For every ad that has no imageUrls/videoUrls, use Playwright to visit the
    Ad Library page and extract the creative. Returns {adId: [url, ...]}.

    Runs up to _PW_CONCURRENCY pages in parallel via a semaphore.
    """
    sem = asyncio.Semaphore(_PW_CONCURRENCY)
    results: Dict[str, List[str]] = {}

    async def _resolve_one(ad: Dict[str, Any]):
        ad_id = ad.get("adId", "")
        ad_url = ad.get("adUrl") or f"https://www.facebook.com/ads/library/?id={ad_id}"
        if not ad_id:
            return
        async with sem:
            urls = await _extract_image_from_ad_library(ad_url)
            if urls:
                results[ad_id] = urls

    needs_fallback = [
        ad for ad in ads
        if ad.get("type") != "pageInsight"
        and not _collect_media_urls(ad)
        and (ad.get("adId") or ad.get("adUrl"))
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


async def scan_meta_ads(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    *,
    channel: str = "facebook",
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Scan Meta Ad Library via Apify for Facebook/Instagram ad creatives.

    1. Starts the Apify actor with the supplied Facebook page URLs
    2. Polls until the run completes
    3. Resolves image URLs via 3-tier fallback (imageUrls → videoUrls → Playwright)
    4. Inserts each ad image as a discovered_image for the matching pipeline

    Returns total number of discovered images inserted.
    """
    if not settings.apify_api_key:
        raise ValueError(
            "APIFY_API_KEY is not configured. "
            "Set it in your .env file to enable Meta Ads scanning."
        )

    if not page_urls:
        raise ValueError("No Facebook page URLs provided for Meta Ads scan.")

    log.info(
        "Starting Apify Meta Ads scan (%s) for %d page(s)", channel, len(page_urls)
    )

    # 1. Start the actor run
    run_info = await _start_actor_run(page_urls)
    run_id = run_info["id"]
    log.info("Apify actor run started: %s", run_id)

    supabase.table("scan_jobs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    # 2. Poll until complete
    try:
        completed_run = await _poll_run(run_id)
    except TimeoutError:
        log.error("Apify run %s timed out", run_id)
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": f"Apify run timed out after {_MAX_POLL_TIME_SEC}s",
        }).eq("id", str(scan_job_id)).execute()
        raise

    if completed_run["status"] != "SUCCEEDED":
        error_msg = f"Apify run finished with status: {completed_run['status']}"
        log.error(error_msg)
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": error_msg,
        }).eq("id", str(scan_job_id)).execute()
        raise RuntimeError(error_msg)

    # 3. Fetch dataset items
    dataset_id = completed_run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError("Apify run succeeded but no dataset ID returned")

    ads = await _fetch_dataset_items(dataset_id)
    log.info("Apify returned %d ad item(s)", len(ads))

    try:
        from . import cost_tracker
        cost_tracker.record_apify_run(
            actor_or_task=ACTOR_ID,
            run_id=run_id,
            usage_total_usd=completed_run.get("usageTotalUsd"),
            items_returned=len(ads),
        )
    except Exception as cost_err:
        log.debug("Cost capture skipped (apify meta): %s", cost_err)

    # Log raw payload keys for debugging (first ad only)
    if ads:
        sample = ads[0]
        log.info(
            "Sample ad payload keys: %s | imageUrls=%d, videoUrls=%d",
            list(sample.keys()),
            len(sample.get("imageUrls") or []),
            len(sample.get("videoUrls") or []),
        )
        log.debug("Full sample ad payload: %s", json.dumps(sample, default=str)[:2000])

    if not ads:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        log.warning("No ads found for the provided pages")
        return 0

    # 4. Playwright fallback: resolve images for ads missing URLs
    pw_resolved = await _resolve_images_for_ads(ads)

    # 5. Build lookup for distributor resolution
    slug_map = _build_url_to_distributor_map(page_urls, distributor_mapping)

    # 6. Insert each ad image as a discovered_image
    total_inserted = 0
    ads_with_images = 0
    ads_skipped = 0

    for ad in ads:
        ad_type = ad.get("type", "")
        if ad_type == "pageInsight":
            continue

        ad_id = ad.get("adId", "")
        ad_url = ad.get("adUrl", "")
        page_name = ad.get("pageName", "")
        platforms = ad.get("platforms") or []
        ad_status = ad.get("status", "")
        start_date = ad.get("startDate")
        media_type = ad.get("mediaType", "")

        # 3-tier image resolution
        image_urls = _collect_media_urls(ad)
        extraction_method = "apify_meta"

        if not image_urls and ad_id in pw_resolved:
            image_urls = pw_resolved[ad_id]
            extraction_method = "apify_meta+playwright_fallback"

        if not image_urls:
            log.warning(
                "No images resolved for ad %s (%s) — skipping",
                ad_id, page_name,
            )
            ads_skipped += 1
            continue

        ads_with_images += 1

        ad_channel = channel
        if "instagram" in platforms and "facebook" not in platforms:
            ad_channel = "instagram"

        distributor_id = _resolve_distributor(ad, slug_map)

        for img_url in image_urls:
            supabase.table("discovered_images").insert({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": ad_url or f"https://www.facebook.com/ads/library/?id={ad_id}",
                "image_url": img_url,
                "source_type": "extracted_image",
                "channel": ad_channel,
                "metadata": {
                    "extraction_method": extraction_method,
                    "apify_actor": ACTOR_ID,
                    "ad_id": ad_id,
                    "page_name": page_name,
                    "page_id": str(ad.get("pageId", "")),
                    "ad_status": ad_status,
                    "media_type": media_type,
                    "platforms": platforms,
                    "start_date": start_date,
                    "headline": ad.get("headline", ""),
                    "ad_text": (ad.get("adText") or "")[:500],
                },
            }).execute()
            total_inserted += 1

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
