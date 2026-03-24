"""
SerpApi integration for Google Ads Transparency Center.

Replaces the Playwright-based Google Ads scanning with structured API calls
that return direct creative image URLs, metadata, and pagination.

Each ad creative returned by SerpApi is inserted as a discovered_image so
the existing matching pipeline (hash → CLIP → Haiku → Opus) processes it
like any other discovered image.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.serpapi")

settings = get_settings()

SERPAPI_ENDPOINT = "https://serpapi.com/search"


async def _fetch_ad_creatives(
    advertiser_id: str,
    creative_format: str = "image",
    region: str = "anywhere",
    max_pages: int = 3,
) -> List[Dict[str, Any]]:
    """
    Fetch ad creatives from the Google Ads Transparency Center via SerpApi.

    Paginates automatically up to max_pages (each page returns ~40 results).
    Filters to the requested creative_format by default.
    """
    all_creatives: List[Dict[str, Any]] = []
    next_page_token: Optional[str] = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(max_pages):
            params: Dict[str, Any] = {
                "engine": "google_ads_transparency_center",
                "advertiser_id": advertiser_id,
                "api_key": settings.serpapi_api_key,
            }
            if creative_format:
                params["creative_format"] = creative_format
            if region:
                params["region"] = region
            if next_page_token:
                params["next_page_token"] = next_page_token

            log.debug("SerpApi request (page %d): advertiser=%s", page + 1, advertiser_id)

            resp = await client.get(SERPAPI_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

            creatives = data.get("ad_creatives", [])
            all_creatives.extend(creatives)

            pagination = data.get("serpapi_pagination", {})
            next_page_token = pagination.get("next_page_token")

            log.info(
                "SerpApi page %d: %d creatives (total so far: %d)",
                page + 1, len(creatives), len(all_creatives),
            )

            if not next_page_token or not creatives:
                break

            await asyncio.sleep(0.3)

    return all_creatives


async def scan_google_ads(
    advertiser_ids: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Scan Google Ads via SerpApi Transparency Center API.

    For each advertiser ID:
      1. Fetch ad creatives (image format) from SerpApi
      2. Insert each creative as a discovered_image
      3. The downstream matching pipeline handles comparison/compliance

    Returns total number of discovered images inserted.
    """
    if not settings.serpapi_api_key:
        raise ValueError(
            "SERPAPI_API_KEY is not configured. "
            "Set it in your .env file to enable Google Ads scanning."
        )

    log.info("Starting SerpApi Google Ads scan for %d advertisers", len(advertiser_ids))
    total = 0
    skipped: List[str] = []

    for adv_id in advertiser_ids:
        if not adv_id or not adv_id.strip():
            continue

        adv_id = adv_id.strip()

        if not (adv_id.startswith("AR") and len(adv_id) > 2 and adv_id[2:].isdigit()):
            skipped.append(adv_id)
            log.warning("SKIPPED '%s' — not a valid Google Ads advertiser ID", adv_id)
            continue

        distributor_id = (
            distributor_mapping.get(adv_id.lower())
            or distributor_mapping.get(adv_id)
        )

        try:
            creatives = await _fetch_ad_creatives(adv_id)
        except httpx.HTTPStatusError as e:
            log.error("SerpApi HTTP error for %s: %d", adv_id, e.response.status_code)
            continue
        except Exception as e:
            log.error("SerpApi error for %s: %s", adv_id, e)
            continue

        if not creatives:
            log.warning("No creatives found for advertiser %s", adv_id)
            continue

        inserted = 0
        for creative in creatives:
            image_url = creative.get("image")
            if not image_url:
                continue

            creative_id = creative.get("ad_creative_id", "")
            fmt = creative.get("format", "unknown")
            first_shown = creative.get("first_shown")
            last_shown = creative.get("last_shown")

            transparency_url = creative.get(
                "details_link",
                f"https://adstransparency.google.com/advertiser/{adv_id}/creative/{creative_id}",
            )

            supabase.table("discovered_images").insert({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": transparency_url,
                "image_url": image_url,
                "source_type": "extracted_image",
                "channel": "google_ads",
                "metadata": {
                    "extraction_method": "serpapi",
                    "advertiser_id": adv_id,
                    "advertiser_name": creative.get("advertiser", ""),
                    "ad_creative_id": creative_id,
                    "format": fmt,
                    "width": creative.get("width"),
                    "height": creative.get("height"),
                    "first_shown": first_shown,
                    "last_shown": last_shown,
                },
            }).execute()
            inserted += 1

        log.info("Advertiser %s: %d creatives inserted", adv_id, inserted)
        total += inserted

    # Handle error cases
    if total == 0 and not skipped:
        error_msg = "No ad creatives found for any advertiser"
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

    log.info("SerpApi Google Ads scan complete: %d discovered images", total)
    return total
