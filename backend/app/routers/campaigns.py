"""Campaign and Asset routes."""
import base64
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request, Query
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import List, Optional
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import (
    Campaign, CampaignCreate, CampaignUpdate,
    Asset, AssetCreate, AssetUpdate,
    ScanJob, ScanSource, ScanJobCreate
)
from ..plan_enforcement import (
    OrgPlan, get_org_plan,
    check_campaign_limit, check_scan_quota,
    check_concurrent_scans, check_channel_allowed,
)

log = logging.getLogger("dealer_intel.campaigns")

limiter = Limiter(key_func=get_remote_address)

log = logging.getLogger("dealer_intel.campaigns")

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ============================================
# CAMPAIGNS
# ============================================

@router.get("", response_model=List[Campaign], summary="List campaigns")
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

    campaign_ids = [c["id"] for c in campaigns_result.data]
    assets_result = supabase.table("assets").select("campaign_id").in_("campaign_id", campaign_ids).execute() if campaign_ids else type("R", (), {"data": []})()

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


@router.get("/{campaign_id}", response_model=Campaign, summary="Get campaign")
async def get_campaign(campaign_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get a specific campaign."""
    result = supabase.table("campaigns").select("*").eq("id", str(campaign_id)).eq("organization_id", str(user.org_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Campaign not found")

    asset_count = supabase.table("assets").select("id", count="exact").eq("campaign_id", str(campaign_id)).execute()

    campaign_data = result.data[0]
    campaign_data["asset_count"] = asset_count.count or 0

    return campaign_data


@router.post("", response_model=Campaign, summary="Create campaign")
@limiter.limit("10/minute")
async def create_campaign(
    request: Request,
    campaign: CampaignCreate,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Create a new campaign."""
    check_campaign_limit(op)

    data = campaign.model_dump()
    data["organization_id"] = str(user.org_id)
    
    if data.get("start_date"):
        data["start_date"] = data["start_date"].isoformat()
    if data.get("end_date"):
        data["end_date"] = data["end_date"].isoformat()
    
    result = supabase.table("campaigns").insert(data).execute()
    return result.data[0]


@router.patch("/{campaign_id}", response_model=Campaign, summary="Update campaign")
@limiter.limit("20/minute")
async def update_campaign(request: Request, campaign_id: UUID, campaign: CampaignUpdate, user: AuthUser = Depends(get_current_user)):
    """Update a campaign."""
    data = campaign.model_dump(exclude_unset=True)
    
    if data.get("start_date"):
        data["start_date"] = data["start_date"].isoformat()
    if data.get("end_date"):
        data["end_date"] = data["end_date"].isoformat()
    
    result = supabase.table("campaigns")\
        .update(data)\
        .eq("id", str(campaign_id))\
        .eq("organization_id", str(user.org_id))\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return result.data[0]


@router.delete("/{campaign_id}", summary="Delete campaign")
@limiter.limit("10/minute")
async def delete_campaign(request: Request, campaign_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Delete a campaign."""
    supabase.table("campaigns")\
        .delete()\
        .eq("id", str(campaign_id))\
        .eq("organization_id", str(user.org_id))\
        .execute()
    
    return {"status": "deleted"}


# ============================================
# ASSETS
# ============================================

def _verify_campaign_ownership(campaign_id: UUID, org_id: UUID) -> None:
    """Raise 404 if the campaign doesn't belong to the given org."""
    check = supabase.table("campaigns")\
        .select("id")\
        .eq("id", str(campaign_id))\
        .eq("organization_id", str(org_id))\
        .maybe_single()\
        .execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Campaign not found")


@router.get("/{campaign_id}/assets", response_model=List[Asset], summary="List campaign assets")
async def list_campaign_assets(campaign_id: UUID, user: AuthUser = Depends(get_current_user)):
    """List all assets for a campaign."""
    _verify_campaign_ownership(campaign_id, user.org_id)
    result = supabase.table("assets")\
        .select("*")\
        .eq("campaign_id", str(campaign_id))\
        .order("created_at", desc=True)\
        .execute()
    
    return result.data


_VALID_TARGET_PLATFORMS = {s.value for s in ScanSource}


def _normalize_target_platforms(values: Optional[List[str]]) -> List[str]:
    """Validate and de-duplicate platform tags. Empty list = all channels."""
    if not values:
        return []
    cleaned: List[str] = []
    seen: set[str] = set()
    for raw in values:
        if not raw:
            continue
        v = str(raw).strip().lower()
        if v in seen:
            continue
        if v not in _VALID_TARGET_PLATFORMS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid target platform '{raw}'. Allowed: {', '.join(sorted(_VALID_TARGET_PLATFORMS))}",
            )
        seen.add(v)
        cleaned.append(v)
    return cleaned


@router.post("/{campaign_id}/assets", response_model=Asset, summary="Create asset")
@limiter.limit("10/minute")
async def create_asset(request: Request, campaign_id: UUID, asset: AssetCreate, user: AuthUser = Depends(get_current_user)):
    """Create a new asset."""
    _verify_campaign_ownership(campaign_id, user.org_id)
    data = asset.model_dump()
    data["campaign_id"] = str(campaign_id)
    data["target_platforms"] = _normalize_target_platforms(data.get("target_platforms"))

    result = supabase.table("assets").insert(data).execute()
    return result.data[0]


@router.post("/{campaign_id}/assets/upload", response_model=Asset, summary="Upload asset file")
@limiter.limit("10/minute")
async def upload_asset(
    request: Request,
    campaign_id: UUID,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    target_platforms: Optional[List[str]] = Form(None),
    user: AuthUser = Depends(get_current_user),
):
    """Upload an asset file.

    `target_platforms` (optional, multipart-repeatable) tags this creative
    with the channels it's approved for. Empty/omitted = all channels.
    Allowed values mirror `ScanSource`: google_ads, facebook, instagram,
    youtube, website. Send as repeated form fields, e.g.
    `target_platforms=facebook&target_platforms=instagram`.
    """
    _verify_campaign_ownership(campaign_id, user.org_id)
    normalized_platforms = _normalize_target_platforms(target_platforms)
    import uuid as uuid_lib
    import time
    import base64
    import io
    import os

    ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/svg+xml"}
    PSD_TYPES = {"image/vnd.adobe.photoshop", "image/x-photoshop", "application/x-photoshop"}

    # Two-tier size cap. The raw upload cap protects worker RAM from
    # arbitrary client payloads; the stored cap bounds what the matcher
    # pipeline (hash, CLIP, Claude) actually has to operate on.
    #
    # Why two tiers instead of one. Layered Photoshop sources from
    # dealer creative teams routinely run 30-60 MB even when the visible
    # composite would render as a 2-5 MB PNG. The previous single 25 MB
    # cap rejected those PSDs before rasterization had a chance to flatten
    # them, even though the *stored* asset would have been small. The
    # raw cap is generous enough to absorb a typical print-quality PSD;
    # the stored cap stays at the historical 25 MB so non-PSD uploads
    # see no behaviour change and the matcher pipeline's per-asset RAM
    # footprint is unchanged.
    MAX_RAW_UPLOAD_BYTES = 75 * 1024 * 1024   # raw multipart payload ceiling
    MAX_STORED_BYTES = 25 * 1024 * 1024       # post-rasterization ceiling

    raw_filename = file.filename or "unnamed"
    incoming_ext = os.path.splitext(raw_filename)[1].lower()
    is_psd_by_ext = incoming_ext == ".psd"
    is_psd_by_type = (file.content_type or "").lower() in PSD_TYPES

    content_type = (file.content_type or "").lower()
    accepted = (
        content_type in ALLOWED_TYPES
        or is_psd_by_type
        or is_psd_by_ext
        or not content_type  # browsers occasionally omit the type — defer to extension/magic-bytes check below
    )
    if not accepted:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{file.content_type}' not allowed. "
                f"Accepted: {', '.join(sorted(ALLOWED_TYPES))}, image/vnd.adobe.photoshop (.psd)."
            ),
        )

    content = await file.read()

    if len(content) > MAX_RAW_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(content) / 1024 / 1024:.1f} MB). "
                f"Maximum upload size is {MAX_RAW_UPLOAD_BYTES // 1024 // 1024} MB. "
                "Flatten the file or export to PNG/JPG before re-uploading."
            ),
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    # Detect PSD by magic bytes ("8BPS") in case the MIME/extension lied.
    is_psd = is_psd_by_ext or is_psd_by_type or content[:4] == b"8BPS"

    # If the upload is a PSD, rasterize to a flat PNG so the rest of the
    # pipeline (browser previews, AI matching) keeps working unchanged.
    # The original PSD bytes are discarded; we keep only the composite PNG.
    stored_content = content
    stored_content_type = file.content_type or "application/octet-stream"
    file_name = raw_filename

    if is_psd:
        try:
            from psd_tools import PSDImage  # type: ignore

            psd = PSDImage.open(io.BytesIO(content))
            composite = psd.composite()
            if composite is None:
                raise ValueError("PSD has no rasterizable composite layer")
            png_buf = io.BytesIO()
            composite.convert("RGBA").save(png_buf, format="PNG", optimize=True)
            stored_content = png_buf.getvalue()
            stored_content_type = "image/png"
            base, _ = os.path.splitext(raw_filename)
            file_name = f"{base or 'asset'}.png"
        except Exception as psd_error:
            log.error("PSD rasterization failed: %s", psd_error)
            raise HTTPException(
                status_code=400,
                detail="Could not read this .psd file. Please re-export it from Photoshop and try again.",
            )

    if not is_psd and stored_content_type not in ALLOWED_TYPES:
        # Final guard for unknown/missing MIMEs that slipped past the early check.
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{stored_content_type}' not allowed. "
                f"Accepted: {', '.join(sorted(ALLOWED_TYPES))}, image/vnd.adobe.photoshop (.psd)."
            ),
        )

    # Post-rasterization cap. For non-PSD uploads ``stored_content`` is
    # ``content`` so this is effectively a second check at the same byte
    # count — fine, it just costs one comparison. For PSDs the stored
    # bytes are the flattened PNG, which is what the matcher actually
    # works on; reject if it's somehow still larger than the matcher
    # budget (e.g. an absurdly high-res print PSD whose composite is
    # itself >25 MB even after PNG compression).
    if len(stored_content) > MAX_STORED_BYTES:
        if is_psd:
            detail = (
                f"Flattened PSD is too large ({len(stored_content) / 1024 / 1024:.1f} MB). "
                f"Maximum stored size is {MAX_STORED_BYTES // 1024 // 1024} MB. "
                "Reduce the canvas resolution in Photoshop, then re-upload."
            )
        else:
            detail = (
                f"File too large ({len(stored_content) / 1024 / 1024:.1f} MB). "
                f"Maximum stored size is {MAX_STORED_BYTES // 1024 // 1024} MB. "
                "Re-export at a lower resolution or higher compression and re-upload."
            )
        raise HTTPException(status_code=400, detail=detail)

    asset_name = name or file_name

    timestamp = int(time.time() * 1000)
    random_id = uuid_lib.uuid4().hex[:12]
    unique_filename = f"{timestamp}_{random_id}_{file_name}"
    storage_path = f"assets/{campaign_id}/{unique_filename}"

    file_url = None

    try:
        bucket = supabase.storage.from_("campaign-assets")
        bucket.upload(
            path=storage_path,
            file=stored_content,
            file_options={"contentType": stored_content_type, "upsert": "true"}
        )
        file_url = bucket.get_public_url(storage_path)

    except Exception as storage_error:
        log.error("Storage upload failed: %s", storage_error)
        # Fallback: inline data URL (works without a storage bucket configured).
        base64_content = base64.b64encode(stored_content).decode('utf-8')
        file_url = f"data:{stored_content_type};base64,{base64_content}"

    try:
        asset_data = {
            "campaign_id": str(campaign_id),
            "name": asset_name,
            "file_url": file_url,
            "file_type": stored_content_type,
            "file_size": len(stored_content),
            "target_platforms": normalized_platforms,
        }

        result = supabase.table("assets").insert(asset_data).execute()
        return result.data[0]

    except Exception as e:
        error_str = str(e)
        log.error("Database error: %s: %s", type(e).__name__, error_str)
        raise HTTPException(status_code=500, detail="Failed to save asset. Please try again.")


