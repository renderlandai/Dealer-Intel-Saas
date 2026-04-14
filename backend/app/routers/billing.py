"""Billing routes — Stripe Checkout, Customer Portal, usage tracking, and webhooks."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import stripe
from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..auth import AuthUser, get_current_user

limiter = Limiter(key_func=get_remote_address)
from ..config import (
    get_settings,
    get_plan_limits,
    get_stripe_price_id,
    get_extra_dealer_price_id,
    PLAN_LIMITS,
)
from ..database import supabase

log = logging.getLogger("dealer_intel.billing")

router = APIRouter(prefix="/billing", tags=["billing"])

settings = get_settings()
if settings.stripe_secret_key:
    stripe.api_key = settings.stripe_secret_key


PLAN_FROM_PRICE: dict = {}


def _build_price_plan_map() -> None:
    """Lazily build reverse mapping from Stripe Price ID → plan name."""
    if PLAN_FROM_PRICE:
        return
    s = get_settings()
    for plan, price_id in [
        ("starter", s.stripe_price_starter),
        ("professional", s.stripe_price_professional),
        ("business", s.stripe_price_business),
    ]:
        if price_id:
            PLAN_FROM_PRICE[price_id] = plan


def _plan_from_subscription(subscription: stripe.Subscription) -> str:
    """Determine the plan name from the subscription's line items."""
    _build_price_plan_map()
    for item in subscription["items"]["data"]:
        price_id = item["price"]["id"]
        if price_id in PLAN_FROM_PRICE:
            return PLAN_FROM_PRICE[price_id]
    return "starter"


# ------------------------------------------------------------------
# Checkout
# ------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str  # starter | professional | business


