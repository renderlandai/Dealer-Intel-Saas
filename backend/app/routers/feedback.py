"""
Match feedback routes for continuous AI improvement.

This module provides endpoints for:
- Submitting feedback on match accuracy
- Retrieving accuracy statistics
- Getting threshold recommendations based on feedback data
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import List, Optional
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import (
    MatchFeedback, 
    MatchFeedbackCreate, 
    FeedbackAccuracyStats,
    ThresholdRecommendation,
    AnalysisSettingsResponse
)
from ..config import get_settings
from ..services import adaptive_threshold_service

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/feedback", tags=["feedback"])

settings = get_settings()


@router.get("/adaptive-thresholds", summary="Get adaptive thresholds")
async def get_adaptive_thresholds(user: AuthUser = Depends(get_current_user)):
    """
    Get all adaptive thresholds calculated from feedback data.
    
    These thresholds are automatically tuned based on user feedback
    to optimize accuracy for each source type and channel combination.
    """
    thresholds = await adaptive_threshold_service.get_all_adaptive_thresholds()
    
    return {
        "thresholds": thresholds,
        "min_samples_required": adaptive_threshold_service.MIN_SAMPLES_FOR_ADAPTATION,
        "cache_duration_minutes": adaptive_threshold_service.CACHE_DURATION_MINUTES
    }


@router.post("/invalidate-cache", summary="Invalidate threshold cache")
@limiter.limit("5/minute")
async def invalidate_threshold_cache(request: Request, user: AuthUser = Depends(get_current_user)):
    """
    Invalidate the adaptive threshold cache.
    
    Call this after bulk feedback submission to force recalculation.
    """
    adaptive_threshold_service.invalidate_cache()
    return {"status": "cache_invalidated"}


@router.post("", response_model=MatchFeedback, summary="Submit match feedback")
@limiter.limit("30/minute")
async def submit_feedback(request: Request, feedback: MatchFeedbackCreate, user: AuthUser = Depends(get_current_user)):
    """
    Submit feedback on a match's accuracy.
    
    This feedback is used to:
    1. Track AI accuracy over time
    2. Calculate optimal thresholds for different source types/channels
    3. Improve confidence calibration
    """
    # Get the match to extract metadata
    match_result = supabase.table("matches")\
        .select("*, discovered_images!inner(source_type, channel)")\
        .eq("id", str(feedback.match_id))\
        .single()\
        .execute()
    
    if not match_result.data:
        raise HTTPException(status_code=404, detail="Match not found")
    
    match_data = match_result.data
    discovered_image = match_data.get("discovered_images", {})
    
    # Create feedback record
    feedback_data = {
        "match_id": str(feedback.match_id),
        "was_correct": feedback.was_correct,
        "actual_verdict": feedback.actual_verdict.value,
        "ai_confidence": match_data.get("confidence_score"),
        "source_type": discovered_image.get("source_type"),
        "channel": discovered_image.get("channel") or match_data.get("channel"),
        "match_type": match_data.get("match_type"),
        "review_notes": feedback.review_notes
    }
    
    result = supabase.table("match_feedback").insert(feedback_data).execute()
    
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save feedback")
    
    feedback_record = result.data[0]
    
    # Update match with feedback status
    supabase.table("matches").update({
        "feedback_status": "reviewed",
        "feedback_id": feedback_record["id"]
    }).eq("id", str(feedback.match_id)).execute()
    
    return feedback_record


@router.get("/stats", response_model=List[FeedbackAccuracyStats], summary="Get accuracy statistics")
async def get_accuracy_stats(
    source_type: Optional[str] = None,
    channel: Optional[str] = None,
    user: AuthUser = Depends(get_current_user),
):
    """
    Get accuracy statistics aggregated by source type, channel, and match type.
    
    Use this to identify:
    - Which source types have low accuracy (may need threshold adjustment)
    - Which channels produce more false positives
    - Overall AI performance trends
    """
    query = supabase.table("feedback_accuracy_stats").select("*")
    
    if source_type:
        query = query.eq("source_type", source_type)
    if channel:
        query = query.eq("channel", channel)
    
    result = query.execute()
    
    return result.data or []


@router.get("/threshold-recommendations", response_model=List[ThresholdRecommendation], summary="Get threshold recommendations")
async def get_threshold_recommendations(user: AuthUser = Depends(get_current_user)):
    """
    Get recommended thresholds based on feedback data.
    
    Returns recommendations for each source_type/channel combination
    that has sufficient feedback data (minimum 20 samples).
    """
    # Get unique source_type/channel combinations with feedback
    combinations_result = supabase.table("match_feedback")\
        .select("source_type, channel")\
        .execute()
    
    if not combinations_result.data:
        return []
    
    # Get unique combinations
    seen = set()
    combinations = []
    for row in combinations_result.data:
        key = (row.get("source_type"), row.get("channel"))
        if key not in seen and key[0] and key[1]:
            seen.add(key)
            combinations.append(key)
    
    recommendations = []
    
    for source_type, channel in combinations:
        # Get feedback data for this combination
        feedback_result = supabase.table("match_feedback")\
            .select("ai_confidence, was_correct, actual_verdict")\
            .eq("source_type", source_type)\
            .eq("channel", channel)\
            .execute()
        
        feedback_data = feedback_result.data or []
        sample_count = len(feedback_data)
        
        if sample_count < 10:
            continue
        
        # Calculate statistics
        correct_confidences = [f["ai_confidence"] for f in feedback_data if f["was_correct"] and f["ai_confidence"]]
        incorrect_confidences = [f["ai_confidence"] for f in feedback_data if not f["was_correct"] and f["ai_confidence"]]
        
        false_positives = len([f for f in feedback_data if f["actual_verdict"] == "false_positive"])
        false_negatives = len([f for f in feedback_data if f["actual_verdict"] == "false_negative"])
        
        # Calculate recommended threshold
        if correct_confidences:
            avg_correct = sum(correct_confidences) / len(correct_confidences)
            std_correct = (sum((x - avg_correct) ** 2 for x in correct_confidences) / len(correct_confidences)) ** 0.5
            recommended = int(avg_correct - std_correct * 0.5)
        else:
            recommended = settings.regular_image_match_threshold
        
        # Adjust based on false positive rate
        fp_rate = (false_positives / sample_count * 100) if sample_count > 0 else 0
        fn_rate = (false_negatives / sample_count * 100) if sample_count > 0 else 0
        
        if fp_rate > 20:
            recommended = min(100, recommended + 10)  # Raise threshold
        elif fn_rate > 20:
            recommended = max(10, recommended - 10)  # Lower threshold
        
        # Get current threshold
        if source_type == "page_screenshot":
            current = settings.screenshot_match_threshold
        else:
            current = settings.regular_image_match_threshold
        
        # Determine confidence level
        if sample_count >= 100:
            confidence = "high"
        elif sample_count >= 50:
            confidence = "medium"
        else:
            confidence = "low"
        
        recommendations.append(ThresholdRecommendation(
            source_type=source_type,
            channel=channel,
            current_threshold=current,
            recommended_threshold=recommended,
            sample_count=sample_count,
            false_positive_rate=round(fp_rate, 2),
            false_negative_rate=round(fn_rate, 2),
            confidence=confidence
        ))
    
    return recommendations


@router.get("/pending-reviews", summary="Get pending reviews")
async def get_pending_reviews(limit: int = 50, user: AuthUser = Depends(get_current_user)):
    """
    Get matches that haven't been reviewed yet.
    
    Prioritizes:
    1. Borderline confidence scores (30-60 range)
    2. Recent matches
    3. Matches with modifications detected
    """
    org_distributors = supabase.table("distributors")\
        .select("id")\
        .eq("organization_id", str(user.org_id))\
        .execute()
    dist_ids = [d["id"] for d in (org_distributors.data or [])]
    if not dist_ids:
        return []

    result = supabase.table("matches")\
        .select("*, assets(name, file_url), distributors(name)")\
        .eq("feedback_status", "pending")\
        .in_("distributor_id", dist_ids)\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    
    matches = result.data or []
    
    # Sort to prioritize borderline scores
    def priority_score(match):
        confidence = match.get("confidence_score", 50)
        # Borderline scores (30-60) get highest priority
        if settings.borderline_match_lower <= confidence <= settings.borderline_match_upper:
            return 0
        # Modified matches next
        if match.get("is_modified"):
            return 1
        return 2
    
    matches.sort(key=priority_score)
    
    return matches


@router.get("/settings", response_model=AnalysisSettingsResponse, summary="Get analysis settings")
async def get_analysis_settings(user: AuthUser = Depends(get_current_user)):
    """
    Get current AI analysis threshold settings.
    
    Use this to understand current configuration and compare
    with recommendations.
    """
    return AnalysisSettingsResponse(
        exact_match_threshold=settings.exact_match_threshold,
        strong_match_threshold=settings.strong_match_threshold,
        partial_match_threshold=settings.partial_match_threshold,
        weak_match_threshold=settings.weak_match_threshold,
        regular_image_match_threshold=settings.regular_image_match_threshold,
        screenshot_match_threshold=settings.screenshot_match_threshold,
        filter_relevance_threshold=settings.filter_relevance_threshold,
        borderline_match_lower=settings.borderline_match_lower,
        borderline_match_upper=settings.borderline_match_upper,
        calibration_factors={
            "page_screenshot": settings.calibration_page_screenshot,
            "website_banner": settings.calibration_website_banner,
            "ad": settings.calibration_ad,
            "organic_post": settings.calibration_organic_post,
            "google_ads": settings.calibration_google_ads,
            "facebook": settings.calibration_facebook,
            "website": settings.calibration_website,
        },
        ensemble_weights={
            "visual": settings.ensemble_visual_weight,
            "detection": settings.ensemble_detection_weight,
            "hash": settings.ensemble_hash_weight,
            "agreement_bonus": settings.ensemble_agreement_bonus,
        }
    )


@router.get("/accuracy-trend", summary="Get accuracy trend")
async def get_accuracy_trend(days: int = 30, user: AuthUser = Depends(get_current_user)):
    """
    Get accuracy trend over time.
    
    Shows how AI accuracy has changed day-by-day.
    """
    from datetime import datetime, timedelta
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    result = supabase.table("match_feedback")\
        .select("created_at, was_correct, actual_verdict")\
        .gte("created_at", start_date.isoformat())\
        .order("created_at")\
        .execute()
    
    feedback_data = result.data or []
    
    # Group by date
    daily_stats = {}
    for feedback in feedback_data:
        date_str = feedback["created_at"][:10]  # Extract YYYY-MM-DD
        if date_str not in daily_stats:
            daily_stats[date_str] = {"total": 0, "correct": 0, "false_positives": 0, "false_negatives": 0}
        
        daily_stats[date_str]["total"] += 1
        if feedback["was_correct"]:
            daily_stats[date_str]["correct"] += 1
        if feedback["actual_verdict"] == "false_positive":
            daily_stats[date_str]["false_positives"] += 1
        if feedback["actual_verdict"] == "false_negative":
            daily_stats[date_str]["false_negatives"] += 1
    
    # Convert to list with accuracy percentages
    trend = []
    for date_str in sorted(daily_stats.keys()):
        stats = daily_stats[date_str]
        accuracy = (stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
        trend.append({
            "date": date_str,
            "total_reviews": stats["total"],
            "correct": stats["correct"],
            "accuracy_percentage": round(accuracy, 2),
            "false_positives": stats["false_positives"],
            "false_negatives": stats["false_negatives"]
        })
    
    return {
        "period_days": days,
        "total_feedback": len(feedback_data),
        "overall_accuracy": round(
            (sum(1 for f in feedback_data if f["was_correct"]) / len(feedback_data) * 100)
            if feedback_data else 0, 2
        ),
        "trend": trend
    }

