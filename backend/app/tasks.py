"""Background task definitions for ARQ worker.

Each task is a plain async function.  The API dispatches work via
``dispatch_task()`` which enqueues jobs through redis-py / ARQ.
"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from arq.connections import ArqRedis, create_pool

log = logging.getLogger("dealer_intel.tasks")

# ---------------------------------------------------------------------------
# Redis pool for enqueuing jobs from the API process
# ---------------------------------------------------------------------------
_arq_pool: Optional[ArqRedis] = None


async def _get_pool() -> ArqRedis:
    """Lazily create (and cache) an ARQ Redis connection pool."""
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    from .worker import REDIS_SETTINGS
    _arq_pool = await create_pool(REDIS_SETTINGS)
    log.info("ARQ Redis pool created")
    return _arq_pool


# ---------------------------------------------------------------------------
# Dispatch helper — called by API routers and scheduler
# ---------------------------------------------------------------------------

async def dispatch_task(
    task_name: str,
    args: Sequence,
    scan_job_id: str,
    source: str,
) -> Optional[str]:
    """Enqueue a background job via ARQ.

    Returns the ARQ job ID on success, None on failure.
    """
    try:
        pool = await _get_pool()
        job = await pool.enqueue_job(task_name, *args)
        if job is None:
            log.error("DISPATCH FAILED (duplicate?): source=%s job=%s", source, scan_job_id)
            _mark_job_failed(scan_job_id, "Task dispatch returned None — possible duplicate")
            return None
        log.info("Task enqueued: source=%s job=%s arq_job_id=%s", source, scan_job_id, job.job_id)
        return job.job_id
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
# Task functions — these run inside the ARQ worker process
# ---------------------------------------------------------------------------

async def run_website_scan_task(ctx: dict, urls, scan_job_id, distributor_mapping, campaign_id=None):
    from .routers.scanning import run_website_scan
    log.info("Worker: website scan job=%s urls=%d", scan_job_id, len(urls))
    try:
        await run_website_scan(
            urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None,
        )
    except Exception as e:
        log.error("run_website_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def run_google_ads_scan_task(ctx: dict, advertiser_ids, scan_job_id, distributor_mapping, campaign_id=None):
    from .routers.scanning import run_google_ads_scan
    log.info("Worker: Google Ads scan job=%s advertisers=%d", scan_job_id, len(advertiser_ids))
    try:
        await run_google_ads_scan(
            advertiser_ids, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None,
        )
    except Exception as e:
        log.error("run_google_ads_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def run_facebook_scan_task(ctx: dict, page_urls, scan_job_id, distributor_mapping, campaign_id=None, channel="facebook"):
    from .routers.scanning import run_facebook_scan
    log.info("Worker: Facebook scan job=%s pages=%d", scan_job_id, len(page_urls))
    try:
        await run_facebook_scan(
            page_urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None, channel,
        )
    except Exception as e:
        log.error("run_facebook_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def run_instagram_scan_task(ctx: dict, profile_urls, scan_job_id, distributor_mapping, campaign_id=None):
    from .routers.scanning import run_instagram_scan
    log.info("Worker: Instagram scan job=%s profiles=%d", scan_job_id, len(profile_urls))
    try:
        await run_instagram_scan(
            profile_urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None,
        )
    except Exception as e:
        log.error("run_instagram_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


async def run_analyze_scan_task(ctx: dict, scan_job_id, campaign_id=None):
    """Run AI analysis on discovered images."""
    from .routers.scanning import auto_analyze_scan, run_image_analysis
    from .database import supabase

    log.info("Worker: analyze scan job=%s campaign=%s", scan_job_id, campaign_id)

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


async def run_reprocess_images_task(ctx: dict, campaign_id, limit=100):
    """Re-analyze unprocessed images for a campaign."""
    from .routers.scanning import run_image_analysis
    from .database import supabase

    log.info("Worker: reprocess images campaign=%s limit=%d", campaign_id, limit)

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


# ---------------------------------------------------------------------------
# Cron: auto-fail scans stuck in pending for > 5 min
# ---------------------------------------------------------------------------

async def cleanup_stale_scans(ctx: dict):
    """Auto-fail scans stuck in 'pending' for more than 5 minutes."""
    try:
        from .database import supabase
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        stale = supabase.table("scan_jobs") \
            .select("id") \
            .eq("status", "pending") \
            .lt("created_at", cutoff) \
            .execute()

        for job in (stale.data or []):
            supabase.table("scan_jobs").update({
                "status": "failed",
                "error_message": "Scan timed out in pending state — task was not picked up by worker",
            }).eq("id", job["id"]).execute()
            log.warning("Auto-failed stale pending scan: %s", job["id"])

        if stale.data:
            log.info("Cleaned up %d stale pending scan(s)", len(stale.data))
    except Exception:
        log.exception("Error cleaning up stale scans")