@router.post("/checkout-session", summary="Create checkout session")
@limiter.limit("10/minute")
async def create_checkout_session(
    request: Request,
    body: CheckoutRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Create a Stripe Checkout session for the selected plan."""
    s = get_settings()
    if not s.stripe_secret_key:
        raise HTTPException(503, "Billing not configured")

    if body.plan not in ("starter", "professional", "business"):
        raise HTTPException(400, "Plan must be starter, professional, or business")

    price_id = get_stripe_price_id(body.plan, s)
    if not price_id:
        raise HTTPException(500, f"Stripe price not configured for plan '{body.plan}'")

    org = supabase.table("organizations") \
        .select("id, name, stripe_customer_id") \
        .eq("id", str(user.org_id)) \
        .single().execute()
    if not org.data:
        raise HTTPException(404, "Organization not found")

    customer_id = org.data.get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            name=org.data.get("name"),
            metadata={"org_id": str(user.org_id)},
        )
        customer_id = customer.id
        supabase.table("organizations") \
            .update({"stripe_customer_id": customer_id}) \
            .eq("id", str(user.org_id)).execute()

    line_items = [{"price": price_id, "quantity": 1}]

    extra_price_id = get_extra_dealer_price_id(body.plan, s)
    if extra_price_id:
        line_items.append({"price": extra_price_id, "quantity": 0})

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=line_items,
        success_url=f"{s.frontend_url}/settings?billing=success",
        cancel_url=f"{s.frontend_url}/settings?billing=canceled",
        metadata={
            "org_id": str(user.org_id),
            "plan": body.plan,
        },
        subscription_data={
            "metadata": {
                "org_id": str(user.org_id),
                "plan": body.plan,
            },
        },
    )

    log.info("Checkout session created for org %s, plan %s", user.org_id, body.plan)
    return {"checkout_url": session.url, "session_id": session.id}


# ------------------------------------------------------------------
# Customer Portal (manage subscription, payment methods, invoices)
# ------------------------------------------------------------------

@router.post("/portal-session", summary="Create portal session")
@limiter.limit("10/minute")
async def create_portal_session(request: Request, user: AuthUser = Depends(get_current_user)):
    """Create a Stripe Customer Portal session for self-serve billing management."""
    s = get_settings()
    if not s.stripe_secret_key:
        raise HTTPException(503, "Billing not configured")

    org = supabase.table("organizations") \
        .select("stripe_customer_id") \
        .eq("id", str(user.org_id)) \
        .single().execute()
    customer_id = (org.data or {}).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No billing account found. Subscribe to a plan first.")

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{s.frontend_url}/settings",
    )
    return {"portal_url": session.url}


# ------------------------------------------------------------------
# Usage
# ------------------------------------------------------------------

_billing_cache: TTLCache = TTLCache(maxsize=200, ttl=60)


@router.get("/usage", summary="Get billing usage")
async def get_billing_usage(user: AuthUser = Depends(get_current_user)):
    """Return current plan, limits, and usage counters for the org."""
    org_id = str(user.org_id)

    if org_id in _billing_cache:
        return _billing_cache[org_id]

    org = supabase.table("organizations") \
        .select("plan, plan_status, trial_expires_at, extra_dealers_count") \
        .eq("id", org_id) \
        .single().execute()
    if not org.data:
        raise HTTPException(404, "Organization not found")

    plan = org.data.get("plan", "free")
    limits = get_plan_limits(plan)

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )

    dealer_count = supabase.table("distributors") \
        .select("id", count="exact") \
        .eq("organization_id", org_id) \
        .eq("status", "active").execute()

    campaign_count = supabase.table("campaigns") \
        .select("id", count="exact") \
        .eq("organization_id", org_id) \
        .eq("status", "active").execute()

    if plan == "free":
        scan_count = supabase.table("scan_jobs") \
            .select("id", count="exact") \
            .eq("organization_id", org_id).execute()
        scan_limit = limits.get("max_scans_total", 5)
        scan_label = "total"
    else:
        scan_count = supabase.table("scan_jobs") \
            .select("id", count="exact") \
            .eq("organization_id", org_id) \
            .gte("created_at", month_start.isoformat()).execute()
        scan_limit = limits.get("max_scans_per_month")
        scan_label = "this_month"

    active_scans = supabase.table("scan_jobs") \
        .select("id", count="exact") \
        .eq("organization_id", org_id) \
        .in_("status", ["pending", "running", "analyzing"]).execute()

    trial_expires = org.data.get("trial_expires_at")
    trial_days_left = None
    if plan == "free" and trial_expires:
        try:
            exp = datetime.fromisoformat(trial_expires.replace("Z", "+00:00"))
            delta = exp - datetime.now(timezone.utc)
            trial_days_left = max(0, delta.days)
        except Exception:
            pass

    result = {
        "plan": plan,
        "plan_status": org.data.get("plan_status", "trialing"),
        "trial_days_left": trial_days_left,
        "dealers": {
            "current": dealer_count.count or 0,
            "included": limits.get("included_dealers"),
            "max": limits.get("max_dealers"),
            "extra": org.data.get("extra_dealers_count", 0),
        },
        "campaigns": {
            "current": campaign_count.count or 0,
            "max": limits.get("max_campaigns"),
        },
        "scans": {
            "current": scan_count.count or 0,
            "max": scan_limit,
            "period": scan_label,
            "concurrent": active_scans.count or 0,
            "max_concurrent": limits.get("max_concurrent_scans"),
        },
        "features": {
            "channels": limits.get("allowed_channels"),
            "frequencies": limits.get("allowed_frequencies"),
            "pdf_reports": limits.get("pdf_reports"),
            "report_branding": limits.get("report_branding"),
            "email_notifications": limits.get("email_notifications"),
            "slack_notifications": limits.get("slack_notifications"),
            "compliance_trends": limits.get("compliance_trends"),
            "adaptive_calibration": limits.get("adaptive_calibration_active"),
            "api_access": limits.get("api_access"),
            "max_pages_per_site": limits.get("max_pages_per_site"),
            "max_user_seats": limits.get("max_user_seats"),
        },
    }
    _billing_cache[org_id] = result
    return result


# ------------------------------------------------------------------
# Stripe Webhook
# ------------------------------------------------------------------

@router.post("/webhook", summary="Handle Stripe webhook")
@limiter.limit("60/minute")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events to sync subscription state."""
    s = get_settings()
    if not s.stripe_secret_key or not s.stripe_webhook_secret:
        log.warning("Stripe webhook received but billing is not configured")
        return JSONResponse(status_code=503, content={"error": "Billing not configured"})

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, s.stripe_webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        log.warning("Stripe webhook signature verification failed")
        raise HTTPException(400, "Invalid signature")
    except Exception as e:
        log.error("Stripe webhook error: %s", e)
        raise HTTPException(400, "Webhook processing error")

    event_type = event["type"]
    data = event["data"]["object"]

    log.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type == "invoice.paid":
        _handle_invoice_paid(data)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data)
    else:
        log.debug("Unhandled Stripe event: %s", event_type)

    return JSONResponse(status_code=200, content={"received": True})


