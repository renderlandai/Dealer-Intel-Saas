"""Scanning and analysis routes.

HTTP layer only. The scan runner coroutines (`run_website_scan`,
`run_google_ads_scan`, etc.) live in `app.services.scan_runners` and
are dispatched via `app.tasks.dispatch_task`. Keeping the HTTP layer
in this file means it can stay coupled to FastAPI / auth / slowapi /
plan_enforcement without contaminating the worker import path —
see Phase 4.5 in `log.md` and `backend/docs/scan_dispatch_flow.md`.
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import ScanJobCreate, ScanJob, ScanSource
from ..services import apify_instagram_service
from ..plan_enforcement import (
    OrgPlan, get_org_plan,
    check_scan_quota, check_concurrent_scans, check_channel_allowed,
)
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

log = logging.getLogger("dealer_intel.scanning")

router = APIRouter(prefix="/scans", tags=["scanning"])


@router.post("/start", response_model=ScanJob, summary="Start scan job")
@limiter.limit("10/minute")
async def start_scan(
    request: Request,
    scan_request: ScanJobCreate,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """
    Start a new scan job.
    
    Dispatches the scan as a background task.
    """
    check_channel_allowed(op, scan_request.source.value)
    check_scan_quota(op)
    check_concurrent_scans(op)
    from ..tasks import dispatch_task

    if scan_request.campaign_id:
        campaign_check = supabase.table("campaigns")\
            .select("id")\
            .eq("id", str(scan_request.campaign_id))\
            .eq("organization_id", str(user.org_id))\
            .maybe_single()\
            .execute()
        if not campaign_check.data:
            raise HTTPException(status_code=404, detail="Campaign not found")

    job_data = {
        "organization_id": str(user.org_id),
        "campaign_id": str(scan_request.campaign_id) if scan_request.campaign_id else None,
        "source": scan_request.source.value,
        "status": "pending"
    }
    
    result = supabase.table("scan_jobs").insert(job_data).execute()
    scan_job = result.data[0]
    scan_job_id = scan_job["id"]

    if scan_request.distributor_ids:
        distributors = supabase.table("distributors")\
            .select("*")\
            .in_("id", [str(d) for d in scan_request.distributor_ids])\
            .eq("organization_id", str(user.org_id))\
            .execute()
    else:
        distributors = supabase.table("distributors")\
            .select("*")\
            .eq("organization_id", str(user.org_id))\
            .eq("status", "active")\
            .execute()
    
    distributor_list = distributors.data
    campaign_id_str = str(scan_request.campaign_id) if scan_request.campaign_id else None
    dispatched = False
    
    if scan_request.source == ScanSource.GOOGLE_ADS:
        names = [d.get("google_ads_advertiser_id") or d["name"] for d in distributor_list]
        mapping = {
            (d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"]
            for d in distributor_list
        }
        log.info("Starting Google Ads scan for %d advertisers, job=%s", len(names), scan_job_id)
        dispatched = await dispatch_task("run_google_ads_scan_task", [names, scan_job_id, mapping, campaign_id_str], scan_job_id, "google_ads")
        
    elif scan_request.source == ScanSource.INSTAGRAM:
        urls = [d["instagram_url"] for d in distributor_list if d.get("instagram_url")]
        mapping = {}
        for d in distributor_list:
            ig_url = d.get("instagram_url")
            if ig_url:
                username = apify_instagram_service._extract_username(ig_url)
                if username:
                    mapping[username.lower()] = d["id"]
                mapping[d["name"].lower()] = d["id"]
        log.info("Starting Instagram organic scan for %d profiles, job=%s", len(urls), scan_job_id)
        dispatched = await dispatch_task("run_instagram_scan_task", [urls, scan_job_id, mapping, campaign_id_str], scan_job_id, "instagram")

    elif scan_request.source == ScanSource.FACEBOOK:
        urls = [d["facebook_url"] for d in distributor_list if d.get("facebook_url")]
        mapping = {d["name"].lower(): d["id"] for d in distributor_list}
        log.info("Starting Facebook scan for %d pages, job=%s", len(urls), scan_job_id)
        dispatched = await dispatch_task("run_facebook_scan_task", [urls, scan_job_id, mapping, campaign_id_str, "facebook"], scan_job_id, "facebook")
        
    elif scan_request.source == ScanSource.WEBSITE:
        urls = [d["website_url"] for d in distributor_list if d.get("website_url")]
        mapping = {
            d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
            for d in distributor_list if d.get("website_url")
        }
        log.info("Starting website scan for %d URLs, job=%s: %s", len(urls), scan_job_id, urls)
        dispatched = await dispatch_task("run_website_scan_task", [urls, scan_job_id, mapping, campaign_id_str], scan_job_id, "website")

    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to start scan task. Please try again.")
    
    return scan_job


@router.get("", response_model=List[ScanJob], summary="List scan jobs")
async def list_scan_jobs(
    status: Optional[str] = None,
    limit: int = 20,
    user: AuthUser = Depends(get_current_user),
):
    """List scan jobs."""
    query = supabase.table("scan_jobs").select("*")
    query = query.eq("organization_id", str(user.org_id))
    if status:
        query = query.eq("status", status)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/{job_id}", response_model=ScanJob, summary="Get scan job")
async def get_scan_job(job_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get scan job details."""
    result = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(job_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    return result.data


@router.post("/{job_id}/retry", response_model=ScanJob, summary="Retry failed scan")
async def retry_scan_job(
    job_id: UUID,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Retry a failed scan by creating a new scan job with the same parameters."""
    old_job = supabase.table("scan_jobs") \
        .select("*") \
        .eq("id", str(job_id)) \
        .single().execute()
    if not old_job.data:
        raise HTTPException(404, "Scan job not found")
    if old_job.data.get("organization_id") != str(user.org_id):
        raise HTTPException(403, "Not your scan")
    if old_job.data["status"] != "failed":
        raise HTTPException(400, "Only failed scans can be retried")

    source = old_job.data["source"]
    campaign_id = old_job.data.get("campaign_id")

    check_channel_allowed(op, source)
    check_scan_quota(op)
    check_concurrent_scans(op)

    from ..tasks import dispatch_task

    new_job = supabase.table("scan_jobs").insert({
        "organization_id": str(user.org_id),
        "campaign_id": campaign_id,
        "source": source,
        "status": "pending",
    }).execute()
    new_id = new_job.data[0]["id"]

    distributors = supabase.table("distributors") \
        .select("*") \
        .eq("organization_id", str(user.org_id)) \
        .eq("status", "active").execute()
    dist_list = distributors.data

    campaign_id_str = campaign_id if campaign_id else None
    dispatched = False

    if source == "google_ads":
        names = [d.get("google_ads_advertiser_id") or d["name"] for d in dist_list]
        mapping = {(d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"] for d in dist_list}
        dispatched = await dispatch_task("run_google_ads_scan_task", [names, new_id, mapping, campaign_id_str], new_id, "google_ads")
    elif source == "instagram":
        urls = [d["instagram_url"] for d in dist_list if d.get("instagram_url")]
        mapping = {}
        for d in dist_list:
            ig_url = d.get("instagram_url")
            if ig_url:
                username = apify_instagram_service._extract_username(ig_url)
                if username:
                    mapping[username.lower()] = d["id"]
                mapping[d["name"].lower()] = d["id"]
        dispatched = await dispatch_task("run_instagram_scan_task", [urls, new_id, mapping, campaign_id_str], new_id, "instagram")
    elif source == "facebook":
        urls = [d["facebook_url"] for d in dist_list if d.get("facebook_url")]
        mapping = {d["name"].lower(): d["id"] for d in dist_list}
        dispatched = await dispatch_task("run_facebook_scan_task", [urls, new_id, mapping, campaign_id_str, "facebook"], new_id, "facebook")
    elif source == "website":
        urls = [d["website_url"] for d in dist_list if d.get("website_url")]
        mapping = {
            d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
            for d in dist_list if d.get("website_url")
        }
        dispatched = await dispatch_task("run_website_scan_task", [urls, new_id, mapping, campaign_id_str], new_id, "website")

    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to start scan task. Please try again.")

    log.info("Retried scan %s → new scan %s (source=%s)", job_id, new_id, source)
    return new_job.data[0]


@router.delete("/{job_id}", summary="Delete scan job")
async def delete_scan_job(job_id: UUID, user: AuthUser = Depends(get_current_user)):
    """
    Delete a scan job and all its associated data.
    
    This will cascade delete:
    - discovered_images (via ON DELETE CASCADE)
    - matches linked to those discovered images (via ON DELETE CASCADE)
    """
    job = supabase.table("scan_jobs")\
        .select("id")\
        .eq("id", str(job_id))\
        .eq("organization_id", str(user.org_id))\
        .maybe_single()\
        .execute()
    if not job.data:
        raise HTTPException(status_code=404, detail="Scan job not found")

    discovered = supabase.table("discovered_images")\
        .select("id")\
        .eq("scan_job_id", str(job_id))\
        .execute()
    
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        supabase.table("matches")\
            .delete()\
            .in_("discovered_image_id", discovered_ids)\
            .execute()
    
    supabase.table("scan_jobs")\
        .delete()\
        .eq("id", str(job_id))\
        .execute()
    
    return {"status": "deleted", "job_id": str(job_id)}


@router.delete("", summary="Delete all scans")
async def delete_all_scans(user: AuthUser = Depends(get_current_user)):
    """
    Delete all scan jobs and associated data for the current org.
    Only available when ENABLE_DANGEROUS_ENDPOINTS=true.
    """
    from ..config import get_settings
    if not get_settings().enable_dangerous_endpoints:
        raise HTTPException(status_code=403, detail="Bulk delete is disabled in this environment")

    org_jobs = supabase.table("scan_jobs")\
        .select("id")\
        .eq("organization_id", str(user.org_id))\
        .execute()
    job_ids = [j["id"] for j in (org_jobs.data or [])]
    if not job_ids:
        return {"status": "deleted", "count": 0}

    discovered = supabase.table("discovered_images")\
        .select("id")\
        .in_("scan_job_id", job_ids)\
        .execute()
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        supabase.table("matches")\
            .delete()\
            .in_("discovered_image_id", discovered_ids)\
            .execute()

    supabase.table("scan_jobs")\
        .delete()\
        .eq("organization_id", str(user.org_id))\
        .execute()

    return {"status": "deleted", "count": len(job_ids)}


@router.post("/{job_id}/analyze", summary="Analyze discovered images")
async def analyze_discovered_images(
    job_id: UUID,
    campaign_id: Optional[UUID] = None,
    user: AuthUser = Depends(get_current_user),
):
    """
    Analyze discovered images from a completed scan.
    Runs as a background task.
    """
    from ..tasks import dispatch_task

    job = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(job_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not job.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    if job.data["status"] != "completed":
        raise HTTPException(status_code=400, detail="Scan job not completed yet")
    
    images = supabase.table("discovered_images")\
        .select("id", count="exact")\
        .eq("scan_job_id", str(job_id))\
        .eq("is_processed", False)\
        .execute()
    
    image_count = images.count or 0
    if image_count == 0:
        return {"message": "No unprocessed images found", "count": 0}
    
    dispatched = await dispatch_task(
        "run_analyze_scan_task",
        [str(job_id), str(campaign_id) if campaign_id else None],
        str(job_id),
        "analyze_scan",
    )
    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to queue analysis task")

    return {
        "message": "Analysis queued",
        "image_count": image_count,
    }


@router.post("/batch", summary="Batch scan all channels")
@limiter.limit("2/minute")
async def batch_scan(
    request: Request,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Scan all dealers across all allowed channels. Pro and Business plans only."""
    if op.plan not in ("professional", "business", "enterprise"):
        raise HTTPException(
            403,
            "Batch scanning is available on Pro and Business plans. "
            "Upgrade to unlock this feature.",
        )

    check_scan_quota(op)

    from ..tasks import dispatch_task

    distributors = supabase.table("distributors") \
        .select("*") \
        .eq("organization_id", str(user.org_id)) \
        .eq("status", "active").execute()
    dist_list = distributors.data or []
    if not dist_list:
        raise HTTPException(400, "No active dealers found. Add dealers first.")

    campaigns_resp = supabase.table("campaigns") \
        .select("id") \
        .eq("organization_id", str(user.org_id)) \
        .eq("status", "active") \
        .limit(1).execute()
    campaign_id_str = campaigns_resp.data[0]["id"] if campaigns_resp.data else None

    allowed_channels = op.limits.get("allowed_channels", [])
    created_jobs = []

    for channel in allowed_channels:
        active = supabase.table("scan_jobs") \
            .select("id", count="exact") \
            .eq("organization_id", str(user.org_id)) \
            .in_("status", ["pending", "running", "analyzing"]).execute()
        max_concurrent = op.limits.get("max_concurrent_scans", 1)
        if (active.count or 0) >= max_concurrent:
            break

        job = supabase.table("scan_jobs").insert({
            "organization_id": str(user.org_id),
            "campaign_id": campaign_id_str,
            "source": channel,
            "status": "pending",
        }).execute()
        job_id = job.data[0]["id"]

        if channel == "google_ads":
            names = [d.get("google_ads_advertiser_id") or d["name"] for d in dist_list]
            mapping = {(d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"] for d in dist_list}
            await dispatch_task("run_google_ads_scan_task", [names, job_id, mapping, campaign_id_str], job_id, "google_ads")
        elif channel == "instagram":
            urls = [d["instagram_url"] for d in dist_list if d.get("instagram_url")]
            mapping = {}
            for d in dist_list:
                ig_url = d.get("instagram_url")
                if ig_url:
                    username = apify_instagram_service._extract_username(ig_url)
                    if username:
                        mapping[username.lower()] = d["id"]
                    mapping[d["name"].lower()] = d["id"]
            if urls:
                await dispatch_task("run_instagram_scan_task", [urls, job_id, mapping, campaign_id_str], job_id, "instagram")
        elif channel == "facebook":
            urls = [d["facebook_url"] for d in dist_list if d.get("facebook_url")]
            mapping = {}
            for d in dist_list:
                mapping[d["name"].lower()] = d["id"]
                fb_url = d.get("facebook_url")
                if fb_url:
                    from urllib.parse import urlparse
                    slug = urlparse(fb_url).path.strip("/").split("/")[0].lower()
                    if slug:
                        mapping[slug] = d["id"]
            if urls:
                await dispatch_task("run_facebook_scan_task", [urls, job_id, mapping, campaign_id_str, "facebook"], job_id, "facebook")
        elif channel == "website":
            urls = [d["website_url"] for d in dist_list if d.get("website_url")]
            mapping = {
                d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
                for d in dist_list if d.get("website_url")
            }
            if urls:
                await dispatch_task("run_website_scan_task", [urls, job_id, mapping, campaign_id_str], job_id, "website")

        created_jobs.append({"id": job_id, "source": channel})

    log.info("Batch scan started for org %s: %d jobs across %s",
             user.org_id, len(created_jobs), [j["source"] for j in created_jobs])

    return {
        "message": f"Batch scan started — {len(created_jobs)} scan(s) queued",
        "jobs": created_jobs,
    }


@router.post("/quick-scan", summary="Quick scan")
async def quick_scan(
    request: Request,
    source: ScanSource,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """
    Quick scan - starts a scan and immediately begins analysis.
    """
    job = await start_scan(
        request,
        ScanJobCreate(source=source),
        user,
        op,
    )

    return {
        "message": "Quick scan started",
        "job_id": job["id"],
        "source": source.value
    }


@router.post("/reprocess-unprocessed", summary="Reprocess unprocessed images")
async def reprocess_unprocessed_images(
    campaign_id: UUID,
    limit: int = 100,
    user: AuthUser = Depends(get_current_user),
):
    """
    Reprocess images that were never analyzed.
    Runs as a background task.
    """
    from ..tasks import dispatch_task

    campaign = supabase.table("campaigns")\
        .select("organization_id")\
        .eq("id", str(campaign_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    org_scan_jobs = supabase.table("scan_jobs")\
        .select("id")\
        .eq("organization_id", str(user.org_id))\
        .execute()
    org_job_ids = [j["id"] for j in (org_scan_jobs.data or [])]

    if not org_job_ids:
        return {"message": "No scan jobs found for your organization", "count": 0}

    unprocessed = supabase.table("discovered_images")\
        .select("id", count="exact")\
        .in_("scan_job_id", org_job_ids)\
        .eq("is_processed", False)\
        .limit(limit)\
        .execute()
    
    if not (unprocessed.count or 0):
        return {"message": "No unprocessed images found", "count": 0}
    
    assets = supabase.table("assets")\
        .select("id", count="exact")\
        .eq("campaign_id", str(campaign_id))\
        .execute()
    
    if not (assets.count or 0):
        return {"message": "No campaign assets to match against", "count": 0}
    
    dispatched = await dispatch_task(
        "run_reprocess_images_task",
        [str(campaign_id), limit],
        str(campaign_id),
        "reprocess_images",
    )
    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to queue reprocessing task")

    return {
        "message": "Reprocessing queued",
        "image_count": unprocessed.count,
        "asset_count": assets.count,
    }


@router.get("/debug/{scan_id}", summary="Debug scan details")
async def debug_scan(scan_id: UUID, user: AuthUser = Depends(get_current_user)):
    """
    Debug endpoint to inspect scan details and identify issues.
    Only available when ENABLE_DANGEROUS_ENDPOINTS=true.
    """
    from ..config import get_settings
    if not get_settings().enable_dangerous_endpoints:
        raise HTTPException(status_code=403, detail="Debug endpoint is disabled in this environment")

    job = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(scan_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not job.data:
        return {"error": "Scan job not found"}
    
    # Get discovered images
    discovered = supabase.table("discovered_images")\
        .select("*")\
        .eq("scan_job_id", str(scan_id))\
        .execute()
    
    # Get campaign assets if campaign_id exists
    assets = []
    if job.data.get("campaign_id"):
        assets_result = supabase.table("assets")\
            .select("*")\
            .eq("campaign_id", job.data["campaign_id"])\
            .execute()
        assets = assets_result.data
    
    # Get matches for this scan's discovered images
    matches = []
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        matches_result = supabase.table("matches")\
            .select("*")\
            .in_("discovered_image_id", discovered_ids)\
            .execute()
        matches = matches_result.data
    
    # Build debug report
    return {
        "scan_job": {
            "id": job.data["id"],
            "status": job.data["status"],
            "source": job.data["source"],
            "campaign_id": job.data.get("campaign_id"),
            "total_items": job.data.get("total_items", 0),
            "processed_items": job.data.get("processed_items", 0),
            "matches_count": job.data.get("matches_count", 0),
            "error_message": job.data.get("error_message"),
        },
        "discovered_images": {
            "count": len(discovered.data) if discovered.data else 0,
            "processed": len([d for d in discovered.data if d.get("is_processed")]) if discovered.data else 0,
            "unprocessed": len([d for d in discovered.data if not d.get("is_processed")]) if discovered.data else 0,
            "images": [
                {
                    "id": d["id"],
                    "source_type": d.get("source_type"),
                    "channel": d.get("channel"),
                    "is_processed": d.get("is_processed"),
                    "image_url": d["image_url"][:100] + "..." if len(d["image_url"]) > 100 else d["image_url"],
                    "distributor_id": d.get("distributor_id"),
                }
                for d in (discovered.data or [])[:10]  # Limit to first 10
            ]
        },
        "campaign_assets": {
            "count": len(assets),
            "assets": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "file_url": a["file_url"][:100] + "..." if len(a["file_url"]) > 100 else a["file_url"],
                }
                for a in assets[:10]  # Limit to first 10
            ],
            "warning": "No campaign assets found - cannot match!" if len(assets) == 0 and job.data.get("campaign_id") else None
        },
        "matches": {
            "count": len(matches),
            "matches": [
                {
                    "id": m["id"],
                    "asset_id": m["asset_id"],
                    "confidence_score": m.get("confidence_score"),
                    "match_type": m.get("match_type"),
                    "compliance_status": m.get("compliance_status"),
                }
                for m in matches[:10]  # Limit to first 10
            ]
        },
        "diagnosis": {
            "has_campaign": job.data.get("campaign_id") is not None,
            "has_discovered_images": len(discovered.data) > 0 if discovered.data else False,
            "has_campaign_assets": len(assets) > 0,
            "has_matches": len(matches) > 0,
            "all_images_processed": all(d.get("is_processed") for d in discovered.data) if discovered.data else True,
            "issues": _get_scan_issues(job.data, discovered.data, assets, matches)
        }
    }


def _get_scan_issues(job, discovered, assets, matches):
    """Identify potential issues with the scan."""
    issues = []
    
    if not job.get("campaign_id"):
        issues.append("No campaign linked to scan - cannot match against assets")
    
    if not discovered:
        issues.append("No images were discovered during the scan")
    elif len(discovered) == 0:
        issues.append("Scan completed but no images found")
    
    if job.get("campaign_id") and len(assets) == 0:
        issues.append("Campaign has no assets uploaded - upload assets before scanning")
    
    if discovered and len(discovered) > 0 and len(matches) == 0:
        unprocessed = [d for d in discovered if not d.get("is_processed")]
        if len(unprocessed) > 0:
            issues.append(f"{len(unprocessed)} images haven't been processed yet")
        else:
            issues.append("All images processed but no matches found - assets may not match discovered images or thresholds too high")
    
    # Check for asset URL accessibility issues
    for asset in assets:
        url = asset.get("file_url", "")
        if "supabase" in url.lower() and "/storage/v1/" in url:
            if "public" not in url.lower():
                issues.append(f"Asset '{asset.get('name')}' may not be publicly accessible (private Supabase storage)")
    
    if job.get("status") == "failed":
        issues.append(f"Scan failed: {job.get('error_message', 'Unknown error')}")
    
    return issues if issues else ["No issues detected"]
