"""Team management — list members, invite users, remove members."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..auth import AuthUser, get_current_user, clear_profile_cache

limiter = Limiter(key_func=get_remote_address)
from ..config import get_plan_limits
from ..database import supabase

log = logging.getLogger("dealer_intel.team")

router = APIRouter(prefix="/team", tags=["team"])


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class MemberOut(BaseModel):
    user_id: str
    email: str
    role: str
    created_at: Optional[str] = None


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    expires_at: str
    created_at: Optional[str] = None


def _require_admin(user: AuthUser) -> None:
    if user.role not in ("owner", "admin"):
        raise HTTPException(403, "Only org owners and admins can manage the team")


@router.get("/members")
async def list_members(user: AuthUser = Depends(get_current_user)):
    """List all members of the current organization."""
    profiles = supabase.table("user_profiles") \
        .select("user_id, role, created_at") \
        .eq("organization_id", str(user.org_id)) \
        .order("created_at") \
        .execute()

    members = []
    for p in profiles.data or []:
        # Resolve email from Supabase Auth admin API or fall back
        members.append({
            "user_id": p["user_id"],
            "email": "",
            "role": p["role"],
            "created_at": p.get("created_at"),
        })

    # Batch-resolve emails from auth.users via service role
    user_ids = [m["user_id"] for m in members]
    if user_ids:
        try:
            auth_users = supabase.table("user_profiles") \
                .select("user_id") \
                .in_("user_id", user_ids) \
                .execute()
            # Use the JWT email from Supabase auth — we can fetch from the
            # auth.users table if service role is available, otherwise we
            # store the email during auto-provision. For now, query via RPC
            # or simply leave email resolution to a future enhancement.
        except Exception:
            pass

    # Attempt to resolve emails from Supabase auth.users
    for m in members:
        try:
            auth_resp = supabase.auth.admin.get_user_by_id(m["user_id"])
            if auth_resp and auth_resp.user:
                m["email"] = auth_resp.user.email or ""
        except Exception:
            pass

    return members


@router.get("/invites")
async def list_invites(user: AuthUser = Depends(get_current_user)):
    """List pending invitations for the current organization."""
    _require_admin(user)

    now = datetime.now(timezone.utc).isoformat()
    result = supabase.table("pending_invites") \
        .select("id, email, role, expires_at, created_at") \
        .eq("organization_id", str(user.org_id)) \
        .gte("expires_at", now) \
        .order("created_at", desc=True) \
        .execute()

    return result.data or []


@router.post("/invites")
async def invite_member(
    body: InviteRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Invite a new member to the organization."""
    _require_admin(user)

    if body.role not in ("admin", "member"):
        raise HTTPException(400, "Role must be 'admin' or 'member'")

    org = supabase.table("organizations") \
        .select("plan") \
        .eq("id", str(user.org_id)) \
        .single().execute()
    plan = (org.data or {}).get("plan", "free")
    limits = get_plan_limits(plan)
    max_seats = limits.get("max_user_seats")

    if max_seats is not None:
        current_count = supabase.table("user_profiles") \
            .select("id", count="exact") \
            .eq("organization_id", str(user.org_id)).execute()
        pending_count = supabase.table("pending_invites") \
            .select("id", count="exact") \
            .eq("organization_id", str(user.org_id)) \
            .gte("expires_at", datetime.now(timezone.utc).isoformat()).execute()

        total = (current_count.count or 0) + (pending_count.count or 0)
        if total >= max_seats:
            raise HTTPException(
                403,
                f"Your {plan} plan allows {max_seats} seat(s). "
                "Upgrade to add more team members.",
            )

    # Check for duplicate invite
    existing = supabase.table("pending_invites") \
        .select("id") \
        .eq("organization_id", str(user.org_id)) \
        .eq("email", body.email.lower()) \
        .gte("expires_at", datetime.now(timezone.utc).isoformat()) \
        .execute()
    if existing.data:
        raise HTTPException(409, "An invite for this email is already pending")

    # Check if user already a member
    existing_member = supabase.table("user_profiles") \
        .select("user_id") \
        .eq("organization_id", str(user.org_id)) \
        .execute()
    for m in existing_member.data or []:
        try:
            auth_resp = supabase.auth.admin.get_user_by_id(m["user_id"])
            if auth_resp and auth_resp.user and auth_resp.user.email == body.email.lower():
                raise HTTPException(409, "This user is already a member of your organization")
        except HTTPException:
            raise
        except Exception:
            pass

    result = supabase.table("pending_invites").insert({
        "organization_id": str(user.org_id),
        "email": body.email.lower(),
        "role": body.role,
        "invited_by": str(user.user_id),
    }).execute()

    log.info("Invite sent to %s for org %s by %s", body.email, user.org_id, user.user_id)
    return result.data[0]


@router.delete("/invites/{invite_id}")
async def cancel_invite(
    invite_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """Cancel a pending invitation."""
    _require_admin(user)

    supabase.table("pending_invites") \
        .delete() \
        .eq("id", str(invite_id)) \
        .eq("organization_id", str(user.org_id)) \
        .execute()

    return {"status": "canceled"}


@router.delete("/members/{member_user_id}")
async def remove_member(
    member_user_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """Remove a member from the organization. Owners cannot be removed."""
    _require_admin(user)

    if str(member_user_id) == str(user.user_id):
        raise HTTPException(400, "You cannot remove yourself")

    profile = supabase.table("user_profiles") \
        .select("role") \
        .eq("user_id", str(member_user_id)) \
        .eq("organization_id", str(user.org_id)) \
        .maybe_single().execute()

    if not profile.data:
        raise HTTPException(404, "Member not found")
    if profile.data["role"] == "owner":
        raise HTTPException(403, "Cannot remove the organization owner")

    supabase.table("user_profiles") \
        .delete() \
        .eq("user_id", str(member_user_id)) \
        .eq("organization_id", str(user.org_id)) \
        .execute()

    clear_profile_cache(member_user_id)
    log.info("Removed member %s from org %s", member_user_id, user.org_id)
    return {"status": "removed"}


@router.post("/invites/{token}/accept")
@limiter.limit("10/minute")
async def accept_invite(request: Request, token: UUID, user: AuthUser = Depends(get_current_user)):
    """Accept an invitation. The authenticated user's email must match the invite."""
    invite = supabase.table("pending_invites") \
        .select("*") \
        .eq("token", str(token)) \
        .maybe_single().execute()

    if not invite.data:
        raise HTTPException(404, "Invite not found or expired")

    if invite.data["email"].lower() != (user.email or "").lower():
        raise HTTPException(403, "This invite was sent to a different email address")

    expires = invite.data.get("expires_at", "")
    try:
        exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            raise HTTPException(410, "This invite has expired")
    except (ValueError, TypeError):
        pass

    return {
        "organization_id": invite.data["organization_id"],
        "role": invite.data["role"],
        "email": invite.data["email"],
        "invite_id": invite.data["id"],
    }