def _handle_checkout_completed(session: dict) -> None:
    """First-time subscription creation via Checkout."""
    org_id = (session.get("metadata") or {}).get("org_id")
    plan = (session.get("metadata") or {}).get("plan", "starter")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")

    if not org_id:
        log.warning("checkout.session.completed missing org_id in metadata")
        return

    updates = {
        "plan": plan,
        "plan_status": "active",
        "stripe_subscription_id": subscription_id,
        "trial_expires_at": None,
    }
    if customer_id:
        updates["stripe_customer_id"] = customer_id

    supabase.table("organizations") \
        .update(updates) \
        .eq("id", org_id).execute()

    log.info("Org %s activated on plan '%s' (sub %s)", org_id, plan, subscription_id)


def _handle_invoice_paid(invoice: dict) -> None:
    """Recurring payment succeeded — ensure plan is active."""
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    org = supabase.table("organizations") \
        .select("id, plan") \
        .eq("stripe_customer_id", customer_id) \
        .maybe_single().execute()
    if not org.data:
        return

    supabase.table("organizations") \
        .update({"plan_status": "active"}) \
        .eq("id", org.data["id"]).execute()

    log.info("Org %s invoice paid — plan_status set to active", org.data["id"])


def _handle_payment_failed(invoice: dict) -> None:
    """Payment failed — mark org as past_due."""
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    org = supabase.table("organizations") \
        .select("id") \
        .eq("stripe_customer_id", customer_id) \
        .maybe_single().execute()
    if not org.data:
        return

    supabase.table("organizations") \
        .update({"plan_status": "past_due"}) \
        .eq("id", org.data["id"]).execute()

    log.warning("Org %s payment failed — plan_status set to past_due", org.data["id"])


def _handle_subscription_updated(subscription: dict) -> None:
    """Plan change (upgrade/downgrade) or subscription reactivation."""
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    org = supabase.table("organizations") \
        .select("id") \
        .eq("stripe_customer_id", customer_id) \
        .maybe_single().execute()
    if not org.data:
        return

    new_plan = _plan_from_subscription(subscription)
    stripe_status = subscription.get("status", "active")

    status_map = {
        "active": "active",
        "past_due": "past_due",
        "canceled": "canceled",
        "unpaid": "past_due",
        "trialing": "trialing",
    }
    plan_status = status_map.get(stripe_status, "active")

    supabase.table("organizations").update({
        "plan": new_plan,
        "plan_status": plan_status,
        "stripe_subscription_id": subscription.get("id"),
    }).eq("id", org.data["id"]).execute()

    log.info("Org %s subscription updated → plan=%s, status=%s",
             org.data["id"], new_plan, plan_status)


def _handle_subscription_deleted(subscription: dict) -> None:
    """Subscription canceled — downgrade to free."""
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    org = supabase.table("organizations") \
        .select("id") \
        .eq("stripe_customer_id", customer_id) \
        .maybe_single().execute()
    if not org.data:
        return

    supabase.table("organizations").update({
        "plan": "free",
        "plan_status": "canceled",
        "stripe_subscription_id": None,
        "extra_dealers_count": 0,
    }).eq("id", org.data["id"]).execute()

    log.info("Org %s subscription canceled — downgraded to free", org.data["id"])
