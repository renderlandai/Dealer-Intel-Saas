"""Campaign and Asset routes."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import List, Optional
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import (
    Campaign, CampaignCreate, CampaignUpdate,
    Asset, AssetCreate, AssetUpdate,
    ScanJob, ScanSource, ScanJobCreate
)

log = logging.getLogger("dealer_intel.campaigns")

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ============================================
# CAMPAIGNS
# ============================================

@router.get("", response_model=List[Campaign])
async def list_campaigns(
    status: Optional[str] = None,
    user: AuthUser = Depends(get_current_user),
):
    """List all campaigns."""
    query = supabase.table("campaigns").select("*")
    query = query.eq("organization_id", str(user.org_id))
    if status:
        query = query.eq("status", status)
    campaigns_result = query.order("created_at", desc=True).execute()

    assets_result = supabase.table("assets").select("campaign_id").execute()

    # Count assets per campaign
    asset_counts = {}
    for asset in assets_result.data:
        cid = asset.get("campaign_id")
        if cid:
            asset_counts[cid] = asset_counts.get(cid, 0) + 1

    # Add asset counts to campaigns
    campaigns = []
    for camp in campaigns_result.data:
        camp["asset_count"] = asset_counts.get(camp["id"], 0)
        campaigns.append(camp)

    return campaigns


@router.get("/{campaign_id}", response_model=Campaign)
async def get_campaign(campaign_id: UUID):
    """Get a specific campaign."""
    result = supabase.table("campaigns").select("*").eq("id", str(campaign_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Campaign not found")

    asset_count = supabase.table("assets").select("id", count="exact").eq("campaign_id", str(campaign_id)).execute()

    campaign_data = result.data[0]
    campaign_data["asset_count"] = asset_count.count or 0

    return campaign_data


@router.post("", response_model=Campaign)
async def create_campaign(campaign: CampaignCreate, user: AuthUser = Depends(get_current_user)):
    """Create a new campaign."""
    data = campaign.model_dump()
    data["organization_id"] = str(user.org_id)
    
    if data.get("start_date"):
        data["start_date"] = data["start_date"].isoformat()
    if data.get("end_date"):
        data["end_date"] = data["end_date"].isoformat()
    
    result = supabase.table("campaigns").insert(data).execute()
    return result.data[0]


@router.patch("/{campaign_id}", response_model=Campaign)
async def update_campaign(campaign_id: UUID, campaign: CampaignUpdate):
    """Update a campaign."""
    data = campaign.model_dump(exclude_unset=True)
    
    if data.get("start_date"):
        data["start_date"] = data["start_date"].isoformat()
    if data.get("end_date"):
        data["end_date"] = data["end_date"].isoformat()
    
    result = supabase.table("campaigns")\
        .update(data)\
        .eq("id", str(campaign_id))\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return result.data[0]


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: UUID):
    """Delete a campaign."""
    result = supabase.table("campaigns")\
        .delete()\
        .eq("id", str(campaign_id))\
        .execute()
    
    return {"status": "deleted"}


# ============================================
# ASSETS
# ============================================

@router.get("/{campaign_id}/assets", response_model=List[Asset])
async def list_campaign_assets(campaign_id: UUID):
    """List all assets for a campaign."""
    result = supabase.table("assets")\
        .select("*")\
        .eq("campaign_id", str(campaign_id))\
        .order("created_at", desc=True)\
        .execute()
    
    return result.data


@router.post("/{campaign_id}/assets", response_model=Asset)
async def create_asset(campaign_id: UUID, asset: AssetCreate):
    """Create a new asset."""
    data = asset.model_dump()
    data["campaign_id"] = str(campaign_id)
    
    result = supabase.table("assets").insert(data).execute()
    return result.data[0]


@router.post("/{campaign_id}/assets/upload", response_model=Asset)
async def upload_asset(
    campaign_id: UUID,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None)
):
    """Upload an asset file."""
    import uuid as uuid_lib
    import time
    import base64

    ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/svg+xml"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file.content_type}' not allowed. Accepted: {', '.join(sorted(ALLOWED_TYPES))}",
        )

    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Maximum is {MAX_FILE_SIZE // 1024 // 1024} MB.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    file_name = file.filename or "unnamed"
    asset_name = name or file_name
    
    # Generate unique filename with timestamp to avoid conflicts
    timestamp = int(time.time() * 1000)
    random_id = uuid_lib.uuid4().hex[:12]
    unique_filename = f"{timestamp}_{random_id}_{file_name}"
    storage_path = f"assets/{campaign_id}/{unique_filename}"
    
    file_url = None
    
    try:
        # Try Supabase Storage first
        bucket = supabase.storage.from_("campaign-assets")
        
        # Upload file with overwrite
        bucket.upload(
            path=storage_path,
            file=content,
            file_options={"contentType": file.content_type, "upsert": "true"}
        )
        
        # Get public URL
        file_url = bucket.get_public_url(storage_path)
        
    except Exception as storage_error:
        log.error("Storage upload failed: %s", storage_error)
        # Fallback: use base64 data URL (works without storage bucket)
        base64_content = base64.b64encode(content).decode('utf-8')
        file_url = f"data:{file.content_type};base64,{base64_content}"
    
    try:
        # Create asset record
        asset_data = {
            "campaign_id": str(campaign_id),
            "name": asset_name,
            "file_url": file_url,
            "file_type": file.content_type,
            "file_size": len(content)
        }
        
        result = supabase.table("assets").insert(asset_data).execute()
        return result.data[0]
        
    except Exception as e:
        error_str = str(e)
        log.error("Database error: %s: %s", type(e).__name__, error_str)
        raise HTTPException(status_code=500, detail="Failed to save asset. Please try again.")


@router.get("/assets/{asset_id}", response_model=Asset)
async def get_asset(asset_id: UUID):
    """Get a specific asset."""
    result = supabase.table("assets")\
        .select("*")\
        .eq("id", str(asset_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    return result.data


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: UUID):
    """Delete an asset."""
    result = supabase.table("assets")\
        .delete()\
        .eq("id", str(asset_id))\
        .execute()
    
    return {"status": "deleted"}


# ============================================
# CAMPAIGN SCANS
# ============================================

@router.post("/{campaign_id}/scans/start", response_model=ScanJob)
async def start_campaign_scan(
    campaign_id: UUID,
    source: ScanSource,
    distributor_ids: Optional[List[UUID]] = None,
    user: AuthUser = Depends(get_current_user),
):
    """
    Start a scan specifically for this campaign.
    Dispatched to Celery worker for durable background execution.
    """
    from ..tasks import (
        run_google_ads_scan_task, run_facebook_scan_task,
        run_instagram_scan_task, run_website_scan_task,
    )
    from ..services import apify_instagram_service

    campaign = supabase.table("campaigns")\
        .select("*, organizations!campaigns_organization_id_fkey(id)")\
        .eq("id", str(campaign_id))\
        .single()\
        .execute()
    
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    organization_id = campaign.data["organization_id"]
    
    job_data = {
        "organization_id": str(organization_id),
        "campaign_id": str(campaign_id),
        "source": source.value,
        "status": "pending"
    }
    
    result = supabase.table("scan_jobs").insert(job_data).execute()
    scan_job = result.data[0]
    scan_job_id = scan_job["id"]
    
    if distributor_ids:
        distributors = supabase.table("distributors")\
            .select("*")\
            .in_("id", [str(d) for d in distributor_ids])\
            .execute()
    else:
        distributors = supabase.table("distributors")\
            .select("*")\
            .eq("organization_id", str(organization_id))\
            .eq("status", "active")\
            .execute()
    
    distributor_list = distributors.data
    
    if not distributor_list:
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": "No active distributors found to scan"
        }).eq("id", scan_job_id).execute()
        scan_job["status"] = "failed"
        scan_job["error_message"] = "No active distributors found to scan"
        return scan_job
    
    campaign_id_str = str(campaign_id)
    
    if source == ScanSource.GOOGLE_ADS:
        names = [d.get("google_ads_advertiser_id") or d["name"] for d in distributor_list]
        mapping = {
            (d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"]
            for d in distributor_list
        }
        run_google_ads_scan_task.delay(names, scan_job_id, mapping, campaign_id_str)

    elif source == ScanSource.INSTAGRAM:
        urls = [d["instagram_url"] for d in distributor_list if d.get("instagram_url")]
        mapping = {}
        for d in distributor_list:
            ig_url = d.get("instagram_url")
            if ig_url:
                username = apify_instagram_service._extract_username(ig_url)
                if username:
                    mapping[username.lower()] = d["id"]
                mapping[d["name"].lower()] = d["id"]
        run_instagram_scan_task.delay(urls, scan_job_id, mapping, campaign_id_str)

    elif source == ScanSource.FACEBOOK:
        urls = [d["facebook_url"] for d in distributor_list if d.get("facebook_url")]
        mapping = {d["name"].lower(): d["id"] for d in distributor_list}
        run_facebook_scan_task.delay(urls, scan_job_id, mapping, campaign_id_str, "facebook")
        
    elif source == ScanSource.WEBSITE:
        urls = [d["website_url"] for d in distributor_list if d.get("website_url")]
        mapping = {
            d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
            for d in distributor_list if d.get("website_url")
        }
        run_website_scan_task.delay(urls, scan_job_id, mapping, campaign_id_str)
    
    return scan_job


@router.get("/{campaign_id}/scans", response_model=List[ScanJob])
async def list_campaign_scans(
    campaign_id: UUID,
    status: Optional[str] = None,
    limit: int = 20,
    user: AuthUser = Depends(get_current_user),
):
    """List all scan jobs for a specific campaign."""
    query = supabase.table("scan_jobs")\
        .select("*")\
        .eq("campaign_id", str(campaign_id))
    
    if status:
        query = query.eq("status", status)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/{campaign_id}/scans/{scan_id}", response_model=ScanJob)
async def get_campaign_scan(campaign_id: UUID, scan_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get details of a specific scan job for a campaign."""
    result = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(scan_id))\
        .eq("campaign_id", str(campaign_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    return result.data


@router.post("/{campaign_id}/scans/{scan_id}/analyze")
async def analyze_campaign_scan(
    campaign_id: UUID,
    scan_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """
    Analyze discovered images from a campaign scan.
    Dispatched to Celery worker for durable execution.
    """
    from ..tasks import analyze_scan_task

    job = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(scan_id))\
        .eq("campaign_id", str(campaign_id))\
        .single()\
        .execute()
    
    if not job.data:
        raise HTTPException(status_code=404, detail="Scan job not found for this campaign")
    
    if job.data["status"] != "completed":
        raise HTTPException(status_code=400, detail="Scan job not completed yet")
    
    images = supabase.table("discovered_images")\
        .select("id", count="exact")\
        .eq("scan_job_id", str(scan_id))\
        .eq("is_processed", False)\
        .execute()
    
    image_count = images.count or 0
    if image_count == 0:
        return {"message": "No unprocessed images found", "count": 0}
    
    analyze_scan_task.delay(str(scan_id), str(campaign_id))
    
    return {
        "message": "Analysis queued for campaign",
        "campaign_id": str(campaign_id),
        "image_count": image_count,
    }


@router.get("/{campaign_id}/matches")
async def get_campaign_matches(
    campaign_id: UUID,
    compliance_status: Optional[str] = None,
    limit: int = 50,
    user: AuthUser = Depends(get_current_user),
):
    """Get all matches found for this campaign's assets."""
    query = supabase.table("matches")\
        .select("*, assets!inner(campaign_id, name, file_url), distributors(name)")\
        .eq("assets.campaign_id", str(campaign_id))
    
    if compliance_status:
        query = query.eq("compliance_status", compliance_status)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    
    # Format response
    matches = []
    for match in result.data:
        match_data = {
            **match,
            "asset_name": match.get("assets", {}).get("name"),
            "asset_url": match.get("assets", {}).get("file_url"),
            "distributor_name": match.get("distributors", {}).get("name") if match.get("distributors") else None
        }
        # Remove nested objects
        match_data.pop("assets", None)
        match_data.pop("distributors", None)
        matches.append(match_data)
    
    return matches


@router.get("/{campaign_id}/scan-stats")
async def get_campaign_scan_stats(campaign_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get scan statistics for a campaign."""
    cid = str(campaign_id)

    scans_result = supabase.table("scan_jobs").select("status").eq("campaign_id", cid).execute()

    matches_result = supabase.table("matches")\
        .select("compliance_status, assets!inner(campaign_id)")\
        .eq("assets.campaign_id", cid)\
        .execute()

    last_scan_result = supabase.table("scan_jobs")\
        .select("*")\
        .eq("campaign_id", cid)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()

    # Count scan statuses
    status_counts = {"completed": 0, "running": 0, "failed": 0, "pending": 0}
    for scan in scans_result.data:
        status = scan.get("status", "pending")
        if status in status_counts:
            status_counts[status] += 1

    # Count match statuses
    total_matches = len(matches_result.data)
    violations = len([m for m in matches_result.data if m.get("compliance_status") == "violation"])
    compliant = len([m for m in matches_result.data if m.get("compliance_status") == "compliant"])
    pending_review = len([m for m in matches_result.data if m.get("compliance_status") in ["pending", "review"]])

    return {
        "total_scans": len(scans_result.data),
        "completed_scans": status_counts["completed"],
        "running_scans": status_counts["running"],
        "failed_scans": status_counts["failed"],
        "total_matches": total_matches,
        "violations": violations,
        "compliant": compliant,
        "pending_review": pending_review,
        "last_scan": last_scan_result.data[0] if last_scan_result.data else None
    }

