"""Match routes."""
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from uuid import UUID
import asyncio
from concurrent.futures import ThreadPoolExecutor

from ..database import supabase
from ..models import Match, MatchUpdate, ComplianceStatus

router = APIRouter(prefix="/matches", tags=["matches"])

# Thread pool for parallel DB queries
_executor = ThreadPoolExecutor(max_workers=10)


async def run_in_thread(func):
    """Run a synchronous function in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, func)


@router.get("", response_model=List[Match])
async def list_matches(
    organization_id: Optional[UUID] = None,
    campaign_id: Optional[UUID] = None,
    distributor_id: Optional[UUID] = None,
    compliance_status: Optional[ComplianceStatus] = None,
    match_type: Optional[str] = None,
    min_confidence: Optional[float] = None,
    limit: int = 50,
    offset: int = 0
):
    """List all matches with filters."""
    def query():
        q = supabase.table("recent_matches").select("*")
        if distributor_id:
            q = q.eq("distributor_id", str(distributor_id))
        if compliance_status:
            q = q.eq("compliance_status", compliance_status.value)
        if match_type:
            q = q.eq("match_type", match_type)
        if min_confidence:
            q = q.gte("confidence_score", min_confidence)
        return q.range(offset, offset + limit - 1).execute()
    
    result = await run_in_thread(query)
    return result.data


@router.get("/stats")
async def get_match_stats(organization_id: Optional[UUID] = None):
    """Get match statistics using efficient SQL aggregation."""
    try:
        # Try using the optimized RPC function first
        def rpc_query():
            return supabase.rpc("get_match_stats").execute()
        
        result = await run_in_thread(rpc_query)
        
        # The RPC returns the stats directly as JSON
        if result.data:
            return result.data
    except Exception as e:
        # RPC function might not exist, fall back to direct queries
        print(f"RPC get_match_stats failed, using fallback: {e}")
    
    # Fallback: compute stats from matches table directly
    def get_all_matches():
        return supabase.table("matches").select("compliance_status, match_type, confidence_score").execute()
    
    result = await run_in_thread(get_all_matches)
    
    total = len(result.data) if result.data else 0
    compliance_counts = {"compliant": 0, "violation": 0, "pending": 0}
    type_counts = {"exact": 0, "strong": 0, "partial": 0}
    scores = []
    
    for match in (result.data or []):
        status = match.get("compliance_status")
        if status in compliance_counts:
            compliance_counts[status] += 1
        
        mtype = match.get("match_type")
        if mtype in type_counts:
            type_counts[mtype] += 1
        
        if match.get("confidence_score"):
            scores.append(match["confidence_score"])
    
    avg_confidence = sum(scores) / len(scores) if scores else 0.0
    
    return {
        "total_matches": total,
        "compliant": compliance_counts["compliant"],
        "violations": compliance_counts["violation"],
        "pending_review": compliance_counts["pending"],
        "by_type": type_counts,
        "average_confidence": round(avg_confidence, 2),
        "compliance_rate": round(
            compliance_counts["compliant"] / max(total, 1) * 100, 1
        )
    }


@router.get("/{match_id}", response_model=Match)
async def get_match(match_id: UUID):
    """Get a specific match with full details."""
    def query():
        return supabase.table("recent_matches")\
            .select("*")\
            .eq("id", str(match_id))\
            .single()\
            .execute()
    
    result = await run_in_thread(query)
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")
    
    return result.data


@router.patch("/{match_id}", response_model=Match)
async def update_match(match_id: UUID, match: MatchUpdate):
    """Update match compliance status."""
    data = match.model_dump(exclude_unset=True)
    
    if "compliance_status" in data:
        data["reviewed_at"] = "now()"
    
    def query():
        return supabase.table("matches")\
            .update(data)\
            .eq("id", str(match_id))\
            .execute()
    
    result = await run_in_thread(query)
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")
    
    return result.data[0]


@router.post("/{match_id}/approve")
async def approve_match(match_id: UUID):
    """Mark a match as compliant."""
    def query():
        return supabase.table("matches")\
            .update({
                "compliance_status": "compliant",
                "reviewed_at": "now()"
            })\
            .eq("id", str(match_id))\
            .execute()
    
    result = await run_in_thread(query)
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")
    
    return {"status": "approved", "match_id": str(match_id)}


@router.post("/{match_id}/flag")
async def flag_match(match_id: UUID, reason: Optional[str] = None):
    """Flag a match as a violation."""
    update_data = {
        "compliance_status": "violation",
        "reviewed_at": "now()"
    }
    
    if reason:
        # Append to compliance issues
        def get_current():
            return supabase.table("matches")\
                .select("compliance_issues")\
                .eq("id", str(match_id))\
                .single()\
                .execute()
        
        current = await run_in_thread(get_current)
        issues = current.data.get("compliance_issues", []) if current.data else []
        issues.append({"type": "manual_flag", "reason": reason})
        update_data["compliance_issues"] = issues
    
    def update_query():
        return supabase.table("matches")\
            .update(update_data)\
            .eq("id", str(match_id))\
            .execute()
    
    result = await run_in_thread(update_query)
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")
    
    return {"status": "flagged", "match_id": str(match_id)}


@router.delete("/{match_id}")
async def delete_match(match_id: UUID):
    """Delete a specific match."""
    def query():
        return supabase.table("matches")\
            .delete()\
            .eq("id", str(match_id))\
            .execute()
    
    result = await run_in_thread(query)
    
    return {"status": "deleted", "match_id": str(match_id)}


@router.delete("")
async def delete_all_matches():
    """Delete all matches. Use with caution - for testing purposes."""
    def query():
        # Delete all matches by selecting all and deleting
        return supabase.table("matches")\
            .delete()\
            .neq("id", "00000000-0000-0000-0000-000000000000")\
            .execute()
    
    result = await run_in_thread(query)
    deleted_count = len(result.data) if result.data else 0
    
    return {"status": "deleted", "count": deleted_count}


@router.post("/link-google-ads-distributors")
async def link_google_ads_distributors():
    """
    Link orphaned Google Ads matches to distributors based on advertiser_id.
    
    This finds matches from google_ads channel that have no distributor_id,
    looks up the advertiser_id from discovered_images metadata,
    and links them to the distributor with matching google_ads_advertiser_id.
    """
    # Get all distributors with their google_ads_advertiser_id
    def get_distributors():
        return supabase.table("distributors")\
            .select("id, google_ads_advertiser_id")\
            .not_.is_("google_ads_advertiser_id", "null")\
            .execute()
    
    distributors_result = await run_in_thread(get_distributors)
    
    # Build mapping of advertiser_id -> distributor_id (case-insensitive)
    advertiser_to_distributor = {}
    for d in distributors_result.data:
        ad_id = d.get("google_ads_advertiser_id")
        if ad_id:
            advertiser_to_distributor[ad_id.lower()] = d["id"]
            advertiser_to_distributor[ad_id] = d["id"]  # Also keep original case
    
    if not advertiser_to_distributor:
        return {"status": "no_distributors", "message": "No distributors have Google Ads advertiser IDs configured", "updated": 0}
    
    # Get orphaned matches (google_ads channel, no distributor_id)
    def get_orphaned_matches():
        return supabase.table("matches")\
            .select("id, discovered_image_id")\
            .eq("channel", "google_ads")\
            .is_("distributor_id", "null")\
            .execute()
    
    matches_result = await run_in_thread(get_orphaned_matches)
    
    if not matches_result.data:
        return {"status": "no_orphans", "message": "No orphaned Google Ads matches found", "updated": 0}
    
    # Get discovered_images to look up metadata
    image_ids = [m["discovered_image_id"] for m in matches_result.data if m.get("discovered_image_id")]
    
    def get_images():
        return supabase.table("discovered_images")\
            .select("id, metadata, distributor_id")\
            .in_("id", image_ids)\
            .execute()
    
    images_result = await run_in_thread(get_images)
    
    # Build image_id -> advertiser_id mapping
    image_metadata = {img["id"]: img for img in images_result.data}
    
    updated_count = 0
    for match in matches_result.data:
        img_id = match.get("discovered_image_id")
        if not img_id or img_id not in image_metadata:
            continue
        
        img = image_metadata[img_id]
        metadata = img.get("metadata", {})
        advertiser_id = metadata.get("advertiser_id", "")
        
        # Look up distributor
        distributor_id = (
            advertiser_to_distributor.get(advertiser_id.lower()) or
            advertiser_to_distributor.get(advertiser_id)
        )
        
        if distributor_id:
            # Update the match
            supabase.table("matches").update({
                "distributor_id": distributor_id
            }).eq("id", match["id"]).execute()
            
            # Also update the discovered_image if it doesn't have distributor_id
            if not img.get("distributor_id"):
                supabase.table("discovered_images").update({
                    "distributor_id": distributor_id
                }).eq("id", img_id).execute()
            
            updated_count += 1
            print(f"[Link] Linked match {match['id']} to distributor {distributor_id} (advertiser: {advertiser_id})")
    
    return {
        "status": "success",
        "message": f"Linked {updated_count} matches to distributors",
        "updated": updated_count,
        "total_orphans": len(matches_result.data)
    }




