"""Data retention enforcement — purges expired data based on each org's plan."""
import logging
from datetime import datetime, timedelta, timezone

from ..config import get_plan_limits
from ..database import supabase

log = logging.getLogger("dealer_intel.retention")


async def run_retention_sweep() -> None:
    """Iterate all organizations and delete data older than their plan allows."""
    try:
        orgs = supabase.table("organizations") \
            .select("id, plan") \
            .execute()

        if not orgs.data:
            return

        now = datetime.now(timezone.utc)
        total_deleted = 0

        for org in orgs.data:
            org_id = org["id"]
            plan = org.get("plan", "free")
            limits = get_plan_limits(plan)
            retention_days = limits.get("data_retention_days")

            if retention_days is None:
                continue

            cutoff = (now - timedelta(days=retention_days)).isoformat()
            deleted = _purge_org_data(org_id, cutoff)
            total_deleted += deleted

        if total_deleted > 0:
            log.info("Retention sweep complete — purged %d expired scan jobs", total_deleted)
        else:
            log.debug("Retention sweep complete — nothing to purge")

    except Exception:
        log.exception("Data retention sweep failed")


def _purge_org_data(org_id: str, cutoff_iso: str) -> int:
    """Delete scan jobs (and cascading discovered_images) older than cutoff."""
    expired_jobs = supabase.table("scan_jobs") \
        .select("id") \
        .eq("organization_id", org_id) \
        .lt("created_at", cutoff_iso) \
        .in_("status", ["completed", "failed"]) \
        .execute()

    job_ids = [j["id"] for j in (expired_jobs.data or [])]
    if not job_ids:
        return 0

    # Delete matches linked to discovered_images from these scan jobs
    for job_id in job_ids:
        discovered = supabase.table("discovered_images") \
            .select("id") \
            .eq("scan_job_id", job_id) \
            .execute()

        if discovered.data:
            di_ids = [d["id"] for d in discovered.data]
            supabase.table("matches") \
                .delete() \
                .in_("discovered_image_id", di_ids) \
                .execute()

    # Delete the scan jobs (discovered_images cascade automatically)
    supabase.table("scan_jobs") \
        .delete() \
        .in_("id", job_ids) \
        .execute()

    # Purge old alerts
    supabase.table("alerts") \
        .delete() \
        .eq("organization_id", org_id) \
        .lt("created_at", cutoff_iso) \
        .execute()

    # Purge stale page hit cache entries
    supabase.table("page_hit_cache") \
        .delete() \
        .eq("organization_id", org_id) \
        .lt("last_hit_at", cutoff_iso) \
        .execute()

    log.info("Org %s: purged %d scan jobs older than %s", org_id, len(job_ids), cutoff_iso[:10])
    return len(job_ids)
