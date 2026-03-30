"""CRUD endpoints for scan schedules."""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..services import scheduler_service
from ..plan_enforcement import (
    OrgPlan, get_org_plan,
    check_frequency_allowed, check_schedule_limit, check_channel_allowed,
)

log = logging.getLogger("dealer_intel.schedules")
limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/schedules", tags=["schedules"])


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------
class ScheduleCreate(BaseModel):
    campaign_id: UUID
    source: str
    frequency: str        # daily | weekly | biweekly | monthly
    run_at_time: str = "09:00"   # HH:MM (24-hour, UTC)
    run_on_day: Optional[int] = None  # 0=Mon .. 6=Sun


class ScheduleUpdate(BaseModel):
    frequency: Optional[str] = None
    is_active: Optional[bool] = None
    run_at_time: Optional[str] = None
    run_on_day: Optional[int] = None


class ScheduleOut(BaseModel):
    id: UUID
    organization_id: UUID
    campaign_id: UUID
    source: str
    frequency: str
    run_at_time: Optional[str] = "09:00"
    run_on_day: Optional[int] = None
    is_active: bool
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
VALID_SOURCES = {"google_ads", "facebook", "instagram", "website"}
VALID_FREQS = {"daily", "weekly", "biweekly", "monthly"}


def _validate_time(t: str) -> None:
    parts = t.split(":")
    if len(parts) != 2:
        raise HTTPException(400, "run_at_time must be HH:MM format")
    try:
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError()
    except ValueError:
        raise HTTPException(400, "run_at_time must be valid HH:MM (00:00 – 23:59)")


@router.get("", response_model=List[ScheduleOut], summary="List scan schedules")
async def list_schedules(campaign_id: Optional[UUID] = None, user: AuthUser = Depends(get_current_user)):
    """List all scan schedules for the current organization."""
    try:
        query = supabase.table("scan_schedules").select("*").eq("organization_id", str(user.org_id)).order("created_at", desc=True)
        if campaign_id:
            query = query.eq("campaign_id", str(campaign_id))
        result = query.execute()
        return result.data or []
    except Exception as exc:
        if "PGRST205" in str(exc) or "scan_schedules" in str(exc):
            return []
        raise


@router.post("", response_model=ScheduleOut, status_code=201, summary="Create scan schedule")
@limiter.limit("10/minute")
async def create_schedule(request: Request, body: ScheduleCreate, user: AuthUser = Depends(get_current_user), op: OrgPlan = Depends(get_org_plan)):
    """Create a new scan schedule for a campaign."""
    if body.source not in VALID_SOURCES:
        raise HTTPException(400, f"source must be one of {VALID_SOURCES}")
    if body.frequency not in VALID_FREQS:
        raise HTTPException(400, f"frequency must be one of {VALID_FREQS}")
    _validate_time(body.run_at_time)
    if body.run_on_day is not None and not (0 <= body.run_on_day <= 6):
        raise HTTPException(400, "run_on_day must be 0 (Mon) – 6 (Sun)")

    check_channel_allowed(op, body.source)
    check_frequency_allowed(op, body.frequency)
    check_schedule_limit(op, str(body.campaign_id))

    campaign = (
        supabase.table("campaigns")
        .select("organization_id")
        .eq("id", str(body.campaign_id))
        .eq("organization_id", str(user.org_id))
        .single()
        .execute()
    )
    if not campaign.data:
        raise HTTPException(404, "Campaign not found")

    org_id = str(user.org_id)
    next_run = scheduler_service.compute_next_run(body.frequency, body.run_at_time, body.run_on_day)

    row = {
        "organization_id": org_id,
        "campaign_id": str(body.campaign_id),
        "source": body.source,
        "frequency": body.frequency,
        "run_at_time": body.run_at_time,
        "run_on_day": body.run_on_day,
        "is_active": True,
        "next_run_at": next_run.isoformat(),
    }

    try:
        result = supabase.table("scan_schedules").insert(row).execute()
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(409, "A schedule already exists for this campaign + source")
        raise

    created = result.data[0]
    scheduler_service.upsert_job(created)
    log.info("Schedule created: %s (%s / %s at %s)", created["id"], body.source, body.frequency, body.run_at_time)
    return created


@router.patch("/{schedule_id}", response_model=ScheduleOut, summary="Update scan schedule")
@limiter.limit("20/minute")
async def update_schedule(request: Request, schedule_id: UUID, body: ScheduleUpdate, user: AuthUser = Depends(get_current_user)):
    """Update an existing scan schedule."""
    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if body.frequency is not None:
        if body.frequency not in VALID_FREQS:
            raise HTTPException(400, f"frequency must be one of {VALID_FREQS}")
        updates["frequency"] = body.frequency

    if body.run_at_time is not None:
        _validate_time(body.run_at_time)
        updates["run_at_time"] = body.run_at_time

    if body.run_on_day is not None:
        if not (0 <= body.run_on_day <= 6):
            raise HTTPException(400, "run_on_day must be 0 (Mon) – 6 (Sun)")
        updates["run_on_day"] = body.run_on_day

    if body.is_active is not None:
        updates["is_active"] = body.is_active

    # Recompute next_run_at if timing changed
    if any(k in updates for k in ("frequency", "run_at_time", "run_on_day")):
        existing = supabase.table("scan_schedules").select("*").eq("id", str(schedule_id)).eq("organization_id", str(user.org_id)).single().execute()
        if not existing.data:
            raise HTTPException(404, "Schedule not found")
        merged = {**existing.data, **updates}
        updates["next_run_at"] = scheduler_service.compute_next_run(
            merged["frequency"],
            merged.get("run_at_time") or "09:00",
            merged.get("run_on_day"),
        ).isoformat()

    result = (
        supabase.table("scan_schedules")
        .update(updates)
        .eq("id", str(schedule_id))
        .eq("organization_id", str(user.org_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Schedule not found")

    updated = result.data[0]
    scheduler_service.upsert_job(updated)
    return updated


@router.delete("/{schedule_id}", status_code=204, summary="Delete scan schedule")
@limiter.limit("10/minute")
async def delete_schedule(request: Request, schedule_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Delete a scan schedule."""
    scheduler_service.remove_job(str(schedule_id))
    result = (
        supabase.table("scan_schedules")
        .delete()
        .eq("id", str(schedule_id))
        .eq("organization_id", str(user.org_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(404, "Schedule not found")
    return None
