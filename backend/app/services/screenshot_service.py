"""
ScreenshotOne integration service for capturing dealer websites and ad pages.

Replaces Apify with a purpose-built screenshot API that handles:
- Full-page rendering with lazy-loaded content
- Cookie banner and chat widget blocking
- Retina-quality screenshots for AI analysis
"""
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from uuid import UUID
from urllib.parse import quote, urlencode

import httpx

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.screenshot")

settings = get_settings()

SCREENSHOTONE_BASE = "https://api.screenshotone.com/take"


def _build_screenshot_params(target_url: str, **overrides) -> Dict[str, Any]:
    """Build ScreenshotOne API query parameters with sensible defaults."""
    defaults = {
        "access_key": settings.screenshotone_access_key,
        "url": target_url,
        "full_page": "true",
        "format": "png",
        "block_cookie_banners": "true",
        "block_chats": "true",
        "block_ads": "true",
        "viewport_width": 1920,
        "viewport_height": 1080,
        "device_scale_factor": 2,
        "delay": 3,
        "timeout": 60,
    }
    defaults.update(overrides)
    return defaults


async def capture_screenshot(target_url: str, **overrides) -> bytes:
    """
    Capture a screenshot of a URL via ScreenshotOne.

    Returns raw PNG image bytes.
    Raises httpx.HTTPStatusError on API failure.
    """
    params = _build_screenshot_params(target_url, **overrides)
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.get(SCREENSHOTONE_BASE, params=params)
        response.raise_for_status()
        try:
            from . import cost_tracker
            cost_tracker.record_screenshotone(renders=1, target=target_url)
        except Exception as cost_err:
            log.debug("Cost capture skipped (screenshotone): %s", cost_err)
        return response.content


async def capture_and_upload(
    target_url: str,
    scan_job_id: UUID,
    bucket: str = "scan-screenshots",
    **overrides,
) -> Optional[str]:
    """
    Capture a screenshot and upload it to Supabase Storage.

    Returns the public URL of the uploaded image, or None on failure.
    """
    try:
        image_bytes = await capture_screenshot(target_url, **overrides)

        url_hash = hashlib.md5(target_url.encode()).hexdigest()[:12]
        timestamp = int(time.time() * 1000)
        path = f"screenshots/{scan_job_id}/{url_hash}-{timestamp}.png"

        supabase.storage.from_(bucket).upload(
            path, image_bytes, {"content-type": "image/png"}
        )
        public_url = supabase.storage.from_(bucket).get_public_url(path)
        log.info("Captured & uploaded: %s -> %s", target_url[:80], public_url[:80])
        return public_url

    except httpx.HTTPStatusError as e:
        log.error("API error for %s: %d", target_url[:80], e.response.status_code)
        return None
    except Exception as e:
        log.error("Failed for %s: %s", target_url[:80], e)
        return None


async def scan_dealer_websites(
    website_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
) -> int:
    """
    Scan dealer websites by taking full-page screenshots via ScreenshotOne.

    Each URL gets one high-quality screenshot saved as a discovered image
    for downstream AI analysis (asset detection, compliance checks).

    Returns the number of discovered images saved.
    """
    log.info("Starting ScreenshotOne capture for %d URLs", len(website_urls))
    discovered_count = 0

    for url in website_urls:
        log.info("Capturing: %s", url)
        screenshot_url = await capture_and_upload(url, scan_job_id)

        if not screenshot_url:
            log.warning("Skipping %s — screenshot failed", url)
            continue

        distributor_id = _match_distributor_by_domain(url, distributor_mapping)

        supabase.table("discovered_images").insert({
            "scan_job_id": str(scan_job_id),
            "distributor_id": str(distributor_id) if distributor_id else None,
            "source_url": url,
            "image_url": screenshot_url,
            "source_type": "page_screenshot",
            "channel": "website",
            "metadata": {
                "capture_method": "screenshotone",
                "full_page": True,
                "viewport": "1920x1080",
            },
        }).execute()
        discovered_count += 1
        log.info("Saved screenshot for %s", url)

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": discovered_count,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    log.info("Captured %d/%d websites", discovered_count, len(website_urls))
    return discovered_count


