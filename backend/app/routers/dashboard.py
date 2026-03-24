"""Dashboard routes."""
from fastapi import APIRouter, Depends
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import DashboardStats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(user: AuthUser = Depends(get_current_user)):
    """Get dashboard statistics."""
    org_filter = str(user.org_id)
    today = datetime.utcnow().date().isoformat()

    campaigns_q = supabase.table("campaigns").select("id", count="exact").eq("status", "active")
    if org_filter:
        campaigns_q = campaigns_q.eq("organization_id", org_filter)
    campaigns = campaigns_q.execute()

    assets = supabase.table("assets").select("id", count="exact").execute()

    distributors_q = supabase.table("distributors").select("id", count="exact").eq("status", "active")
    if org_filter:
        distributors_q = distributors_q.eq("organization_id", org_filter)
    distributors = distributors_q.execute()

    matches = supabase.table("matches").select("id", count="exact").execute()

    alerts_q = supabase.table("alerts").select("id", count="exact").eq("is_read", False)
    if org_filter:
        alerts_q = alerts_q.eq("organization_id", org_filter)
    alerts = alerts_q.execute()

    compliant = supabase.table("matches").select("id", count="exact").eq("compliance_status", "compliant").execute()
    violations = supabase.table("matches").select("id", count="exact").eq("compliance_status", "violation").execute()
    matches_today = supabase.table("matches").select("id", count="exact").gte("created_at", today).execute()

    total_matches = matches.count or 0
    compliant_count = compliant.count or 0
    compliance_rate = (compliant_count / max(total_matches, 1)) * 100

    return DashboardStats(
        active_campaigns=campaigns.count or 0,
        total_assets=assets.count or 0,
        active_distributors=distributors.count or 0,
        total_matches=total_matches,
        unread_alerts=alerts.count or 0,
        compliance_rate=round(compliance_rate, 1),
        matches_today=matches_today.count or 0,
        violations_count=violations.count or 0
    )


@router.get("/recent-matches")
async def get_recent_matches(limit: int = 10):
    """Get recent matches for dashboard."""
    result = supabase.table("recent_matches")\
        .select("*")\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    return result.data


@router.get("/recent-alerts")
async def get_recent_alerts(limit: int = 10, unread_only: bool = True):
    """Get recent alerts for dashboard."""
    q = supabase.table("alerts")\
        .select("*, distributors(name), matches(confidence_score)")\
        .order("created_at", desc=True)\
        .limit(limit)
    if unread_only:
        q = q.eq("is_read", False)
    result = q.execute()
    return result.data


@router.get("/coverage-by-channel")
async def get_coverage_by_channel():
    """Get match coverage by channel."""
    result = supabase.table("matches").select("channel").execute()

    channel_counts = {}
    for match in result.data:
        channel = match.get("channel") or "unknown"
        channel_counts[channel] = channel_counts.get(channel, 0) + 1

    return [
        {"channel": k, "count": v}
        for k, v in sorted(channel_counts.items(), key=lambda x: -x[1])
    ]


@router.get("/coverage-by-distributor")
async def get_coverage_by_distributor(limit: int = 10):
    """Get match coverage by distributor."""
    result = supabase.table("matches").select("distributor_id, distributors(name)").execute()

    dist_counts = {}
    dist_names = {}
    for match in result.data:
        dist_id = match.get("distributor_id")
        if dist_id:
            dist_counts[dist_id] = dist_counts.get(dist_id, 0) + 1
            if match.get("distributors"):
                dist_names[dist_id] = match["distributors"]["name"]

    sorted_dists = sorted(dist_counts.items(), key=lambda x: -x[1])[:limit]

    return [
        {
            "distributor_id": k,
            "distributor_name": dist_names.get(k, "Unknown"),
            "match_count": v
        }
        for k, v in sorted_dists
    ]


@router.get("/compliance-trend")
async def get_compliance_trend(days: int = 30):
    """Get compliance trend over time."""
    start_date = (datetime.utcnow() - timedelta(days=days)).isoformat()

    result = supabase.table("matches")\
        .select("created_at, compliance_status")\
        .gte("created_at", start_date)\
        .order("created_at")\
        .execute()

    daily_stats = {}
    for match in result.data:
        date = match["created_at"][:10]
        if date not in daily_stats:
            daily_stats[date] = {"total": 0, "compliant": 0, "violations": 0}

        daily_stats[date]["total"] += 1
        if match["compliance_status"] == "compliant":
            daily_stats[date]["compliant"] += 1
        elif match["compliance_status"] == "violation":
            daily_stats[date]["violations"] += 1

    return [
        {"date": k, **v}
        for k, v in sorted(daily_stats.items())
    ]
