"""
Apify Meta Ad Library integration for Facebook & Instagram ad scraping.

Uses the nourishing_courier/meta-ads-scraper-pro actor to pull ad creatives
from Meta's Ad Library via GraphQL interception (more reliable than DOM scraping).

Each discovered ad image is inserted as a discovered_image so the existing
matching pipeline (hash → CLIP → Haiku → Opus) processes it like any other
discovered image.
"""
import asyncio
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
    3. Inserts each ad image as a discovered_image for the matching pipeline

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

    if not ads:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        log.warning("No ads found for the provided pages")
        return 0

    # 4. Build lookup for distributor resolution
    slug_map = _build_url_to_distributor_map(page_urls, distributor_mapping)

    # 5. Insert each ad image as a discovered_image
    total_inserted = 0
    for ad in ads:
        ad_type = ad.get("type", "")
        if ad_type == "pageInsight":
            continue

        image_urls = ad.get("imageUrls") or []
        if not image_urls:
            continue

        ad_id = ad.get("adId", "")
        ad_url = ad.get("adUrl", "")
        page_name = ad.get("pageName", "")
        platforms = ad.get("platforms") or []
        status = ad.get("status", "")
        start_date = ad.get("startDate")
        media_type = ad.get("mediaType", "")

        # Determine channel from platforms reported by Meta
        ad_channel = channel
        if "instagram" in platforms and "facebook" not in platforms:
            ad_channel = "instagram"

        distributor_id = _resolve_distributor(ad, slug_map)

        for img_url in image_urls:
            if not img_url or not img_url.startswith("http"):
                continue

            supabase.table("discovered_images").insert({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": ad_url or f"https://www.facebook.com/ads/library/?id={ad_id}",
                "image_url": img_url,
                "source_type": "extracted_image",
                "channel": ad_channel,
                "metadata": {
                    "extraction_method": "apify_meta",
                    "apify_actor": ACTOR_ID,
                    "ad_id": ad_id,
                    "page_name": page_name,
                    "page_id": str(ad.get("pageId", "")),
                    "ad_status": status,
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
        "Apify Meta Ads scan complete: %d images from %d ads inserted",
        total_inserted, len(ads),
    )
    return total_inserted
