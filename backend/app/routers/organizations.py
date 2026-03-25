"""Organization routes — settings and logo management."""
import base64
import logging
import time
import uuid as uuid_lib
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..auth import AuthUser, get_current_user

limiter = Limiter(key_func=get_remote_address)
from ..database import supabase
from ..plan_enforcement import (
    OrgPlan, get_org_plan,
    check_report_branding, check_email_notifications,
)

log = logging.getLogger("dealer_intel.organizations")

router = APIRouter(prefix="/organizations", tags=["organizations"])

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB


class OrgSettingsUpdate(BaseModel):
    name: Optional[str] = None
    report_brand_color: Optional[str] = None
    notify_email: Optional[str] = None
    notify_on_violation: Optional[bool] = None


_SETTINGS_COLS = "id, name, slug, logo_url, report_brand_color, notify_email, notify_on_violation"
_SETTINGS_COLS_FALLBACK = "id, name, slug"


def _assert_own_org(org_id: UUID, user: AuthUser) -> None:
    """Verify the authenticated user belongs to the requested organization."""
    if str(org_id) != str(user.org_id):
        raise HTTPException(status_code=403, detail="Access denied")


@router.get("/{org_id}/settings")
async def get_org_settings(org_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get organization settings."""
    _assert_own_org(org_id, user)
    try:
        result = supabase.table("organizations")\
            .select(_SETTINGS_COLS)\
            .eq("id", str(org_id))\
            .single()\
            .execute()
    except Exception:
        result = supabase.table("organizations")\
            .select(_SETTINGS_COLS_FALLBACK)\
            .eq("id", str(org_id))\
            .single()\
            .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Organization not found")

    d = result.data
    return {
        "organization_id": str(org_id),
        "name": d.get("name"),
        "slug": d.get("slug"),
        "logo_url": d.get("logo_url"),
        "report_brand_color": d.get("report_brand_color"),
        "notify_email": d.get("notify_email"),
        "notify_on_violation": d.get("notify_on_violation", True),
    }


@router.patch("/{org_id}/settings")
async def update_org_settings(
    org_id: UUID,
    updates: OrgSettingsUpdate,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Update organization settings."""
    _assert_own_org(org_id, user)
    data = updates.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "report_brand_color" in data:
        check_report_branding(op)
    if "notify_email" in data or "notify_on_violation" in data:
        check_email_notifications(op)

    result = supabase.table("organizations")\
        .update(data)\
        .eq("id", str(org_id))\
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Organization not found")

    log.info("Org %s settings updated: %s", org_id, list(data.keys()))
    return {"organization_id": str(org_id), "status": "updated"}


@router.post("/{org_id}/test-email")
@limiter.limit("5/minute")
async def test_email(
    request: Request,
    org_id: UUID,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Send a test email to verify notifications are working."""
    _assert_own_org(org_id, user)
    check_email_notifications(op)
    from ..services.notification_service import send_test_email

    result = send_test_email(org_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/{org_id}/logo")
async def get_org_logo(org_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get the current logo URL for an organization."""
    _assert_own_org(org_id, user)
    try:
        result = supabase.table("organizations")\
            .select("id, name, logo_url")\
            .eq("id", str(org_id))\
            .single()\
            .execute()
    except Exception:
        result = supabase.table("organizations")\
            .select("id, name")\
            .eq("id", str(org_id))\
            .single()\
            .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Organization not found")

    return {
        "organization_id": str(org_id),
        "logo_url": result.data.get("logo_url"),
    }


@router.post("/{org_id}/logo")
async def upload_org_logo(
    org_id: UUID,
    file: UploadFile = File(...),
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """
    Upload or replace the organization logo used in PDF reports.
    Accepts PNG, JPEG, or WebP up to 2 MB.
    """
    _assert_own_org(org_id, user)
    check_report_branding(op)

    org_result = supabase.table("organizations")\
        .select("id")\
        .eq("id", str(org_id))\
        .single()\
        .execute()
    if not org_result.data:
        raise HTTPException(status_code=404, detail="Organization not found")

    if file.content_type and file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{file.content_type}' not allowed. Accepted: PNG, JPEG, WebP.",
        )

    content = await file.read()

    if len(content) > MAX_LOGO_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Maximum is 2 MB.",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    timestamp = int(time.time() * 1000)
    random_id = uuid_lib.uuid4().hex[:8]
    ext = (file.filename or "logo.png").rsplit(".", 1)[-1]
    storage_path = f"logos/{org_id}/{timestamp}_{random_id}.{ext}"

    logo_url = None
    try:
        bucket = supabase.storage.from_("org-logos")
        bucket.upload(
            path=storage_path,
            file=content,
            file_options={"contentType": file.content_type, "upsert": "true"},
        )
        logo_url = bucket.get_public_url(storage_path)
    except Exception as storage_err:
        log.warning("Supabase Storage upload failed, using base64 fallback: %s", storage_err)
        b64 = base64.b64encode(content).decode("utf-8")
        logo_url = f"data:{file.content_type};base64,{b64}"

    supabase.table("organizations")\
        .update({"logo_url": logo_url})\
        .eq("id", str(org_id))\
        .execute()

    log.info("Logo updated for org %s → %s", org_id, storage_path)

    return {
        "organization_id": str(org_id),
        "logo_url": logo_url,
        "status": "uploaded",
    }


@router.delete("/{org_id}/logo")
async def delete_org_logo(org_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Remove the organization logo — reports will fall back to the default."""
    _assert_own_org(org_id, user)
    supabase.table("organizations")\
        .update({"logo_url": None})\
        .eq("id", str(org_id))\
        .execute()

    return {
        "organization_id": str(org_id),
        "logo_url": None,
        "status": "deleted",
    }
