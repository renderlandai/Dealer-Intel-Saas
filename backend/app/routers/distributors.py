"""Distributor routes."""
from fastapi import APIRouter, HTTPException, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from cachetools import TTLCache
from typing import List, Optional
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import (
    Distributor, DistributorCreate, DistributorUpdate
)
from ..plan_enforcement import OrgPlan, get_org_plan, check_dealer_limit, check_dealer_limit_bulk

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/distributors", tags=["distributors"])

_dist_list_cache: TTLCache = TTLCache(maxsize=200, ttl=60)


def _verify_distributor_ownership(distributor_id: UUID, org_id: UUID) -> None:
    """Raise 404 if the distributor doesn't belong to the given org."""
    check = supabase.table("distributors")\
        .select("id")\
        .eq("id", str(distributor_id))\
        .eq("organization_id", str(org_id))\
        .maybe_single()\
        .execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Distributor not found")


@router.get("", response_model=List[Distributor], summary="List distributors")
async def list_distributors(
    status: Optional[str] = None,
    region: Optional[str] = None,
    user: AuthUser = Depends(get_current_user),
):
    """List all distributors with match/violation counts."""
    org_id = str(user.org_id)
    cache_key = f"{org_id}:{status}:{region}"
    if cache_key in _dist_list_cache:
        return _dist_list_cache[cache_key]

    query = supabase.table("distributors").select("*")
    query = query.eq("organization_id", org_id)
    if status:
        query = query.eq("status", status)
    if region:
        query = query.eq("region", region)
    distributors_result = query.order("name").execute()

    distributor_ids = [d["id"] for d in distributors_result.data]
    if not distributor_ids:
        return []

    matches_result = supabase.table("matches") \
        .select("distributor_id, compliance_status") \
        .in_("distributor_id", distributor_ids) \
        .execute()

    match_counts: dict = {}
    violation_counts: dict = {}
    for match in matches_result.data:
        did = match.get("distributor_id")
        if did:
            match_counts[did] = match_counts.get(did, 0) + 1
            if match.get("compliance_status") == "violation":
                violation_counts[did] = violation_counts.get(did, 0) + 1

    distributors = []
    for dist in distributors_result.data:
        dist["match_count"] = match_counts.get(dist["id"], 0)
        dist["has_violation"] = dist["id"] in violation_counts
        dist["violation_count"] = violation_counts.get(dist["id"], 0)
        distributors.append(dist)

    _dist_list_cache[cache_key] = distributors
    return distributors


