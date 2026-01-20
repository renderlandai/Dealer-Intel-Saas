"""Distributor routes."""
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from uuid import UUID
import asyncio
from concurrent.futures import ThreadPoolExecutor

from ..database import supabase
from ..models import (
    Distributor, DistributorCreate, DistributorUpdate
)
from ..services import apify_service

router = APIRouter(prefix="/distributors", tags=["distributors"])

# Thread pool for parallel DB queries
_executor = ThreadPoolExecutor(max_workers=10)


async def run_in_thread(func):
    """Run a synchronous function in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, func)


@router.get("", response_model=List[Distributor])
async def list_distributors(
    organization_id: Optional[UUID] = None,
    status: Optional[str] = None,
    region: Optional[str] = None
):
    """List all distributors."""
    def get_distributors():
        query = supabase.table("distributors").select("*")
        if organization_id:
            query = query.eq("organization_id", str(organization_id))
        if status:
            query = query.eq("status", status)
        if region:
            query = query.eq("region", region)
        return query.order("name").execute()
    
    # First get the distributors
    distributors_result = await run_in_thread(get_distributors)
    
    # Get list of distributor IDs to filter matches
    distributor_ids = [d["id"] for d in distributors_result.data]
    
    if not distributor_ids:
        return []
    
    # Get matches only for these distributors
    def get_match_counts():
        return supabase.table("matches")\
            .select("distributor_id, compliance_status")\
            .in_("distributor_id", distributor_ids)\
            .execute()
    
    matches_result = await run_in_thread(get_match_counts)
    
    # Count matches and violations per distributor
    match_counts = {}
    violation_counts = {}
    for match in matches_result.data:
        did = match.get("distributor_id")
        if did:
            match_counts[did] = match_counts.get(did, 0) + 1
            # Track if this distributor has any violations
            if match.get("compliance_status") == "violation":
                violation_counts[did] = violation_counts.get(did, 0) + 1
    
    # Add match counts and violation status to distributors
    distributors = []
    for dist in distributors_result.data:
        dist["match_count"] = match_counts.get(dist["id"], 0)
        dist["has_violation"] = dist["id"] in violation_counts
        dist["violation_count"] = violation_counts.get(dist["id"], 0)
        distributors.append(dist)
    
    return distributors


@router.get("/{distributor_id}", response_model=Distributor)
async def get_distributor(distributor_id: UUID):
    """Get a specific distributor."""
    def get_distributor_data():
        return supabase.table("distributors").select("*").eq("id", str(distributor_id)).execute()
    
    def get_match_count():
        return supabase.table("matches").select("id", count="exact").eq("distributor_id", str(distributor_id)).execute()
    
    # Run both queries in parallel
    result, match_count = await asyncio.gather(
        run_in_thread(get_distributor_data),
        run_in_thread(get_match_count),
    )
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")
    
    distributor_data = result.data[0]
    distributor_data["match_count"] = match_count.count or 0
    
    return distributor_data


@router.post("", response_model=Distributor)
async def create_distributor(distributor: DistributorCreate):
    """Create a new distributor."""
    data = distributor.model_dump()
    data["organization_id"] = str(data["organization_id"])
    
    result = supabase.table("distributors").insert(data).execute()
    return result.data[0]


@router.patch("/{distributor_id}", response_model=Distributor)
async def update_distributor(distributor_id: UUID, distributor: DistributorUpdate):
    """Update a distributor."""
    data = distributor.model_dump(exclude_unset=True)
    
    result = supabase.table("distributors")\
        .update(data)\
        .eq("id", str(distributor_id))\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")
    
    return result.data[0]


@router.delete("/{distributor_id}")
async def delete_distributor(distributor_id: UUID):
    """Delete a distributor."""
    result = supabase.table("distributors")\
        .delete()\
        .eq("id", str(distributor_id))\
        .execute()
    
    return {"status": "deleted"}


@router.get("/{distributor_id}/matches")
async def get_distributor_matches(
    distributor_id: UUID,
    limit: int = 50,
    offset: int = 0
):
    """Get all matches for a distributor."""
    def query():
        return supabase.table("matches")\
            .select("*, assets(name, file_url), campaigns:assets(campaign_id)")\
            .eq("distributor_id", str(distributor_id))\
            .order("created_at", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
    
    result = await run_in_thread(query)
    return result.data


@router.post("/bulk", response_model=List[Distributor])
async def bulk_create_distributors(distributors: List[DistributorCreate]):
    """Bulk create distributors."""
    data = [d.model_dump() for d in distributors]
    for d in data:
        d["organization_id"] = str(d["organization_id"])
    
    result = supabase.table("distributors").insert(data).execute()
    return result.data


@router.post("/{distributor_id}/lookup-google-ads-id")
async def lookup_google_ads_id(distributor_id: UUID):
    """
    Look up the Google Ads Advertiser ID for a distributor by searching
    the Google Ads Transparency Center using the distributor's name.
    
    If found, automatically updates the distributor's google_ads_advertiser_id field.
    """
    from urllib.parse import quote
    
    # Get distributor
    result = supabase.table("distributors")\
        .select("*")\
        .eq("id", str(distributor_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")
    
    distributor = result.data
    company_name = distributor.get("name")
    
    if not company_name:
        raise HTTPException(status_code=400, detail="Distributor has no name")
    
    # Generate the manual search URL
    encoded_name = quote(company_name.strip())
    search_url = f"https://adstransparency.google.com/?region=anywhere&query={encoded_name}"
    
    # Look up the advertiser ID
    lookup_result = await apify_service.lookup_google_ads_advertiser_id(company_name)
    
    if lookup_result and lookup_result.get("advertiser_id"):
        # Update the distributor with the found ID
        advertiser_id = lookup_result["advertiser_id"]
        
        supabase.table("distributors").update({
            "google_ads_advertiser_id": advertiser_id
        }).eq("id", str(distributor_id)).execute()
        
        return {
            "success": True,
            "advertiser_id": advertiser_id,
            "advertiser_name": lookup_result.get("advertiser_name", ""),
            "url": lookup_result.get("url", ""),
            "search_url": search_url,
            "message": f"Found and saved advertiser ID: {advertiser_id}"
        }
    else:
        return {
            "success": False,
            "advertiser_id": None,
            "search_url": search_url,
            "message": f"Could not auto-detect advertiser ID. Please search manually and copy the AR... ID from the URL."
        }


@router.patch("/{distributor_id}/google-ads-id")
async def set_google_ads_id(distributor_id: UUID, advertiser_id: str):
    """
    Manually set the Google Ads Advertiser ID for a distributor.
    """
    # Validate the format
    if not advertiser_id.startswith("AR") or not advertiser_id[2:].isdigit():
        raise HTTPException(
            status_code=400, 
            detail="Invalid advertiser ID format. Must start with 'AR' followed by numbers (e.g., AR18135649662495883265)"
        )
    
    result = supabase.table("distributors").update({
        "google_ads_advertiser_id": advertiser_id
    }).eq("id", str(distributor_id)).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Distributor not found")
    
    return {
        "success": True,
        "advertiser_id": advertiser_id,
        "message": f"Saved advertiser ID: {advertiser_id}"
    }


@router.post("/lookup-google-ads-id-by-name")
async def lookup_google_ads_id_by_name(company_name: str):
    """
    Look up a Google Ads Advertiser ID by company name without saving.
    
    Useful for testing or manual lookups.
    """
    if not company_name or not company_name.strip():
        raise HTTPException(status_code=400, detail="Company name is required")
    
    lookup_result = await apify_service.lookup_google_ads_advertiser_id(company_name.strip())
    
    if lookup_result and lookup_result.get("advertiser_id"):
        return {
            "success": True,
            "advertiser_id": lookup_result["advertiser_id"],
            "advertiser_name": lookup_result.get("advertiser_name", ""),
            "url": lookup_result.get("url", "")
        }
    else:
        return {
            "success": False,
            "advertiser_id": None,
            "message": f"No Google Ads advertiser found for '{company_name}'"
        }

