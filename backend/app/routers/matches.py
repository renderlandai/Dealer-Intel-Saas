"""Match routes — all queries scoped to the authenticated user's organization."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import (
    Match, MatchUpdate, ComplianceStatus,
    MatchFeedbackCreate, MatchFeedback,
    FeedbackAccuracyStats, ThresholdRecommendation,
)
from ..services.adaptive_threshold_service import (
    get_all_adaptive_thresholds,
    invalidate_cache,
)


def _utc_now() -> str:
    """Return current UTC timestamp as ISO-8601 string for Supabase."""
    return datetime.now(timezone.utc).isoformat()


log = logging.getLogger("dealer_intel.matches")

router = APIRouter(prefix="/matches", tags=["matches"])


def _org_distributor_ids(org_id: str) -> List[str]:
    """Return all distributor IDs belonging to an organization."""
    result = supabase.table("distributors") \
        .select("id") \
        .eq("organization_id", org_id) \
        .execute()
    return [d["id"] for d in (result.data or [])]


def _verify_match_ownership(match_id: str, org_distributor_ids: List[str]) -> dict:
    """Fetch a match and verify it belongs to the org's distributors."""
    result = supabase.table("matches") \
        .select("*") \
        .eq("id", match_id) \
        .single() \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")

    if result.data.get("distributor_id") and result.data["distributor_id"] not in org_distributor_ids:
        raise HTTPException(status_code=404, detail="Match not found")

    return result.data


@router.get("", response_model=List[Match], summary="List matches")
async def list_matches(
    distributor_id: Optional[UUID] = None,
    compliance_status: Optional[ComplianceStatus] = None,
    match_type: Optional[str] = None,
    min_confidence: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
    user: AuthUser = Depends(get_current_user),
):
    """List matches scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    if not dist_ids:
        return []

    q = supabase.table("recent_matches").select("*")
    q = q.in_("distributor_id", dist_ids)

    if distributor_id:
        q = q.eq("distributor_id", str(distributor_id))
    if compliance_status:
        q = q.eq("compliance_status", compliance_status.value)
    if match_type:
        q = q.eq("match_type", match_type)
    if min_confidence:
        q = q.gte("confidence_score", min_confidence)

    result = q.range(offset, offset + limit - 1).execute()
    return result.data


@router.get("/stats", summary="Get match statistics")
async def get_match_stats(user: AuthUser = Depends(get_current_user)):
    """Get match statistics scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    if not dist_ids:
        return {
            "total_matches": 0,
            "compliant": 0,
            "violations": 0,
            "pending_review": 0,
            "by_type": {"exact": 0, "strong": 0, "partial": 0},
            "average_confidence": 0.0,
            "compliance_rate": 0.0,
        }

    result = supabase.table("matches") \
        .select("compliance_status, match_type, confidence_score") \
        .in_("distributor_id", dist_ids) \
        .execute()

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
        ),
    }


