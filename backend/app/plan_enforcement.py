"""Plan enforcement — reusable checks that gate features by subscription tier."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import Depends, HTTPException

from .auth import AuthUser, get_current_user
from .config import get_plan_limits
from .database import supabase

log = logging.getLogger("dealer_intel.plan_enforcement")


class OrgPlan:
    """Resolved plan context for the current request."""
    __slots__ = ("org_id", "plan", "plan_status", "limits", "trial_expired")

    def __init__(self, org_id: UUID, plan: str, plan_status: str,
                 limits: Dict[str, Any], trial_expired: bool):
        self.org_id = org_id
        self.plan = plan
        self.plan_status = plan_status
        self.limits = limits
        self.trial_expired = trial_expired


async def get_org_plan(user: AuthUser = Depends(get_current_user)) -> OrgPlan:
    """FastAPI dependency that resolves the org's plan and checks basic access."""
    org = supabase.table("organizations") \
        .select("plan, plan_status, trial_expires_at") \
        .eq("id", str(user.org_id)) \
        .single().execute()

    if not org.data:
        raise HTTPException(404, "Organization not found")

    plan = org.data.get("plan", "free")
    plan_status = org.data.get("plan_status", "trialing")
    limits = get_plan_limits(plan)

    trial_expired = False
    if plan == "free":
        exp = org.data.get("trial_expires_at")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                trial_expired = datetime.now(timezone.utc) > exp_dt
            except Exception:
                pass

    if plan_status == "canceled":
        raise HTTPException(403, "Your subscription has been canceled. Please resubscribe to continue.")

    if plan_status == "past_due":
        log.warning("Org %s is past_due — allowing access with warning", user.org_id)

    return OrgPlan(
        org_id=user.org_id,
        plan=plan,
        plan_status=plan_status,
        limits=limits,
        trial_expired=trial_expired,
    )


def require_active_plan(op: OrgPlan) -> None:
    """Block write operations if the free trial has expired."""
    if op.trial_expired:
        raise HTTPException(
            403,
            "Your free trial has expired. Upgrade to a paid plan to continue.",
        )


def check_dealer_limit(op: OrgPlan) -> None:
    """Raise 403 if the org has reached its dealer cap."""
    require_active_plan(op)
    max_dealers = op.limits.get("max_dealers")
    if max_dealers is None:
        return

    count = supabase.table("distributors") \
        .select("id", count="exact") \
        .eq("organization_id", str(op.org_id)) \
        .eq("status", "active").execute()
    current = count.count or 0

    if current >= max_dealers:
        raise HTTPException(
            403,
            f"Dealer limit reached ({current}/{max_dealers}). "
            f"Upgrade your plan to add more dealers.",
        )


def check_dealer_limit_bulk(op: OrgPlan, adding: int) -> None:
    """Raise 403 if bulk-adding dealers would exceed the cap."""
    require_active_plan(op)
    max_dealers = op.limits.get("max_dealers")
    if max_dealers is None:
        return

    count = supabase.table("distributors") \
        .select("id", count="exact") \
        .eq("organization_id", str(op.org_id)) \
        .eq("status", "active").execute()
    current = count.count or 0

    if current + adding > max_dealers:
        raise HTTPException(
            403,
            f"Adding {adding} dealers would exceed your limit "
            f"({current}/{max_dealers}). Upgrade your plan.",
        )


def check_campaign_limit(op: OrgPlan) -> None:
    """Raise 403 if the org has reached its campaign cap."""
    require_active_plan(op)
    max_campaigns = op.limits.get("max_campaigns")
    if max_campaigns is None:
        return

    count = supabase.table("campaigns") \
        .select("id", count="exact") \
        .eq("organization_id", str(op.org_id)) \
        .eq("status", "active").execute()
    current = count.count or 0

    if current >= max_campaigns:
        raise HTTPException(
            403,
            f"Campaign limit reached ({current}/{max_campaigns}). "
            f"Upgrade your plan to create more campaigns.",
        )


def check_scan_quota(op: OrgPlan) -> None:
    """Raise 429 if monthly (or lifetime for free) scan quota is exceeded."""
    require_active_plan(op)

    if op.plan == "free":
        max_total = op.limits.get("max_scans_total", 5)
        count = supabase.table("scan_jobs") \
            .select("id", count="exact") \
            .eq("organization_id", str(op.org_id)).execute()
        current = count.count or 0
        if current >= max_total:
            raise HTTPException(
                429,
                f"Scan limit reached ({current}/{max_total} total). "
                f"Upgrade to a paid plan for more scans.",
            )
        return

    max_monthly = op.limits.get("max_scans_per_month")
    if max_monthly is None:
        return

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    count = supabase.table("scan_jobs") \
        .select("id", count="exact") \
        .eq("organization_id", str(op.org_id)) \
        .gte("created_at", month_start.isoformat()).execute()
    current = count.count or 0

    if current >= max_monthly:
        raise HTTPException(
            429,
            f"Monthly scan limit reached ({current}/{max_monthly}). "
            f"Upgrade your plan for more scans.",
        )


