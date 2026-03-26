"""Celery task definitions wrapping async scan pipelines."""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from .celery_app import celery_app

log = logging.getLogger("dealer_intel.tasks")


def _run_async(coro):
    """Run an async coroutine in a new event loop (Celery workers are sync)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _deserialize_mapping(mapping: Dict[str, str]) -> Dict[str, UUID]:
    """Convert a {str: str} mapping back to {str: UUID} for scan functions."""
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


def dispatch_task(task: Any, args: Sequence, scan_job_id: str, source: str) -> Optional[str]:
    """Dispatch a Celery task with error handling.

    Returns the Celery task ID on success, None on failure.
    On failure the scan job is marked as 'failed' in the database so it
    doesn't permanently block the concurrent-scan slot.
    """
    try:
        result = task.delay(*args)
        log.info("Task dispatched: source=%s job=%s celery_task_id=%s", source, scan_job_id, result.id)
        return result.id
    except Exception as e:
        log.error("DISPATCH FAILED: source=%s job=%s broker=%s error=%s",
                  source, scan_job_id, celery_app.conf.broker_url, e, exc_info=True)
        _mark_job_failed(scan_job_id, f"Task dispatch failed: {e}")
        return None


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def run_website_scan_task(self, urls, scan_job_id, distributor_mapping, campaign_id=None):
    from .routers.scanning import run_website_scan
    log.info("Celery: website scan job=%s urls=%d", scan_job_id, len(urls))
    try:
        _run_async(run_website_scan(
            urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None,
        ))
    except Exception as e:
        log.error("Task run_website_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def run_google_ads_scan_task(self, advertiser_ids, scan_job_id, distributor_mapping, campaign_id=None):
    from .routers.scanning import run_google_ads_scan
    log.info("Celery: Google Ads scan job=%s advertisers=%d", scan_job_id, len(advertiser_ids))
    try:
        _run_async(run_google_ads_scan(
            advertiser_ids, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None,
        ))
    except Exception as e:
        log.error("Task run_google_ads_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def run_facebook_scan_task(self, page_urls, scan_job_id, distributor_mapping, campaign_id=None, channel="facebook"):
    from .routers.scanning import run_facebook_scan
    log.info("Celery: Facebook scan job=%s pages=%d", scan_job_id, len(page_urls))
    try:
        _run_async(run_facebook_scan(
            page_urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None, channel,
        ))
    except Exception as e:
        log.error("Task run_facebook_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def run_instagram_scan_task(self, profile_urls, scan_job_id, distributor_mapping, campaign_id=None):
    from .routers.scanning import run_instagram_scan
    log.info("Celery: Instagram scan job=%s profiles=%d", scan_job_id, len(profile_urls))
    try:
        _run_async(run_instagram_scan(
            profile_urls, UUID(scan_job_id), _deserialize_mapping(distributor_mapping),
            UUID(campaign_id) if campaign_id else None,
        ))
    except Exception as e:
        log.error("Task run_instagram_scan_task failed for %s: %s", scan_job_id, e, exc_info=True)
        _mark_job_failed(scan_job_id, str(e))


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30)
def analyze_scan_task(self, scan_job_id, campaign_id=None):
    """Run AI analysis on discovered images. Fetches data from DB internally."""
    from .routers.scanning import auto_analyze_scan, run_image_analysis
    from .database import supabase

    log.info("Celery: analyze scan job=%s campaign=%s", scan_job_id, campaign_id)

    if campaign_id:
        _run_async(auto_analyze_scan(UUID(scan_job_id), UUID(campaign_id)))
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

    _run_async(run_image_analysis(
        images.data, assets.data or [], brand_rules, org_id, scan_job_id,
    ))


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30)
def reprocess_images_task(self, campaign_id, limit=100):
    """Re-analyze unprocessed images for a campaign."""
    from .routers.scanning import run_image_analysis
    from .database import supabase

    log.info("Celery: reprocess images campaign=%s limit=%d", campaign_id, limit)

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

    _run_async(run_image_analysis(
        unprocessed.data, assets.data, brand_rules, org_id,
    ))