@router.get("/{distributor_id}", response_model=Distributor, summary="Get distributor")
async def get_distributor(distributor_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get a specific distributor."""
    result = supabase.table("distributors").select("*").eq("id", str(distributor_id)).eq("organization_id", str(user.org_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")

    match_count = supabase.table("matches").select("id", count="exact").eq("distributor_id", str(distributor_id)).execute()

    distributor_data = result.data[0]
    distributor_data["match_count"] = match_count.count or 0

    return distributor_data


@router.post("", response_model=Distributor, summary="Create distributor")
@limiter.limit("10/minute")
async def create_distributor(
    request: Request,
    distributor: DistributorCreate,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Create a new distributor."""
    check_dealer_limit(op)

    data = distributor.model_dump()
    data["organization_id"] = str(user.org_id)

    result = supabase.table("distributors").insert(data).execute()
    return result.data[0]


@router.patch("/{distributor_id}", response_model=Distributor, summary="Update distributor")
@limiter.limit("20/minute")
async def update_distributor(request: Request, distributor_id: UUID, distributor: DistributorUpdate, user: AuthUser = Depends(get_current_user)):
    """Update a distributor."""
    data = distributor.model_dump(exclude_unset=True)

    result = supabase.table("distributors")\
        .update(data)\
        .eq("id", str(distributor_id))\
        .eq("organization_id", str(user.org_id))\
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")

    return result.data[0]


@router.delete("/{distributor_id}", summary="Delete distributor")
@limiter.limit("10/minute")
async def delete_distributor(request: Request, distributor_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Delete a distributor."""
    supabase.table("distributors")\
        .delete()\
        .eq("id", str(distributor_id))\
        .eq("organization_id", str(user.org_id))\
        .execute()

    return {"status": "deleted"}


@router.get("/{distributor_id}/matches", summary="Get distributor matches")
async def get_distributor_matches(
    distributor_id: UUID,
    limit: int = 50,
    offset: int = 0,
    user: AuthUser = Depends(get_current_user),
):
    """Get all matches for a distributor."""
    _verify_distributor_ownership(distributor_id, user.org_id)
    result = supabase.table("matches")\
        .select("*, assets(name, file_url), campaigns:assets(campaign_id)")\
        .eq("distributor_id", str(distributor_id))\
        .order("created_at", desc=True)\
        .range(offset, offset + limit - 1)\
        .execute()
    return result.data


@router.post("/bulk", response_model=List[Distributor], summary="Bulk create distributors")
@limiter.limit("5/minute")
async def bulk_create_distributors(
    request: Request,
    distributors: List[DistributorCreate],
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Bulk create distributors."""
    check_dealer_limit_bulk(op, len(distributors))

    data = [d.model_dump() for d in distributors]
    for d in data:
        d["organization_id"] = str(user.org_id)

    result = supabase.table("distributors").insert(data).execute()
    return result.data


@router.post("/{distributor_id}/lookup-google-ads-id", summary="Lookup Google Ads ID")
async def lookup_google_ads_id(distributor_id: UUID, user: AuthUser = Depends(get_current_user)):
    """
    Generate a Google Ads Transparency Center search URL for a distributor.
    """
    from urllib.parse import quote

    result = supabase.table("distributors")\
        .select("*")\
        .eq("id", str(distributor_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")

    company_name = result.data.get("name")
    if not company_name:
        raise HTTPException(status_code=400, detail="Distributor has no name")

    encoded_name = quote(company_name.strip())
    search_url = f"https://adstransparency.google.com/?region=anywhere&query={encoded_name}"

    return {
        "success": False,
        "advertiser_id": None,
        "search_url": search_url,
        "message": (
            f"Search for '{company_name}' at the link above, "
            f"then copy the AR... ID from the URL and save it via "
            f"PATCH /{distributor_id}/google-ads-id."
        ),
    }


@router.patch("/{distributor_id}/google-ads-id", summary="Set Google Ads ID")
@limiter.limit("20/minute")
async def set_google_ads_id(request: Request, distributor_id: UUID, advertiser_id: str, user: AuthUser = Depends(get_current_user)):
    """Manually set the Google Ads Advertiser ID for a distributor."""
    if not advertiser_id.startswith("AR") or not advertiser_id[2:].isdigit():
        raise HTTPException(
            status_code=400,
            detail="Invalid advertiser ID format. Must start with 'AR' followed by numbers (e.g., AR18135649662495883265)"
        )

    result = supabase.table("distributors").update({
        "google_ads_advertiser_id": advertiser_id
    }).eq("id", str(distributor_id)).eq("organization_id", str(user.org_id)).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")

    return {
        "success": True,
        "advertiser_id": advertiser_id,
        "message": f"Saved advertiser ID: {advertiser_id}"
    }


@router.post("/lookup-google-ads-id-by-name", summary="Lookup Ads ID by name")
async def lookup_google_ads_id_by_name(company_name: str, user: AuthUser = Depends(get_current_user)):
    """Generate a Google Ads Transparency Center search URL by company name."""
    if not company_name or not company_name.strip():
        raise HTTPException(status_code=400, detail="Company name is required")

    from urllib.parse import quote

    encoded_name = quote(company_name.strip())
    search_url = f"https://adstransparency.google.com/?region=anywhere&query={encoded_name}"

    return {
        "success": False,
        "advertiser_id": None,
        "search_url": search_url,
        "message": (
            f"Search for '{company_name}' at the link above and "
            f"copy the AR... ID from the URL."
        ),
    }