def check_concurrent_scans(op: OrgPlan) -> None:
    """Raise 429 if too many scans are already running.

    Only counts 'pending' scans from the last 5 minutes to avoid stale
    pending scans permanently blocking the concurrent slot.
    """
    from datetime import timedelta

    max_concurrent = op.limits.get("max_concurrent_scans")
    if max_concurrent is None:
        return

    running = supabase.table("scan_jobs") \
        .select("id", count="exact") \
        .eq("organization_id", str(op.org_id)) \
        .in_("status", ["running", "analyzing"]).execute()

    pending_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    pending = supabase.table("scan_jobs") \
        .select("id", count="exact") \
        .eq("organization_id", str(op.org_id)) \
        .eq("status", "pending") \
        .gte("created_at", pending_cutoff).execute()

    current = (running.count or 0) + (pending.count or 0)

    if current >= max_concurrent:
        raise HTTPException(
            429,
            f"You already have {current} scan(s) running "
            f"(max {max_concurrent} for your plan). Wait for them to finish or upgrade.",
        )


def check_channel_allowed(op: OrgPlan, channel: str) -> None:
    """Raise 403 if the requested scan channel is not included in the plan."""
    allowed = op.limits.get("allowed_channels", [])
    if channel not in allowed:
        raise HTTPException(
            403,
            f"The '{channel}' channel is not available on your {op.plan} plan. "
            f"Upgrade to Pro to unlock all channels.",
        )


def check_frequency_allowed(op: OrgPlan, frequency: str) -> None:
    """Raise 403 if the requested schedule frequency is not included in the plan."""
    allowed = op.limits.get("allowed_frequencies", [])
    if not allowed:
        raise HTTPException(
            403,
            f"Scheduled scans are not available on your {op.plan} plan. "
            f"Upgrade to Starter or above.",
        )
    if frequency not in allowed:
        raise HTTPException(
            403,
            f"'{frequency}' scheduling is not available on your {op.plan} plan. "
            f"Available frequencies: {', '.join(allowed)}.",
        )


def check_schedule_limit(op: OrgPlan, campaign_id: str) -> None:
    """Raise 403 if the campaign has reached its schedule cap."""
    max_per_campaign = op.limits.get("max_schedules_per_campaign")
    if max_per_campaign is None or max_per_campaign == 0:
        if max_per_campaign == 0:
            raise HTTPException(
                403,
                f"Scheduled scans are not available on your {op.plan} plan.",
            )
        return

    count = supabase.table("scan_schedules") \
        .select("id", count="exact") \
        .eq("campaign_id", campaign_id) \
        .eq("is_active", True).execute()
    current = count.count or 0

    if current >= max_per_campaign:
        raise HTTPException(
            403,
            f"Schedule limit reached for this campaign ({current}/{max_per_campaign}). "
            f"Upgrade your plan for more schedules per campaign.",
        )


def check_pdf_reports(op: OrgPlan) -> None:
    """Raise 403 if PDF reports are not included in the plan."""
    if not op.limits.get("pdf_reports"):
        raise HTTPException(
            403,
            f"PDF reports are not available on your {op.plan} plan. "
            f"Upgrade to Pro to unlock PDF reports.",
        )


def check_report_branding(op: OrgPlan) -> None:
    """Raise 403 if report branding is not included in the plan."""
    if not op.limits.get("report_branding"):
        raise HTTPException(
            403,
            f"Report branding is not available on your {op.plan} plan. "
            f"Upgrade to Pro to customize report branding.",
        )


def check_email_notifications(op: OrgPlan) -> None:
    """Raise 403 if email notifications are not included in the plan."""
    if not op.limits.get("email_notifications"):
        raise HTTPException(
            403,
            f"Email notifications are not available on your {op.plan} plan. "
            f"Upgrade to Pro to enable email alerts.",
        )


def check_compliance_rules_limit(op: OrgPlan) -> None:
    """Raise 403 if the org has reached its compliance rules cap."""
    max_rules = op.limits.get("max_compliance_rules")
    if max_rules is None:
        return
    if max_rules == 0:
        raise HTTPException(
            403,
            f"Custom compliance rules are not available on your {op.plan} plan. "
            f"Upgrade to Pro to create custom rules.",
        )

    count = supabase.table("compliance_rules") \
        .select("id", count="exact") \
        .eq("organization_id", str(op.org_id)) \
        .eq("is_active", True).execute()
    current = count.count or 0

    if current >= max_rules:
        raise HTTPException(
            403,
            f"Compliance rule limit reached ({current}/{max_rules}). "
            f"Upgrade your plan to add more rules.",
        )
