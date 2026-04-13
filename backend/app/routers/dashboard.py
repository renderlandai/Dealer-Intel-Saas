"""Dashboard routes — all queries scoped to the authenticated user's organization."""
import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Optional, Tuple
from uuid import UUID
from datetime import datetime, timedelta
from cachetools import TTLCache

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import DashboardStats
from ..org_cache import get_org_distributor_ids, get_org_campaign_ids
from ..plan_enforcement import OrgPlan, get_org_plan

log = logging.getLogger("dealer_intel.dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_stats_cache: TTLCache = TTLCache(maxsize=200, ttl=15)


@router.get("/stats", response_model=DashboardStats, summary="Get dashboard stats")
async def get_dashboard_stats(user: AuthUser = Depends(get_current_user)):
    """Get dashboard statistics via single Postgres RPC (falls back to sequential queries)."""
    org_id = str(user.org_id)

    if org_id in _stats_cache:
        return _stats_cache[org_id]

    try:
        result = supabase.rpc("get_dashboard_stats", {"p_org_id": org_id}).execute()
        if result.data:
            d = result.data
            stats = DashboardStats(
                active_campaigns=d.get("active_campaigns", 0),
                total_assets=d.get("total_assets", 0),
                active_distributors=d.get("active_distributors", 0),
                total_matches=d.get("total_matches", 0),
                unread_alerts=d.get("unread_alerts", 0),
                compliance_rate=float(d.get("compliance_rate", 0)),
                matches_today=d.get("matches_today", 0),
                violations_count=d.get("violations_count", 0),
            )
            _stats_cache[org_id] = stats
            return stats
    except Exception as rpc_err:
        log.debug("Dashboard RPC unavailable, falling back to sequential queries: %s", rpc_err)

    stats = await _get_dashboard_stats_fallback(org_id)
    _stats_cache[org_id] = stats
    return stats


async def _get_dashboard_stats_fallback(org_id: str) -> DashboardStats:
    """Legacy sequential queries — used when the RPC hasn't been deployed yet."""
    today = datetime.utcnow().date().isoformat()

    distributor_ids = get_org_distributor_ids(org_id)
    campaign_ids = get_org_campaign_ids(org_id)

    campaigns = supabase.table("campaigns") \
        .select("id", count="exact") \
        .eq("organization_id", org_id) \
        .eq("status", "active").execute()

    if campaign_ids:
        assets = supabase.table("assets") \
            .select("id", count="exact") \
            .in_("campaign_id", campaign_ids).execute()
        assets_count = assets.count or 0
    else:
        assets_count = 0

    distributors = supabase.table("distributors") \
        .select("id", count="exact") \
        .eq("organization_id", org_id) \
        .eq("status", "active").execute()

    alerts = supabase.table("alerts") \
        .select("id", count="exact") \
        .eq("organization_id", org_id) \
        .eq("is_read", False).execute()

    if distributor_ids:
        matches = supabase.table("matches") \
            .select("id", count="exact") \
            .in_("distributor_id", distributor_ids).execute()
        compliant = supabase.table("matches") \
            .select("id", count="exact") \
            .in_("distributor_id", distributor_ids) \
            .eq("compliance_status", "compliant").execute()
        violations = supabase.table("matches") \
            .select("id", count="exact") \
            .in_("distributor_id", distributor_ids) \
            .eq("compliance_status", "violation").execute()
        matches_today = supabase.table("matches") \
            .select("id", count="exact") \
            .in_("distributor_id", distributor_ids) \
            .gte("created_at", today).execute()

        total_matches = matches.count or 0
        compliant_count = compliant.count or 0
        violations_count = violations.count or 0
        today_count = matches_today.count or 0
    else:
        total_matches = compliant_count = violations_count = today_count = 0

    compliance_rate = (compliant_count / max(total_matches, 1)) * 100

    return DashboardStats(
        active_campaigns=campaigns.count or 0,
        total_assets=assets_count,
        active_distributors=distributors.count or 0,
        total_matches=total_matches,
        unread_alerts=alerts.count or 0,
        compliance_rate=round(compliance_rate, 1),
        matches_today=today_count,
        violations_count=violations_count,
    )


@router.get("/recent-matches", summary="Get recent matches")
async def get_recent_matches(
    limit: int = 10,
    user: AuthUser = Depends(get_current_user),
):
    """Get recent matches scoped to the user's organization."""
    distributor_ids = get_org_distributor_ids(str(user.org_id))
    if not distributor_ids:
        return []

    result = supabase.table("recent_matches") \
        .select("*") \
        .in_("distributor_id", distributor_ids) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return result.data


@router.get("/recent-alerts", summary="Get recent alerts")
async def get_recent_alerts(
    limit: int = 10,
    unread_only: bool = True,
    user: AuthUser = Depends(get_current_user),
):
    """Get recent alerts scoped to the user's organization."""
    q = supabase.table("alerts") \
        .select("*, distributors(name), matches(confidence_score)") \
        .eq("organization_id", str(user.org_id)) \
        .order("created_at", desc=True) \
        .limit(limit)
    if unread_only:
        q = q.eq("is_read", False)
    result = q.execute()
    return result.data


@router.get("/coverage-by-channel", summary="Get coverage by channel")
async def get_coverage_by_channel(user: AuthUser = Depends(get_current_user)):
    """Get match coverage by channel scoped to the user's organization."""
    distributor_ids = get_org_distributor_ids(str(user.org_id))
    if not distributor_ids:
        return []

    result = supabase.table("matches") \
        .select("channel") \
        .in_("distributor_id", distributor_ids) \
        .execute()

    channel_counts: dict = {}
    for match in result.data:
        channel = match.get("channel") or "unknown"
        channel_counts[channel] = channel_counts.get(channel, 0) + 1

    return [
        {"channel": k, "count": v}
        for k, v in sorted(channel_counts.items(), key=lambda x: -x[1])
    ]


@router.get("/coverage-by-distributor", summary="Get coverage by distributor")
async def get_coverage_by_distributor(
    limit: int = 10,
    user: AuthUser = Depends(get_current_user),
):
    """Get match coverage by distributor scoped to the user's organization."""
    distributor_ids = get_org_distributor_ids(str(user.org_id))
    if not distributor_ids:
        return []

    result = supabase.table("matches") \
        .select("distributor_id, distributors(name)") \
        .in_("distributor_id", distributor_ids) \
        .execute()

    dist_counts: dict = {}
    dist_names: dict = {}
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
            "match_count": v,
        }
        for k, v in sorted_dists
    ]


@router.get("/compliance-trend", summary="Get compliance trend")
async def get_compliance_trend(
    days: int = 30,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Get compliance trend over time scoped to the user's organization."""
    if not op.limits.get("compliance_trends"):
        raise HTTPException(
            403,
            f"Compliance trend analytics are not available on your {op.plan} plan. "
            "Upgrade to Pro to unlock this feature.",
        )
    distributor_ids = get_org_distributor_ids(str(user.org_id))
    if not distributor_ids:
        return []

    start_date = (datetime.utcnow() - timedelta(days=days)).isoformat()

    result = supabase.table("matches") \
        .select("created_at, compliance_status") \
        .in_("distributor_id", distributor_ids) \
        .gte("created_at", start_date) \
        .order("created_at") \
        .execute()

    daily_stats: dict = {}
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