async def scan_google_ads(
    advertiser_ids: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
) -> int:
    """
    Scan Google Ads by screenshotting each advertiser's Transparency Center page.

    Requires valid advertiser IDs (AR-prefixed). Names without IDs are skipped
    with a warning — users should set IDs via the distributor settings.

    Returns the number of discovered images saved.
    """
    log.info("Starting ScreenshotOne capture for %d advertisers", len(advertiser_ids))
    discovered_count = 0
    skipped = []

    for adv_id in advertiser_ids:
        if not adv_id or not adv_id.strip():
            continue

        adv_id = adv_id.strip()

        if not (adv_id.startswith("AR") and len(adv_id) > 2 and adv_id[2:].isdigit()):
            skipped.append(adv_id)
            log.warning("SKIPPED '%s' — not a valid advertiser ID", adv_id)
            continue

        transparency_url = (
            f"https://adstransparency.google.com/advertiser/{adv_id}"
            f"?region=anywhere"
        )

        log.info("Capturing transparency page: %s", adv_id)
        screenshot_url = await capture_and_upload(
            transparency_url,
            scan_job_id,
            delay=5,
        )

        if not screenshot_url:
            log.error("Screenshot failed for %s", adv_id)
            continue

        distributor_id = (
            distributor_mapping.get(adv_id.lower())
            or distributor_mapping.get(adv_id)
        )

        supabase.table("discovered_images").insert({
            "scan_job_id": str(scan_job_id),
            "distributor_id": str(distributor_id) if distributor_id else None,
            "source_url": transparency_url,
            "image_url": screenshot_url,
            "source_type": "page_screenshot",
            "channel": "google_ads",
            "metadata": {
                "advertiser_id": adv_id,
                "capture_method": "screenshotone",
            },
        }).execute()
        discovered_count += 1

    if skipped:
        log.warning(
            "%d entries skipped — need valid AR-prefixed advertiser IDs",
            len(skipped),
        )

    if discovered_count == 0 and not skipped:
        error_msg = "No distributors found to scan"
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": error_msg,
        }).eq("id", str(scan_job_id)).execute()
        raise ValueError(error_msg)

    if discovered_count == 0 and skipped:
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
        "total_items": discovered_count,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    log.info("Captured %d transparency pages", discovered_count)
    return discovered_count


async def scan_facebook_ads(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
) -> int:
    """
    Scan Facebook ads by screenshotting each page's Meta Ad Library entry.

    Converts a Facebook page URL (e.g. facebook.com/MustangCAT) into a
    Meta Ad Library search URL and captures a full-page screenshot.

    Returns the number of discovered images saved.
    """
    log.info("Starting ScreenshotOne capture for %d pages", len(page_urls))
    discovered_count = 0

    for page_url in page_urls:
        page_name = page_url.rstrip("/").split("/")[-1]
        ad_library_url = (
            f"https://www.facebook.com/ads/library/"
            f"?active_status=active&ad_type=all"
            f"&country=US&q={quote(page_name)}&media_type=all"
        )

        log.info("Capturing ad library for: %s", page_name)
        screenshot_url = await capture_and_upload(
            ad_library_url,
            scan_job_id,
            delay=5,
        )

        if not screenshot_url:
            log.error("Screenshot failed for %s", page_name)
            continue

        distributor_id = None
        for name, dist_id in distributor_mapping.items():
            if name.lower() in page_name.lower() or page_name.lower() in name.lower():
                distributor_id = dist_id
                break

        supabase.table("discovered_images").insert({
            "scan_job_id": str(scan_job_id),
            "distributor_id": str(distributor_id) if distributor_id else None,
            "source_url": ad_library_url,
            "image_url": screenshot_url,
            "source_type": "page_screenshot",
            "channel": "facebook",
            "metadata": {
                "page_name": page_name,
                "original_url": page_url,
                "capture_method": "screenshotone",
            },
        }).execute()
        discovered_count += 1

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": discovered_count,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    log.info("Captured %d/%d ad library pages", discovered_count, len(page_urls))
    return discovered_count


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