@router.get("/{match_id}", response_model=Match, summary="Get match")
async def get_match(match_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get a specific match scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    if not dist_ids:
        raise HTTPException(status_code=404, detail="Match not found")

    result = supabase.table("recent_matches") \
        .select("*") \
        .eq("id", str(match_id)) \
        .in_("distributor_id", dist_ids) \
        .single() \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")

    return result.data


@router.patch("/{match_id}", response_model=Match, summary="Update match")
async def update_match(
    match_id: UUID,
    match: MatchUpdate,
    user: AuthUser = Depends(get_current_user),
):
    """Update match compliance status, scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    _verify_match_ownership(str(match_id), dist_ids)

    data = match.model_dump(exclude_unset=True)
    if "compliance_status" in data:
        data["reviewed_at"] = _utc_now()

    result = supabase.table("matches") \
        .update(data) \
        .eq("id", str(match_id)) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")

    return result.data[0]


@router.post("/{match_id}/approve", summary="Approve match")
async def approve_match(match_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Mark a match as compliant, scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    _verify_match_ownership(str(match_id), dist_ids)

    result = supabase.table("matches") \
        .update({
            "compliance_status": "compliant",
            "reviewed_at": _utc_now(),
        }) \
        .eq("id", str(match_id)) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")

    return {"status": "approved", "match_id": str(match_id)}


@router.post("/{match_id}/flag", summary="Flag match as violation")
async def flag_match(
    match_id: UUID,
    reason: Optional[str] = None,
    user: AuthUser = Depends(get_current_user),
):
    """Flag a match as a violation, scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    _verify_match_ownership(str(match_id), dist_ids)

    update_data = {
        "compliance_status": "violation",
        "reviewed_at": _utc_now(),
    }

    if reason:
        current = supabase.table("matches") \
            .select("compliance_issues") \
            .eq("id", str(match_id)) \
            .single() \
            .execute()
        issues = current.data.get("compliance_issues", []) if current.data else []
        issues.append({"type": "manual_flag", "reason": reason})
        update_data["compliance_issues"] = issues

    result = supabase.table("matches") \
        .update(update_data) \
        .eq("id", str(match_id)) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Match not found")

    return {"status": "flagged", "match_id": str(match_id)}


@router.delete("/{match_id}", summary="Delete match")
async def delete_match(match_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Delete a specific match, scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    _verify_match_ownership(str(match_id), dist_ids)

    supabase.table("matches") \
        .delete() \
        .eq("id", str(match_id)) \
        .execute()

    return {"status": "deleted", "match_id": str(match_id)}


@router.delete("", summary="Delete all matches")
async def delete_all_matches(user: AuthUser = Depends(get_current_user)):
    """Delete all matches for the user's organization."""
    from ..config import get_settings
    if not get_settings().enable_dangerous_endpoints:
        raise HTTPException(status_code=403, detail="Bulk delete is disabled in this environment")

    dist_ids = _org_distributor_ids(str(user.org_id))
    if not dist_ids:
        return {"status": "deleted", "count": 0}

    result = supabase.table("matches") \
        .delete() \
        .in_("distributor_id", dist_ids) \
        .execute()
    deleted_count = len(result.data) if result.data else 0

    return {"status": "deleted", "count": deleted_count}


@router.post("/link-google-ads-distributors", summary="Link Google Ads distributors")
async def link_google_ads_distributors(user: AuthUser = Depends(get_current_user)):
    """Link orphaned Google Ads matches to distributors, scoped to the user's org."""
    org_id = str(user.org_id)

    distributors_result = supabase.table("distributors") \
        .select("id, google_ads_advertiser_id") \
        .eq("organization_id", org_id) \
        .not_.is_("google_ads_advertiser_id", "null") \
        .execute()

    advertiser_to_distributor = {}
    dist_ids = []
    for d in distributors_result.data:
        dist_ids.append(d["id"])
        ad_id = d.get("google_ads_advertiser_id")
        if ad_id:
            advertiser_to_distributor[ad_id.lower()] = d["id"]
            advertiser_to_distributor[ad_id] = d["id"]

    if not advertiser_to_distributor:
        return {"status": "no_distributors", "message": "No distributors have Google Ads advertiser IDs configured", "updated": 0}

    matches_result = supabase.table("matches") \
        .select("id, discovered_image_id") \
        .eq("channel", "google_ads") \
        .is_("distributor_id", "null") \
        .execute()

    if not matches_result.data:
        return {"status": "no_orphans", "message": "No orphaned Google Ads matches found", "updated": 0}

    image_ids = [m["discovered_image_id"] for m in matches_result.data if m.get("discovered_image_id")]

    scan_jobs = supabase.table("scan_jobs") \
        .select("id") \
        .eq("organization_id", org_id) \
        .execute()
    org_job_ids = {j["id"] for j in (scan_jobs.data or [])}

    images_result = supabase.table("discovered_images") \
        .select("id, metadata, distributor_id, scan_job_id") \
        .in_("id", image_ids) \
        .execute()

    image_metadata = {
        img["id"]: img for img in images_result.data
        if img.get("scan_job_id") in org_job_ids
    }

    updated_count = 0
    for match in matches_result.data:
        img_id = match.get("discovered_image_id")
        if not img_id or img_id not in image_metadata:
            continue

        img = image_metadata[img_id]
        metadata = img.get("metadata", {})
        advertiser_id = metadata.get("advertiser_id", "")

        distributor_id = (
            advertiser_to_distributor.get(advertiser_id.lower()) or
            advertiser_to_distributor.get(advertiser_id)
        )

        if distributor_id:
            supabase.table("matches").update({
                "distributor_id": distributor_id
            }).eq("id", match["id"]).execute()

            if not img.get("distributor_id"):
                supabase.table("discovered_images").update({
                    "distributor_id": distributor_id
                }).eq("id", img_id).execute()

            updated_count += 1
            log.info("Linked match %s to distributor %s (advertiser: %s)", match["id"], distributor_id, advertiser_id)

    return {
        "status": "success",
        "message": f"Linked {updated_count} matches to distributors",
        "updated": updated_count,
        "total_orphans": len(matches_result.data),
    }


# ============================================
# MATCH FEEDBACK (Adaptive Threshold Learning)
# ============================================


@router.post("/{match_id}/feedback", response_model=MatchFeedback, summary="Submit match feedback")
async def submit_match_feedback(
    match_id: UUID,
    feedback: MatchFeedbackCreate,
    user: AuthUser = Depends(get_current_user),
):
    """Submit feedback on whether a match was correct, scoped to the user's org."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    _verify_match_ownership(str(match_id), dist_ids)

    match_result = supabase.table("matches") \
        .select("id, confidence_score, match_type, channel, ai_analysis") \
        .eq("id", str(match_id)) \
        .single() \
        .execute()

    match_data = match_result.data
    ai_analysis = match_data.get("ai_analysis") or {}

    source_type = "unknown"
    if ai_analysis.get("comparison", {}).get("asset_found"):
        source_type = "page_screenshot"
    elif match_data.get("channel") == "website":
        source_type = "website_banner"
    elif match_data.get("channel") in ("google_ads", "facebook", "instagram"):
        source_type = "ad"

    insert_data = {
        "match_id": str(match_id),
        "was_correct": feedback.was_correct,
        "actual_verdict": feedback.actual_verdict.value,
        "ai_confidence": match_data.get("confidence_score"),
        "source_type": source_type,
        "channel": match_data.get("channel"),
        "match_type": match_data.get("match_type"),
        "review_notes": feedback.review_notes,
    }

    result = supabase.table("match_feedback").insert(insert_data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save feedback")

    invalidate_cache()

    log.info(
        "Feedback recorded for match %s: correct=%s, verdict=%s",
        match_id, feedback.was_correct, feedback.actual_verdict.value,
    )

    return result.data[0]


@router.get("/feedback/stats", response_model=List[FeedbackAccuracyStats], summary="Get feedback accuracy stats")
async def get_feedback_accuracy_stats(user: AuthUser = Depends(get_current_user)):
    """Get accuracy statistics scoped to the user's organization."""
    dist_ids = _org_distributor_ids(str(user.org_id))
    if not dist_ids:
        return []

    org_matches = supabase.table("matches") \
        .select("id") \
        .in_("distributor_id", dist_ids) \
        .execute()
    match_ids = [m["id"] for m in (org_matches.data or [])]
    if not match_ids:
        return []

    result = supabase.table("match_feedback") \
        .select("source_type, channel, match_type, was_correct, ai_confidence") \
        .in_("match_id", match_ids) \
        .execute()

    feedback = result.data or []
    if not feedback:
        return []

    groups: dict = {}
    for f in feedback:
        key = (f.get("source_type"), f.get("channel"))
        if key not in groups:
            groups[key] = {
                "source_type": key[0],
                "channel": key[1],
                "total_reviews": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "confidences": [],
                "correct_confidences": [],
                "incorrect_confidences": [],
            }
        g = groups[key]
        g["total_reviews"] += 1
        if f["was_correct"]:
            g["correct_count"] += 1
            if f.get("ai_confidence") is not None:
                g["correct_confidences"].append(f["ai_confidence"])
        else:
            g["incorrect_count"] += 1
            if f.get("ai_confidence") is not None:
                g["incorrect_confidences"].append(f["ai_confidence"])
        if f.get("ai_confidence") is not None:
            g["confidences"].append(f["ai_confidence"])

    stats = []
    for g in groups.values():
        total = g["total_reviews"]
        stats.append(FeedbackAccuracyStats(
            source_type=g["source_type"],
            channel=g["channel"],
            total_reviews=total,
            correct_count=g["correct_count"],
            incorrect_count=g["incorrect_count"],
            accuracy_percentage=round(g["correct_count"] / max(total, 1) * 100, 1),
            avg_confidence=round(sum(g["confidences"]) / len(g["confidences"]), 1) if g["confidences"] else None,
            avg_confidence_correct=round(sum(g["correct_confidences"]) / len(g["correct_confidences"]), 1) if g["correct_confidences"] else None,
            avg_confidence_incorrect=round(sum(g["incorrect_confidences"]) / len(g["incorrect_confidences"]), 1) if g["incorrect_confidences"] else None,
        ))

    return sorted(stats, key=lambda s: s.total_reviews, reverse=True)


@router.get("/feedback/thresholds", summary="Get threshold recommendations")
async def get_threshold_recommendations(user: AuthUser = Depends(get_current_user)):
    """Get adaptive threshold recommendations based on accumulated feedback."""
    thresholds = await get_all_adaptive_thresholds()
    return {
        "thresholds": thresholds,
        "total_combinations": len(thresholds),
    }
