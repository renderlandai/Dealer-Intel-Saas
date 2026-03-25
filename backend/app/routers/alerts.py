"""Alert routes — all queries scoped to the authenticated user's organization."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase

log = logging.getLogger("dealer_intel.alerts")

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    user: AuthUser = Depends(get_current_user),
):
    """List alerts for the user's organization."""
    q = supabase.table("alerts") \
        .select("*, distributors(name), matches(confidence_score)") \
        .eq("organization_id", str(user.org_id)) \
        .order("created_at", desc=True)

    if unread_only:
        q = q.eq("is_read", False)

    result = q.range(offset, offset + limit - 1).execute()
    return result.data


@router.get("/count")
async def get_unread_count(user: AuthUser = Depends(get_current_user)):
    """Return the unread alert count for the user's organization."""
    result = supabase.table("alerts") \
        .select("id", count="exact") \
        .eq("organization_id", str(user.org_id)) \
        .eq("is_read", False) \
        .execute()

    return {"unread_count": result.count or 0}


@router.patch("/{alert_id}/read")
async def mark_alert_read(
    alert_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """Mark a single alert as read."""
    result = supabase.table("alerts") \
        .update({"is_read": True}) \
        .eq("id", str(alert_id)) \
        .eq("organization_id", str(user.org_id)) \
        .execute()

    if not result.data:
        raise HTTPException(404, "Alert not found")

    return {"status": "read", "alert_id": str(alert_id)}


@router.post("/mark-all-read")
async def mark_all_read(user: AuthUser = Depends(get_current_user)):
    """Mark all alerts as read for the user's organization."""
    result = supabase.table("alerts") \
        .update({"is_read": True}) \
        .eq("organization_id", str(user.org_id)) \
        .eq("is_read", False) \
        .execute()

    count = len(result.data) if result.data else 0
    return {"status": "ok", "marked_read": count}


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """Delete a single alert."""
    result = supabase.table("alerts") \
        .delete() \
        .eq("id", str(alert_id)) \
        .eq("organization_id", str(user.org_id)) \
        .execute()

    if not result.data:
        raise HTTPException(404, "Alert not found")

    return {"status": "deleted", "alert_id": str(alert_id)}
