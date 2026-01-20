"""
Adaptive Threshold Service for continuous AI improvement.

This service calculates optimal thresholds based on match feedback data,
enabling the system to learn and improve accuracy over time.
"""
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from ..database import supabase
from ..config import get_settings

settings = get_settings()

# Cache for adaptive thresholds (refreshed periodically)
_threshold_cache: Dict[str, Dict[str, Any]] = {}
_cache_expiry: Optional[datetime] = None
CACHE_DURATION_MINUTES = 30
MIN_SAMPLES_FOR_ADAPTATION = 20


async def get_adaptive_threshold(
    source_type: str,
    channel: str,
    use_cache: bool = True
) -> Tuple[int, Dict[str, Any]]:
    """
    Get the adaptive threshold for a source type and channel combination.
    
    Returns:
        Tuple of (threshold, metadata) where metadata includes:
        - sample_count: number of feedback samples used
        - confidence: 'high', 'medium', 'low'
        - false_positive_rate: percentage
        - false_negative_rate: percentage
        - using_default: whether falling back to default threshold
    """
    global _threshold_cache, _cache_expiry
    
    cache_key = f"{source_type}:{channel}"
    
    # Check cache
    if use_cache and _cache_expiry and datetime.utcnow() < _cache_expiry:
        if cache_key in _threshold_cache:
            cached = _threshold_cache[cache_key]
            return cached["threshold"], cached["metadata"]
    
    # Calculate adaptive threshold
    threshold, metadata = await _calculate_adaptive_threshold(source_type, channel)
    
    # Update cache
    _threshold_cache[cache_key] = {
        "threshold": threshold,
        "metadata": metadata
    }
    _cache_expiry = datetime.utcnow() + timedelta(minutes=CACHE_DURATION_MINUTES)
    
    return threshold, metadata


async def _calculate_adaptive_threshold(
    source_type: str,
    channel: str
) -> Tuple[int, Dict[str, Any]]:
    """
    Calculate the optimal threshold based on feedback data.
    
    Algorithm:
    1. Get all feedback for this source_type/channel
    2. Find the threshold that maximizes accuracy (correct matches)
    3. Adjust for false positive/negative balance
    4. Fall back to default if insufficient data
    """
    # Get feedback data
    result = supabase.table("match_feedback")\
        .select("ai_confidence, was_correct, actual_verdict")\
        .eq("source_type", source_type)\
        .eq("channel", channel)\
        .execute()
    
    feedback_data = result.data or []
    sample_count = len(feedback_data)
    
    # Default thresholds based on source type
    if source_type == "page_screenshot":
        default_threshold = settings.screenshot_match_threshold
    else:
        default_threshold = settings.regular_image_match_threshold
    
    # Not enough data - use defaults
    if sample_count < MIN_SAMPLES_FOR_ADAPTATION:
        return default_threshold, {
            "sample_count": sample_count,
            "confidence": "low",
            "false_positive_rate": 0,
            "false_negative_rate": 0,
            "using_default": True,
            "reason": f"Insufficient samples ({sample_count} < {MIN_SAMPLES_FOR_ADAPTATION})"
        }
    
    # Separate correct and incorrect predictions
    correct_confidences = [
        f["ai_confidence"] for f in feedback_data 
        if f["was_correct"] and f["ai_confidence"] is not None
    ]
    incorrect_confidences = [
        f["ai_confidence"] for f in feedback_data 
        if not f["was_correct"] and f["ai_confidence"] is not None
    ]
    
    # Calculate false positive/negative rates
    false_positives = len([f for f in feedback_data if f["actual_verdict"] == "false_positive"])
    false_negatives = len([f for f in feedback_data if f["actual_verdict"] == "false_negative"])
    
    fp_rate = (false_positives / sample_count * 100) if sample_count > 0 else 0
    fn_rate = (false_negatives / sample_count * 100) if sample_count > 0 else 0
    
    # Calculate optimal threshold
    if correct_confidences:
        avg_correct = sum(correct_confidences) / len(correct_confidences)
        std_correct = _calculate_std(correct_confidences)
        
        # Base threshold is mean - 0.5 * std of correct predictions
        # This captures most correct matches while filtering noise
        base_threshold = int(avg_correct - std_correct * 0.5)
    else:
        base_threshold = default_threshold
    
    # Adjust based on error rates
    # High false positives -> raise threshold
    # High false negatives -> lower threshold
    if fp_rate > 25:
        adjustment = 15
    elif fp_rate > 15:
        adjustment = 10
    elif fp_rate > 10:
        adjustment = 5
    else:
        adjustment = 0
    
    if fn_rate > 25:
        adjustment -= 15
    elif fn_rate > 15:
        adjustment -= 10
    elif fn_rate > 10:
        adjustment -= 5
    
    optimal_threshold = base_threshold + adjustment
    
    # Clamp to reasonable range
    optimal_threshold = max(15, min(85, optimal_threshold))
    
    # Determine confidence level
    if sample_count >= 100:
        confidence = "high"
    elif sample_count >= 50:
        confidence = "medium"
    else:
        confidence = "low"
    
    return optimal_threshold, {
        "sample_count": sample_count,
        "confidence": confidence,
        "false_positive_rate": round(fp_rate, 2),
        "false_negative_rate": round(fn_rate, 2),
        "using_default": False,
        "avg_correct_confidence": round(avg_correct, 2) if correct_confidences else None,
        "base_threshold": base_threshold,
        "adjustment": adjustment,
        "reason": f"Calculated from {sample_count} samples"
    }