@router.get("/assets/{asset_id}", response_model=Asset, summary="Get asset")
async def get_asset(asset_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get a specific asset."""
    result = supabase.table("assets")\
        .select("*, campaigns!inner(organization_id)")\
        .eq("id", str(asset_id))\
        .eq("campaigns.organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    result.data.pop("campaigns", None)
    return result.data


@router.get("/assets/{asset_id}/thumbnail", summary="Serve asset thumbnail")
async def get_asset_thumbnail(asset_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Return the asset image as raw bytes (avoids base64 in JSON payloads)."""
    result = supabase.table("assets")\
        .select("file_url, file_type, campaigns!inner(organization_id)")\
        .eq("id", str(asset_id))\
        .eq("campaigns.organization_id", str(user.org_id))\
        .maybe_single()\
        .execute()

    if not result.data or not result.data.get("file_url"):
        raise HTTPException(status_code=404, detail="Asset image not found")

    file_url: str = result.data["file_url"]
    if file_url.startswith("data:"):
        header, b64 = file_url.split(",", 1)
        media_type = header.split(";")[0].replace("data:", "")
        img_bytes = base64.b64decode(b64)
    else:
        raise HTTPException(status_code=404, detail="No inline image available")

    return Response(
        content=img_bytes,
        media_type=media_type or "image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.patch("/assets/{asset_id}", response_model=Asset, summary="Update asset")
@limiter.limit("20/minute")
async def update_asset(
    request: Request,
    asset_id: UUID,
    payload: AssetUpdate,
    user: AuthUser = Depends(get_current_user),
):
    """Update an asset's mutable fields (name, metadata, target_platforms)."""
    asset = supabase.table("assets")\
        .select("id, campaigns!inner(organization_id)")\
        .eq("id", str(asset_id))\
        .eq("campaigns.organization_id", str(user.org_id))\
        .maybe_single()\
        .execute()
    if not asset.data:
        raise HTTPException(status_code=404, detail="Asset not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "target_platforms" in update_data:
        update_data["target_platforms"] = _normalize_target_platforms(update_data["target_platforms"])
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = supabase.table("assets")\
        .update(update_data)\
        .eq("id", str(asset_id))\
        .execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update asset")
    return result.data[0]


@router.delete("/assets/{asset_id}", summary="Delete asset")
@limiter.limit("20/minute")
async def delete_asset(request: Request, asset_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Delete an asset."""
    asset = supabase.table("assets")\
        .select("id, campaigns!inner(organization_id)")\
        .eq("id", str(asset_id))\
        .eq("campaigns.organization_id", str(user.org_id))\
        .maybe_single()\
        .execute()
    if not asset.data:
        raise HTTPException(status_code=404, detail="Asset not found")

    supabase.table("assets")\
        .delete()\
        .eq("id", str(asset_id))\
        .execute()
    
    return {"status": "deleted"}


# ============================================
# CAMPAIGN SCANS
# ============================================

def _resolve_scan_distributors(
    org_id: UUID,
    distributor_ids: Optional[List[UUID]],
) -> list[dict]:
    """Resolve which dealers a campaign scan should target.

    If `distributor_ids` is provided, restrict to those (still scoped to the
    org) without enforcing `status = 'active'` — explicit user picks override
    the active filter so paused dealers can be re-checked on demand. When
    omitted, fall back to every active dealer in the org.
    """
    if distributor_ids:
        unique_ids = list({str(d) for d in distributor_ids})
        result = supabase.table("distributors")\
            .select("*")\
            .in_("id", unique_ids)\
            .eq("organization_id", str(org_id))\
            .execute()
        return result.data or []

    result = supabase.table("distributors")\
        .select("*")\
        .eq("organization_id", str(org_id))\
        .eq("status", "active")\
        .execute()
    return result.data or []


@router.post("/{campaign_id}/scans/start", response_model=ScanJob, summary="Start campaign scan")
async def start_campaign_scan(
    campaign_id: UUID,
    source: ScanSource,
    distributor_ids: Optional[List[UUID]] = Query(
        None,
        description="Optional dealer IDs to scan. Omit to scan every active dealer in the org.",
    ),
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """
    Start a scan specifically for this campaign.
    Dispatches the scan as a background task.
    """
    check_channel_allowed(op, source.value)
    check_scan_quota(op)
    check_concurrent_scans(op)
    from ..tasks import dispatch_task
    from ..services import apify_instagram_service

    campaign = supabase.table("campaigns")\
        .select("*, organizations!campaigns_organization_id_fkey(id)")\
        .eq("id", str(campaign_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")

    distributor_list = _resolve_scan_distributors(user.org_id, distributor_ids)

    if distributor_ids and not distributor_list:
        # User explicitly picked dealers but none belonged to this org — bail
        # before we create a doomed scan job.
        raise HTTPException(
            status_code=400,
            detail="None of the selected dealers belong to this organization.",
        )

    organization_id = user.org_id

    job_data = {
        "organization_id": str(organization_id),
        "campaign_id": str(campaign_id),
        "source": source.value,
        "status": "pending"
    }

    result = supabase.table("scan_jobs").insert(job_data).execute()
    scan_job = result.data[0]
    scan_job_id = scan_job["id"]

    if not distributor_list:
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": "No active distributors found to scan"
        }).eq("id", scan_job_id).execute()
        scan_job["status"] = "failed"
        scan_job["error_message"] = "No active distributors found to scan"
        return scan_job
    
    campaign_id_str = str(campaign_id)
    dispatched = False
    
    if source == ScanSource.GOOGLE_ADS:
        names = [d.get("google_ads_advertiser_id") or d["name"] for d in distributor_list]
        mapping = {
            (d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"]
            for d in distributor_list
        }
        log.info("Starting Google Ads scan for %d advertisers, job=%s", len(names), scan_job_id)
        dispatched = await dispatch_task("run_google_ads_scan_task", [names, scan_job_id, mapping, campaign_id_str], scan_job_id, "google_ads")

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
        log.info("Starting Instagram scan for %d profiles, job=%s", len(urls), scan_job_id)
        dispatched = await dispatch_task("run_instagram_scan_task", [urls, scan_job_id, mapping, campaign_id_str], scan_job_id, "instagram")

    elif source == ScanSource.FACEBOOK:
        urls = [d["facebook_url"] for d in distributor_list if d.get("facebook_url")]
        mapping = {}
        for d in distributor_list:
            mapping[d["name"].lower()] = d["id"]
            fb_url = d.get("facebook_url")
            if fb_url:
                from urllib.parse import urlparse
                slug = urlparse(fb_url).path.strip("/").split("/")[0].lower()
                if slug:
                    mapping[slug] = d["id"]
        log.info("Starting Facebook scan for %d pages, job=%s", len(urls), scan_job_id)
        dispatched = await dispatch_task("run_facebook_scan_task", [urls, scan_job_id, mapping, campaign_id_str, "facebook"], scan_job_id, "facebook")
        
    elif source == ScanSource.WEBSITE:
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


@router.post("/{campaign_id}/scans/batch", summary="Batch scan all channels for a campaign")
@limiter.limit("2/minute")
async def batch_campaign_scan(
    request: Request,
    campaign_id: UUID,
    distributor_ids: Optional[List[UUID]] = Query(
        None,
        description="Optional dealer IDs to scan. Omit to scan every active dealer in the org.",
    ),
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Start scans across all plan-allowed channels for a specific campaign."""
    check_scan_quota(op)
    from ..tasks import dispatch_task
    from ..services import apify_instagram_service

    campaign = supabase.table("campaigns")\
        .select("id")\
        .eq("id", str(campaign_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")

    dist_list = _resolve_scan_distributors(user.org_id, distributor_ids)
    if not dist_list:
        if distributor_ids:
            raise HTTPException(
                400,
                "None of the selected dealers belong to this organization.",
            )
        raise HTTPException(400, "No active distributors found. Add dealers first.")

    allowed_channels = op.limits.get("allowed_channels", [])
    campaign_id_str = str(campaign_id)
    created_jobs: list[dict] = []

    for channel in allowed_channels:
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

        created_jobs.append(job.data[0])

    log.info("Campaign batch scan started for campaign %s, org %s: %d jobs",
             campaign_id, user.org_id, len(created_jobs))

    return {
        "message": f"Batch scan started — {len(created_jobs)} scan(s) queued",
        "jobs": created_jobs,
    }


@router.get("/{campaign_id}/scans", response_model=List[ScanJob], summary="List campaign scans")
async def list_campaign_scans(
    campaign_id: UUID,
    status: Optional[str] = None,
    limit: int = 20,
    user: AuthUser = Depends(get_current_user),
):
    """List all scan jobs for a specific campaign."""
    _verify_campaign_ownership(campaign_id, user.org_id)
    query = supabase.table("scan_jobs")\
        .select("*")\
        .eq("campaign_id", str(campaign_id))
    
    if status:
        query = query.eq("status", status)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/{campaign_id}/scans/{scan_id}", response_model=ScanJob, summary="Get campaign scan")
async def get_campaign_scan(campaign_id: UUID, scan_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get details of a specific scan job for a campaign."""
    _verify_campaign_ownership(campaign_id, user.org_id)
    result = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(scan_id))\
        .eq("campaign_id", str(campaign_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    return result.data


@router.post("/{campaign_id}/scans/{scan_id}/analyze", summary="Analyze campaign scan")
async def analyze_campaign_scan(
    campaign_id: UUID,
    scan_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """
    Analyze discovered images from a campaign scan.
    Runs as a background task.
    """
    _verify_campaign_ownership(campaign_id, user.org_id)
    from ..tasks import dispatch_task

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
    
    dispatched = await dispatch_task(
        "run_analyze_scan_task",
        [str(scan_id), str(campaign_id)],
        str(scan_id),
        "analyze_campaign",
    )
    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to queue analysis task")

    return {
        "message": "Analysis queued for campaign",
        "campaign_id": str(campaign_id),
        "image_count": image_count,
    }


@router.get("/{campaign_id}/matches", summary="Get campaign matches")
async def get_campaign_matches(
    campaign_id: UUID,
    compliance_status: Optional[str] = None,
    limit: int = 50,
    user: AuthUser = Depends(get_current_user),
):
    """Get all matches found for this campaign's assets."""
    _verify_campaign_ownership(campaign_id, user.org_id)
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


@router.get("/{campaign_id}/scan-stats", summary="Get campaign scan stats")
async def get_campaign_scan_stats(campaign_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get scan statistics for a campaign."""
    _verify_campaign_ownership(campaign_id, user.org_id)
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

