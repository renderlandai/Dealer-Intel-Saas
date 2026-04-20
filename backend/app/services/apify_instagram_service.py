"""
Apify Instagram organic post scraper integration.

Uses the official apify/instagram-scraper actor (via a pre-configured Apify task)
to pull recent organic posts from dealer Instagram profiles.  Each post image is
inserted as a discovered_image so the existing matching pipeline
(hash -> CLIP -> Haiku -> Opus) processes it like any other discovered image.
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

log = logging.getLogger("dealer_intel.apify_instagram")

settings = get_settings()

APIFY_BASE = "https://api.apify.com/v2"
TASK_ID = "diamanted~instagram-scraper-task"

_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
_POLL_INTERVAL_SEC = 5
_MAX_POLL_TIME_SEC = 300


def _extract_username(url: str) -> Optional[str]:
    """Extract the Instagram username from a profile URL."""
    if not url:
        return None
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.netloc and "instagram" in parsed.netloc:
        parts = parsed.path.strip("/").split("/")
        return parts[0] if parts and parts[0] else None
    if not parsed.scheme and not parsed.netloc:
        return url.lstrip("@")
    return None


def _normalize_profile_url(url: str) -> str:
    """Ensure an Instagram URL is well-formed for the scraper."""
    username = _extract_username(url)
    if username:
        return f"https://www.instagram.com/{username}/"
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://www.instagram.com/{url}/"
    return url


async def _start_task_run(
    profile_urls: List[str],
    *,
    results_limit: int = 50,
    newer_than: str = "90 days",
) -> dict:
    """Start an Apify task run with profile-specific overrides."""
    task_input = {
        "directUrls": profile_urls,
        "resultsType": "posts",
        "resultsLimit": results_limit,
        "onlyPostsNewerThan": newer_than,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{APIFY_BASE}/actor-tasks/{TASK_ID}/runs",
            params={"token": settings.apify_api_key},
            json=task_input,
        )
        resp.raise_for_status()
        return resp.json()["data"]


async def _poll_run(run_id: str) -> dict:
    """Poll until the run reaches a terminal status."""
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


def _resolve_distributor(
    post: Dict[str, Any],
    distributor_mapping: Dict[str, UUID],
) -> Optional[UUID]:
    """Try to resolve which distributor this post belongs to."""
    owner = (post.get("ownerUsername") or "").lower()

    if owner in distributor_mapping:
        return distributor_mapping[owner]

    for key, dist_id in distributor_mapping.items():
        if key in owner or owner in key:
            return dist_id

    return None


async def scan_instagram_organic(
    profile_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    *,
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
    results_limit: int = 50,
) -> int:
    """
    Scan dealer Instagram profiles for organic posts.

    1. Starts the Apify task with supplied Instagram profile URLs
    2. Polls until the run completes
    3. Inserts each post image as a discovered_image for the matching pipeline

    Returns total number of discovered images inserted.
    """
    if not settings.apify_api_key:
        raise ValueError(
            "APIFY_API_KEY is not configured. "
            "Set it in your .env file to enable Instagram scanning."
        )

    if not profile_urls:
        raise ValueError("No Instagram profile URLs provided.")

    normalized = [_normalize_profile_url(u) for u in profile_urls]
    log.info(
        "Starting Instagram organic scan for %d profile(s): %s",
        len(normalized), normalized,
    )

    run_info = await _start_task_run(normalized, results_limit=results_limit)
    run_id = run_info["id"]
    log.info("Apify Instagram task run started: %s", run_id)

    supabase.table("scan_jobs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

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

    dataset_id = completed_run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError("Apify run succeeded but no dataset ID returned")

    posts = await _fetch_dataset_items(dataset_id)
    log.info("Apify returned %d post(s)", len(posts))

    try:
        from . import cost_tracker
        cost_tracker.record_apify_run(
            actor_or_task=TASK_ID,
            run_id=run_id,
            usage_total_usd=completed_run.get("usageTotalUsd"),
            items_returned=len(posts),
        )
    except Exception as cost_err:
        log.debug("Cost capture skipped (apify instagram): %s", cost_err)

    if not posts:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        log.warning("No posts found for the provided profiles")
        return 0

    total_inserted = 0
    skipped_no_image = 0
    skipped_video = 0
    for post in posts:
        post_type = (post.get("type") or "").lower()

        if post_type == "video":
            skipped_video += 1
            log.debug("Skipping video post %s", post.get("shortCode"))
            continue

        display_url = post.get("displayUrl") or ""
        image_urls = [display_url] if display_url else []

        for child_url in (post.get("displayResourceUrls") or []):
            if child_url and child_url not in image_urls:
                image_urls.append(child_url)

        if not image_urls:
            skipped_no_image += 1
            log.debug("Skipping post %s (type=%s) — no image URLs", post.get("shortCode"), post_type)
            continue

        log.debug("Post %s (type=%s) — %d image(s)", post.get("shortCode"), post_type, len(image_urls))

        short_code = post.get("shortCode", "")
        post_url = post.get("url") or f"https://www.instagram.com/p/{short_code}/"
        owner_username = post.get("ownerUsername", "")
        caption = (post.get("caption") or "")[:500]
        timestamp = post.get("timestamp")

        distributor_id = _resolve_distributor(post, distributor_mapping)

        for img_url in image_urls:
            if not img_url or not img_url.startswith("http"):
                continue

            supabase.table("discovered_images").insert({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": post_url,
                "image_url": img_url,
                "source_type": "extracted_image",
                "channel": "instagram",
                "metadata": {
                    "extraction_method": "apify_instagram",
                    "apify_task": TASK_ID,
                    "post_type": post_type,
                    "short_code": short_code,
                    "owner_username": owner_username,
                    "caption": caption,
                    "likes": post.get("likesCount"),
                    "comments": post.get("commentsCount"),
                    "timestamp": timestamp,
                    "hashtags": post.get("hashtags", []),
                    "mentions": post.get("mentions", []),
                },
            }).execute()
            total_inserted += 1

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": total_inserted,
    }).eq("id", str(scan_job_id)).execute()

    log.info(
        "Instagram organic scan complete: %d images from %d posts inserted (%d videos skipped, %d had no images)",
        total_inserted, len(posts), skipped_video, skipped_no_image,
    )
    return total_inserted