def _calculate_std(values: list) -> float:
    """Calculate standard deviation."""
    if not values:
        return 0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


async def get_all_adaptive_thresholds() -> Dict[str, Dict[str, Any]]:
    """
    Get adaptive thresholds for all source_type/channel combinations.
    
    Returns dict mapping "source_type:channel" -> threshold info
    """
    # Get unique combinations with feedback
    result = supabase.table("match_feedback")\
        .select("source_type, channel")\
        .execute()
    
    if not result.data:
        return {}
    
    # Find unique combinations
    seen = set()
    combinations = []
    for row in result.data:
        key = (row.get("source_type"), row.get("channel"))
        if key not in seen and key[0] and key[1]:
            seen.add(key)
            combinations.append(key)
    
    # Calculate threshold for each
    thresholds = {}
    for source_type, channel in combinations:
        threshold, metadata = await get_adaptive_threshold(source_type, channel)
        thresholds[f"{source_type}:{channel}"] = {
            "threshold": threshold,
            **metadata
        }
    
    return thresholds


async def get_calibration_factor_from_feedback(
    source_type: str,
    channel: str
) -> float:
    """
    Calculate a calibration factor based on feedback data.
    
    This adjusts confidence scores based on historical accuracy.
    If predictions tend to be overconfident, factor < 1.0
    If predictions tend to be underconfident, factor > 1.0
    """
    result = supabase.table("match_feedback")\
        .select("ai_confidence, was_correct")\
        .eq("source_type", source_type)\
        .eq("channel", channel)\
        .execute()
    
    feedback_data = result.data or []
    
    if len(feedback_data) < MIN_SAMPLES_FOR_ADAPTATION:
        # Use default calibration from settings
        from ..config import get_calibration_factor
        return get_calibration_factor(source_type, channel)
    
    # Calculate average confidence for correct vs incorrect predictions
    correct_avg = 0
    correct_count = 0
    incorrect_avg = 0
    incorrect_count = 0
    
    for f in feedback_data:
        conf = f.get("ai_confidence")
        if conf is not None:
            if f["was_correct"]:
                correct_avg += conf
                correct_count += 1
            else:
                incorrect_avg += conf
                incorrect_count += 1
    
    if correct_count == 0:
        return 1.0
    
    correct_avg /= correct_count
    incorrect_avg = incorrect_avg / incorrect_count if incorrect_count > 0 else 0
    
    # If incorrect predictions have high confidence, we're overconfident
    # Reduce the calibration factor
    if incorrect_avg > 60:
        factor = 0.85
    elif incorrect_avg > 50:
        factor = 0.90
    elif incorrect_avg > 40:
        factor = 0.95
    else:
        factor = 1.0
    
    # If correct predictions have low confidence, we're underconfident
    # Increase the calibration factor
    if correct_avg < 50:
        factor *= 1.15
    elif correct_avg < 60:
        factor *= 1.10
    elif correct_avg < 70:
        factor *= 1.05
    
    return round(factor, 3)


def invalidate_cache():
    """Invalidate the threshold cache to force recalculation."""
    global _threshold_cache, _cache_expiry
    _threshold_cache = {}
    _cache_expiry = None


async def should_verify_match(
    confidence_score: int,
    source_type: str,
    channel: str
) -> bool:
    """
    Determine if a match should go through additional verification.
    
    Uses feedback data to identify score ranges with high uncertainty.
    """
    result = supabase.table("match_feedback")\
        .select("ai_confidence, was_correct")\
        .eq("source_type", source_type)\
        .eq("channel", channel)\
        .gte("ai_confidence", confidence_score - 10)\
        .lte("ai_confidence", confidence_score + 10)\
        .execute()
    
    feedback_data = result.data or []
    
    if len(feedback_data) < 10:
        # Not enough data, use default borderline range
        return settings.borderline_match_lower <= confidence_score <= settings.borderline_match_upper
    
    # Calculate accuracy in this confidence range
    correct = sum(1 for f in feedback_data if f["was_correct"])
    accuracy = correct / len(feedback_data)
    
    # Verify if accuracy is below 80%
    return accuracy < 0.8








