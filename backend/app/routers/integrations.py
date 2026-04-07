"""Integration routes — Slack OAuth install/callback, disconnect, test, status."""
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..auth import AuthUser, get_current_user
from ..config import get_settings
from ..database import supabase
from ..plan_enforcement import OrgPlan, get_org_plan, check_slack_notifications

log = logging.getLogger("dealer_intel.integrations")

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/integrations", tags=["integrations"])

SLACK_OAUTH_AUTHORIZE = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_ACCESS = "https://slack.com/api/oauth.v2.access"
SLACK_SCOPES = "chat:write,channels:read,incoming-webhook"


def _get_redirect_uri() -> str:
    settings = get_settings()
    base = settings.frontend_url.rstrip("/")
    if "localhost" in base:
        return "http://localhost:8000/api/v1/integrations/slack/callback"
    return base.replace("dealer-intel-saas.vercel.app",
                        "dealer-intel-api-c2m2p.ondigitalocean.app") + "/api/v1/integrations/slack/callback"


def _sign_state(org_id: str) -> str:
    """Create an HMAC-signed state param to prevent CSRF."""
    settings = get_settings()
    secret = settings.slack_signing_secret or settings.slack_client_secret
    ts = str(int(time.time()))
    payload = f"{org_id}:{ts}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}:{sig}"


def _verify_state(state: str) -> str:
    """Verify state HMAC and return org_id. Raises on tamper or expiry (10 min)."""
    settings = get_settings()
    secret = settings.slack_signing_secret or settings.slack_client_secret
    parts = state.split(":")
    if len(parts) != 3:
        raise HTTPException(400, "Invalid OAuth state")

    org_id, ts, sig = parts
    payload = f"{org_id}:{ts}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(400, "Invalid OAuth state signature")

    if abs(time.time() - int(ts)) > 600:
        raise HTTPException(400, "OAuth state expired — please try again")

    return org_id


@router.get("/slack/install", summary="Start Slack OAuth flow")
async def slack_install(
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Redirect the user to Slack's OAuth consent screen."""
    check_slack_notifications(op)
    settings = get_settings()
    if not settings.slack_client_id:
        raise HTTPException(500, "Slack integration is not configured")

    state = _sign_state(str(user.org_id))
    params = urlencode({
        "client_id": settings.slack_client_id,
        "scope": SLACK_SCOPES,
        "redirect_uri": _get_redirect_uri(),
        "state": state,
    })
    return {"authorize_url": f"{SLACK_OAUTH_AUTHORIZE}?{params}"}


@router.get("/slack/callback", summary="Slack OAuth callback")
async def slack_callback(code: str, state: str):
    """Exchange the authorization code for a token and store the integration."""
    org_id = _verify_state(state)
    settings = get_settings()

    try:
        resp = httpx.post(SLACK_OAUTH_ACCESS, data={
            "client_id": settings.slack_client_id,
            "client_secret": settings.slack_client_secret,
            "code": code,
            "redirect_uri": _get_redirect_uri(),
        }, timeout=15)
        data = resp.json()
    except Exception as e:
        log.error("Slack OAuth token exchange failed: %s", e)
        return RedirectResponse(f"{settings.frontend_url}/settings?slack=error")

    if not data.get("ok"):
        log.error("Slack OAuth error: %s", data.get("error"))
        return RedirectResponse(f"{settings.frontend_url}/settings?slack=error")

    access_token = data.get("access_token", "")
    team = data.get("team", {})
    webhook_info = data.get("incoming_webhook", {})
    bot = data.get("bot_user_id", "")

    supabase.table("integrations").upsert({
        "organization_id": org_id,
        "provider": "slack",
        "access_token": access_token,
        "webhook_url": webhook_info.get("url", ""),
        "workspace_name": team.get("name", ""),
        "channel_name": webhook_info.get("channel", ""),
        "channel_id": webhook_info.get("channel_id", ""),
        "bot_user_id": bot,
        "connected_at": "now()",
    }, on_conflict="organization_id,provider").execute()

    log.info("Slack connected for org %s — workspace '%s', channel '%s'",
             org_id, team.get("name"), webhook_info.get("channel"))

    return RedirectResponse(f"{settings.frontend_url}/settings?slack=connected")


@router.get("/slack/status", summary="Get Slack integration status")
async def slack_status(user: AuthUser = Depends(get_current_user)):
    """Return current Slack integration status for the org."""
    try:
        result = supabase.table("integrations")\
            .select("workspace_name, channel_name, connected_at")\
            .eq("organization_id", str(user.org_id))\
            .eq("provider", "slack")\
            .maybe_single()\
            .execute()
    except Exception:
        return {"connected": False}

    if not result.data:
        return {"connected": False}

    return {
        "connected": True,
        "workspace_name": result.data.get("workspace_name", ""),
        "channel_name": result.data.get("channel_name", ""),
        "connected_at": result.data.get("connected_at"),
    }


@router.delete("/slack", summary="Disconnect Slack")
async def slack_disconnect(user: AuthUser = Depends(get_current_user)):
    """Remove the Slack integration for the org."""
    supabase.table("integrations")\
        .delete()\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "slack")\
        .execute()

    log.info("Slack disconnected for org %s", user.org_id)
    return {"status": "disconnected"}


@router.post("/slack/test", summary="Send a test Slack message")
@limiter.limit("5/minute")
async def slack_test(
    request: Request,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Send a test message to the connected Slack channel."""
    check_slack_notifications(op)

    result = supabase.table("integrations")\
        .select("access_token, channel_id, webhook_url")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "slack")\
        .maybe_single()\
        .execute()

    if not result.data:
        raise HTTPException(400, "Slack is not connected. Connect Slack first.")

    from ..services.notification_service import send_slack_test

    success = send_slack_test(
        access_token=result.data.get("access_token", ""),
        channel_id=result.data.get("channel_id", ""),
        webhook_url=result.data.get("webhook_url", ""),
    )

    if success:
        return {"success": True, "message": "Test message sent to Slack"}
    raise HTTPException(500, "Failed to send test message. Check the Slack connection.")
