"""Background task dispatch — runs scans in-process via asyncio.

No external worker, no Redis queue, no serialization.  The API process
runs scan coroutines directly in its own event loop using
``asyncio.create_task()``.  This is simpler, more reliable, and
eliminates the entire class of message-broker bugs.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

SCAN_TIMEOUT_SECONDS = 7200

log = logging.getLogger("dealer_intel.tasks")

# Keep a reference to running tasks so they aren't garbage-collected
_running_tasks: set[asyncio.Task] = set()


def _task_done(task: asyncio.Task) -> None:
    """Callback: remove finished task from the tracking set and log failures."""
    _running_tasks.discard(task)
    if task.cancelled():
        log.warning("Background task cancelled: %s", task.get_name())
    elif exc := task.exception():
        log.error("Background task %s failed: %s", task.get_name(), exc, exc_info=exc)


# ---------------------------------------------------------------------------
# Dispatch helper — called by API routers and scheduler
# ---------------------------------------------------------------------------

async def dispatch_task(
    task_name: str,
    args: Sequence,
    scan_job_id: str,
    source: str,
) -> Optional[str]:
    """Launch a background scan coroutine in the current event loop.

    Returns the scan_job_id on success (for API compatibility), None on failure.
    """
    task_map = {
        "run_website_scan_task": _run_website_scan,
        "run_google_ads_scan_task": _run_google_ads_scan,
        "run_facebook_scan_task": _run_facebook_scan,
        "run_instagram_scan_task": _run_instagram_scan,
        "run_analyze_scan_task": _run_analyze_scan,
        "run_reprocess_images_task": _run_reprocess_images,
    }

    coro_fn = task_map.get(task_name)
    if coro_fn is None:
        log.error("Unknown task %s for job %s", task_name, scan_job_id)
        _mark_job_failed(scan_job_id, f"Unknown task: {task_name}")
        return None

    try:
        task = asyncio.create_task(
            coro_fn(*args),
            name=f"{task_name}:{scan_job_id}",
        )
        _running_tasks.add(task)
        task.add_done_callback(_task_done)
        log.info(
            "Task started in-process: source=%s job=%s task=%s (active=%d)",
            source, scan_job_id, task_name, len(_running_tasks),
        )
        return scan_job_id
    except Exception as e:
        log.error("DISPATCH FAILED: source=%s job=%s error=%s", source, scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, f"Task dispatch failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deserialize_mapping(mapping: Dict[str, str]) -> Dict[str, UUID]:
    return {k: UUID(v) for k, v in mapping.items()}


def _mark_job_failed(scan_job_id: str, error: str) -> None:
    """Best-effort update of scan job status to failed."""
    try:
        from .database import supabase
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": error[:500],
        }).eq("id", scan_job_id).execute()
    except Exception as db_err:
        log.error("Could not mark scan job %s as failed: %s", scan_job_id, db_err)


# ---------------------------------------------------------------------------
# Thin wrappers — translate (string args) → actual scan functions
# ---------------------------------------------------------------------------

async def _run_website_scan(urls, scan_job_id, distributor_mapping, campaign_id=None):
    from .services.scan_runners import run_website_scan
    log.info("RUNNING website scan job=%s urls=%d", scan_job_id, len(urls))
    try:
        await asyncio.wait_for(
            run_website_scan(
                urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
                UUID(campaign_id) if campaign_id else None,
            ),
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.error("Website scan timed out after %ds: %s", SCAN_TIMEOUT_SECONDS, scan_job_id)
        _mark_job_failed(scan_job_id, f"Scan timed out after {SCAN_TIMEOUT_SECONDS}s")
    except Exception as e:
        log.error("Website scan failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def _run_google_ads_scan(advertiser_ids, scan_job_id, distributor_mapping, campaign_id=None):
    from .services.scan_runners import run_google_ads_scan
    log.info("RUNNING Google Ads scan job=%s advertisers=%d", scan_job_id, len(advertiser_ids))
    try:
        await asyncio.wait_for(
            run_google_ads_scan(
                advertiser_ids, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
                UUID(campaign_id) if campaign_id else None,
            ),
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.error("Google Ads scan timed out after %ds: %s", SCAN_TIMEOUT_SECONDS, scan_job_id)
        _mark_job_failed(scan_job_id, f"Scan timed out after {SCAN_TIMEOUT_SECONDS}s")
    except Exception as e:
        log.error("Google Ads scan failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def _run_facebook_scan(page_urls, scan_job_id, distributor_mapping, campaign_id=None, channel="facebook"):
    from .services.scan_runners import run_facebook_scan
    log.info("RUNNING Facebook scan job=%s pages=%d", scan_job_id, len(page_urls))
    try:
        await asyncio.wait_for(
            run_facebook_scan(
                page_urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
                UUID(campaign_id) if campaign_id else None, channel,
            ),
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.error("Facebook scan timed out after %ds: %s", SCAN_TIMEOUT_SECONDS, scan_job_id)
        _mark_job_failed(scan_job_id, f"Scan timed out after {SCAN_TIMEOUT_SECONDS}s")
    except Exception as e:
        log.error("Facebook scan failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def _run_instagram_scan(profile_urls, scan_job_id, distributor_mapping, campaign_id=None):
    from .services.scan_runners import run_instagram_scan
    log.info("RUNNING Instagram scan job=%s profiles=%d", scan_job_id, len(profile_urls))
    try:
        await asyncio.wait_for(
            run_instagram_scan(
                profile_urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
                UUID(campaign_id) if campaign_id else None,
            ),
            timeout=SCAN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.error("Instagram scan timed out after %ds: %s", SCAN_TIMEOUT_SECONDS, scan_job_id)
        _mark_job_failed(scan_job_id, f"Scan timed out after {SCAN_TIMEOUT_SECONDS}s")
    except Exception as e:
        log.error("Instagram scan failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def _run_analyze_scan(scan_job_id, campaign_id=None):
    """Run AI analysis on discovered images."""
    from .services.scan_runners import auto_analyze_scan, run_image_analysis
    from .database import supabase

    log.info("RUNNING analyze scan job=%s campaign=%s", scan_job_id, campaign_id)

    if campaign_id:
        await auto_analyze_scan(UUID(scan_job_id), UUID(campaign_id))
        return

    job = supabase.table("scan_jobs").select("*").eq("id", scan_job_id).single().execute()
    if not job.data:
        log.error("Scan job %s not found", scan_job_id)
        return

    org_id = job.data["organization_id"]
    images = (
        supabase.table("discovered_images")
        .select("*")
        .eq("scan_job_id", scan_job_id)
        .eq("is_processed", False)
        .execute()
    )
    if not images.data:
        return

    assets = (
        supabase.table("assets")
        .select("*, campaigns!inner(organization_id)")
        .eq("campaigns.organization_id", org_id)
        .execute()
    )

    rules = (
        supabase.table("compliance_rules")
        .select("*")
        .eq("organization_id", org_id)
        .eq("is_active", True)
        .execute()
    )
    brand_rules: Dict = {}
    for rule in (rules.data or []):
        if rule["rule_type"] == "required_element":
            brand_rules.setdefault("required_elements", []).append(
                rule["rule_config"].get("element"))
        elif rule["rule_type"] == "forbidden_element":
            brand_rules.setdefault("forbidden_elements", []).append(
                rule["rule_config"].get("element"))

    await run_image_analysis(
        images.data, assets.data or [], brand_rules, org_id, scan_job_id,
    )


async def _run_reprocess_images(campaign_id, limit=100):
    """Re-analyze unprocessed images for a campaign."""
    from .services.scan_runners import run_image_analysis
    from .database import supabase

    log.info("RUNNING reprocess images campaign=%s limit=%d", campaign_id, limit)

    campaign = (
        supabase.table("campaigns")
        .select("organization_id")
        .eq("id", campaign_id)
        .single()
        .execute()
    )
    if not campaign.data:
        log.error("Campaign %s not found", campaign_id)
        return

    org_id = campaign.data["organization_id"]

    org_jobs = supabase.table("scan_jobs")\
        .select("id")\
        .eq("organization_id", org_id)\
        .execute()
    org_job_ids = [j["id"] for j in (org_jobs.data or [])]
    if not org_job_ids:
        log.info("No scan jobs found for org %s — nothing to reprocess", org_id)
        return

    unprocessed = (
        supabase.table("discovered_images")
        .select("*")
        .in_("scan_job_id", org_job_ids)
        .eq("is_processed", False)
        .limit(limit)
        .execute()
    )
    if not unprocessed.data:
        return

    assets = (
        supabase.table("assets")
        .select("*")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    if not assets.data:
        return

    rules = (
        supabase.table("compliance_rules")
        .select("*")
        .eq("organization_id", org_id)
        .eq("is_active", True)
        .execute()
    )
    brand_rules: Dict = {}
    for rule in (rules.data or []):
        if rule["rule_type"] == "required_element":
            brand_rules.setdefault("required_elements", []).append(
                rule["rule_config"].get("element"))
        elif rule["rule_type"] == "forbidden_element":
            brand_rules.setdefault("forbidden_elements", []).append(
                rule["rule_config"].get("element"))

    await run_image_analysis(
        unprocessed.data, assets.data, brand_rules, org_id,
    )
