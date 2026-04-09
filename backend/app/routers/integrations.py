"""Integration routes — Slack OAuth install/callback, disconnect, test, status."""
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..auth import AuthUser, get_current_user
from ..config import get_settings
from ..database import supabase
from ..plan_enforcement import OrgPlan, get_org_plan, check_slack_notifications, check_salesforce_notifications

log = logging.getLogger("dealer_intel.integrations")

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/integrations", tags=["integrations"])

SLACK_OAUTH_AUTHORIZE = "https://slack.com/oauth/v2/authorize"
SLACK_OAUTH_ACCESS = "https://slack.com/api/oauth.v2.access"
SLACK_SCOPES = "chat:write,channels:read,incoming-webhook"

SF_OAUTH_AUTHORIZE = "https://login.salesforce.com/services/oauth2/authorize"
SF_OAUTH_TOKEN = "https://login.salesforce.com/services/oauth2/token"
SF_SCOPES = "full refresh_token"

DBX_OAUTH_AUTHORIZE = "https://www.dropbox.com/oauth2/authorize"
DBX_OAUTH_TOKEN = "https://api.dropboxapi.com/oauth2/token"

JIRA_OAUTH_AUTHORIZE = "https://auth.atlassian.com/authorize"
JIRA_OAUTH_TOKEN = "https://auth.atlassian.com/oauth/token"
JIRA_SCOPES = "read:jira-work write:jira-work read:jira-user offline_access"


def _get_backend_base() -> str:
    settings = get_settings()
    base = settings.frontend_url.rstrip("/")
    if "localhost" in base:
        return "http://localhost:8000"
    return "https://dealer-intel-api-c2m2p.ondigitalocean.app"


def _get_redirect_uri() -> str:
    return _get_backend_base() + "/api/v1/integrations/slack/callback"


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


# ─── Salesforce ─────────────────────────────────────────────────


def _sf_redirect_uri() -> str:
    return _get_backend_base() + "/api/v1/integrations/salesforce/callback"


@router.get("/salesforce/install", summary="Start Salesforce OAuth flow")
async def salesforce_install(
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Redirect the user to Salesforce's OAuth consent screen."""
    check_salesforce_notifications(op)
    settings = get_settings()
    if not settings.salesforce_client_id:
        raise HTTPException(500, "Salesforce integration is not configured")

    state = _sign_state(str(user.org_id))
    params = urlencode({
        "response_type": "code",
        "client_id": settings.salesforce_client_id,
        "redirect_uri": _sf_redirect_uri(),
        "scope": SF_SCOPES,
        "state": state,
    })
    return {"authorize_url": f"{SF_OAUTH_AUTHORIZE}?{params}"}


@router.get("/salesforce/callback", summary="Salesforce OAuth callback")
async def salesforce_callback(code: str, state: str):
    """Exchange the authorization code for tokens and store the integration."""
    org_id = _verify_state(state)
    settings = get_settings()

    try:
        resp = httpx.post(SF_OAUTH_TOKEN, data={
            "grant_type": "authorization_code",
            "client_id": settings.salesforce_client_id,
            "client_secret": settings.salesforce_client_secret,
            "code": code,
            "redirect_uri": _sf_redirect_uri(),
        }, timeout=15)
        data = resp.json()
    except Exception as e:
        log.error("Salesforce OAuth token exchange failed: %s", e)
        return RedirectResponse(f"{settings.frontend_url}/settings?salesforce=error")

    if "error" in data:
        log.error("Salesforce OAuth error: %s — %s", data.get("error"), data.get("error_description"))
        return RedirectResponse(f"{settings.frontend_url}/settings?salesforce=error")

    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    instance_url = data.get("instance_url", "")

    # Fetch the org name from Salesforce
    sf_org_name = ""
    try:
        org_resp = httpx.get(
            f"{instance_url}/services/data/v59.0/query",
            params={"q": "SELECT Name FROM Organization LIMIT 1"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        records = org_resp.json().get("records", [])
        if records:
            sf_org_name = records[0].get("Name", "")
    except Exception:
        pass

    supabase.table("integrations").upsert({
        "organization_id": org_id,
        "provider": "salesforce",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "instance_url": instance_url,
        "workspace_name": sf_org_name,
        "connected_at": "now()",
    }, on_conflict="organization_id,provider").execute()

    log.info("Salesforce connected for org %s — instance '%s', sf_org '%s'",
             org_id, instance_url, sf_org_name)

    # Auto-provision Dealer Intel custom fields on the SF Account object
    try:
        from ..services.salesforce_sync_service import provision_custom_fields
        integration = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "instance_url": instance_url,
        }
        prov_result = provision_custom_fields(
            organization_id=UUID(org_id),
            integration=integration,
        )
        log.info("SF field provisioning result: %s", prov_result)
    except Exception as e:
        log.warning("SF field provisioning failed (non-blocking): %s", e)

    return RedirectResponse(f"{settings.frontend_url}/settings?salesforce=connected")


@router.get("/salesforce/status", summary="Get Salesforce integration status")
async def salesforce_status(user: AuthUser = Depends(get_current_user)):
    """Return current Salesforce integration status for the org."""
    try:
        result = supabase.table("integrations")\
            .select("workspace_name, instance_url, connected_at")\
            .eq("organization_id", str(user.org_id))\
            .eq("provider", "salesforce")\
            .maybe_single()\
            .execute()
    except Exception:
        return {"connected": False}

    if not result.data:
        return {"connected": False}

    return {
        "connected": True,
        "org_name": result.data.get("workspace_name", ""),
        "instance_url": result.data.get("instance_url", ""),
        "connected_at": result.data.get("connected_at"),
    }


@router.delete("/salesforce", summary="Disconnect Salesforce")
async def salesforce_disconnect(user: AuthUser = Depends(get_current_user)):
    """Remove the Salesforce integration for the org."""
    supabase.table("integrations")\
        .delete()\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "salesforce")\
        .execute()

    log.info("Salesforce disconnected for org %s", user.org_id)
    return {"status": "disconnected"}


@router.post("/salesforce/test", summary="Create a test Salesforce Task")
@limiter.limit("5/minute")
async def salesforce_test(
    request: Request,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Create a test Task in Salesforce to verify the connection."""
    check_salesforce_notifications(op)

    result = supabase.table("integrations")\
        .select("access_token, refresh_token, instance_url")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "salesforce")\
        .maybe_single()\
        .execute()

    if not result.data:
        raise HTTPException(400, "Salesforce is not connected. Connect Salesforce first.")

    from ..services.notification_service import send_salesforce_test

    success = send_salesforce_test(organization_id=user.org_id)
    if success:
        return {"success": True, "message": "Test task created in Salesforce"}
    raise HTTPException(500, "Failed to create test task. Check the Salesforce connection.")


@router.post("/salesforce/sync", summary="Trigger Salesforce dealer sync")
@limiter.limit("3/minute")
async def salesforce_sync(
    request: Request,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Manually trigger an inbound sync of Accounts from Salesforce."""
    check_salesforce_notifications(op)

    result = supabase.table("integrations")\
        .select("access_token")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "salesforce")\
        .maybe_single()\
        .execute()

    if not result.data:
        raise HTTPException(400, "Salesforce is not connected.")

    from ..services.salesforce_sync_service import sync_dealers_from_salesforce

    sync_result = sync_dealers_from_salesforce(user.org_id)
    if sync_result.get("error"):
        raise HTTPException(502, sync_result["error"])
    return sync_result


@router.get("/salesforce/sync/status", summary="Get Salesforce sync status")
async def salesforce_sync_status(user: AuthUser = Depends(get_current_user)):
    """Return the last sync timestamp and linked dealer count."""
    try:
        integration = supabase.table("integrations")\
            .select("last_synced_at, workspace_name, instance_url, connected_at")\
            .eq("organization_id", str(user.org_id))\
            .eq("provider", "salesforce")\
            .maybe_single()\
            .execute()
    except Exception:
        return {"connected": False}

    if not integration.data:
        return {"connected": False}

    try:
        linked = supabase.table("distributors")\
            .select("id", count="exact")\
            .eq("organization_id", str(user.org_id))\
            .not_.is_("salesforce_id", "null")\
            .execute()
        linked_count = linked.count or 0
    except Exception:
        linked_count = 0

    return {
        "connected": True,
        "org_name": integration.data.get("workspace_name", ""),
        "instance_url": integration.data.get("instance_url", ""),
        "connected_at": integration.data.get("connected_at"),
        "last_synced_at": integration.data.get("last_synced_at"),
        "linked_dealers": linked_count,
    }


# ─── Dropbox ────────────────────────────────────────────────────


def _dbx_redirect_uri() -> str:
    return _get_backend_base() + "/api/v1/integrations/dropbox/callback"


@router.get("/dropbox/install", summary="Start Dropbox OAuth flow")
async def dropbox_install(user: AuthUser = Depends(get_current_user)):
    """Redirect the user to Dropbox's OAuth consent screen."""
    settings = get_settings()
    if not settings.dropbox_client_id:
        raise HTTPException(500, "Dropbox integration is not configured")

    state = _sign_state(str(user.org_id))
    params = urlencode({
        "client_id": settings.dropbox_client_id,
        "redirect_uri": _dbx_redirect_uri(),
        "response_type": "code",
        "token_access_type": "offline",
        "state": state,
    })
    return {"authorize_url": f"{DBX_OAUTH_AUTHORIZE}?{params}"}


@router.get("/dropbox/callback", summary="Dropbox OAuth callback")
async def dropbox_callback(code: str, state: str):
    """Exchange the authorization code for tokens and store the integration."""
    org_id = _verify_state(state)
    settings = get_settings()

    try:
        resp = httpx.post(DBX_OAUTH_TOKEN, data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": settings.dropbox_client_id,
            "client_secret": settings.dropbox_client_secret,
            "redirect_uri": _dbx_redirect_uri(),
        }, timeout=15)
        data = resp.json()
    except Exception as e:
        log.error("Dropbox OAuth token exchange failed: %s", e)
        return RedirectResponse(f"{settings.frontend_url}/settings?dropbox=error")

    if "error" in data:
        log.error("Dropbox OAuth error: %s", data.get("error_description", data.get("error")))
        return RedirectResponse(f"{settings.frontend_url}/settings?dropbox=error")

    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")

    account_name = ""
    account_id = data.get("account_id", "")
    try:
        acct_resp = httpx.post(
            "https://api.dropboxapi.com/2/users/get_current_account",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        acct_data = acct_resp.json()
        account_name = acct_data.get("name", {}).get("display_name", "")
        if not account_id:
            account_id = acct_data.get("account_id", "")
    except Exception:
        pass

    supabase.table("integrations").upsert({
        "organization_id": org_id,
        "provider": "dropbox",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "workspace_name": account_name,
        "external_account_id": account_id,
        "folder_path": "/Dealer Intel",
        "folder_name": "Dealer Intel",
        "connected_at": "now()",
    }, on_conflict="organization_id,provider").execute()

    # Create /Dealer Intel/ root folder in Dropbox
    try:
        httpx.post(
            "https://api.dropboxapi.com/2/files/create_folder_v2",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"path": "/Dealer Intel", "autorename": False},
            timeout=10,
        )
    except Exception:
        pass  # folder may already exist

    log.info("Dropbox connected for org %s — account '%s', id '%s'", org_id, account_name, account_id)
    return RedirectResponse(f"{settings.frontend_url}/settings?dropbox=connected")


@router.get("/dropbox/status", summary="Get Dropbox integration status")
async def dropbox_status(user: AuthUser = Depends(get_current_user)):
    """Return current Dropbox integration status for the org."""
    try:
        result = supabase.table("integrations")\
            .select("workspace_name, folder_path, folder_name, campaign_id, last_synced_at, connected_at")\
            .eq("organization_id", str(user.org_id))\
            .eq("provider", "dropbox")\
            .execute()
    except Exception:
        return {"connected": False}

    if not result.data:
        return {"connected": False}

    row = result.data[0]
    return {
        "connected": True,
        "account_name": row.get("workspace_name", ""),
        "folder_path": row.get("folder_path"),
        "folder_name": row.get("folder_name"),
        "campaign_id": row.get("campaign_id"),
        "last_synced_at": row.get("last_synced_at"),
        "connected_at": row.get("connected_at"),
    }


@router.delete("/dropbox", summary="Disconnect Dropbox")
async def dropbox_disconnect(user: AuthUser = Depends(get_current_user)):
    """Remove the Dropbox integration for the org."""
    supabase.table("integrations")\
        .delete()\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "dropbox")\
        .execute()

    log.info("Dropbox disconnected for org %s", user.org_id)
    return {"status": "disconnected"}


@router.get("/dropbox/folders", summary="List Dropbox folders")
async def dropbox_list_folders(
    path: str = "",
    user: AuthUser = Depends(get_current_user),
):
    """List folders in the connected Dropbox account for folder selection."""
    integration = supabase.table("integrations")\
        .select("access_token, refresh_token")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "dropbox")\
        .execute()

    if not integration.data:
        raise HTTPException(400, "Dropbox is not connected")

    row = integration.data[0]
    token = row["access_token"]
    folder_path = path if path else ""

    try:
        resp = httpx.post(
            "https://api.dropboxapi.com/2/files/list_folder",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"path": folder_path, "include_non_downloadable_files": False},
            timeout=15,
        )

        if resp.status_code == 401:
            token = _refresh_dropbox_token(user.org_id, row["refresh_token"])
            if not token:
                raise HTTPException(401, "Dropbox session expired. Please reconnect.")
            resp = httpx.post(
                "https://api.dropboxapi.com/2/files/list_folder",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"path": folder_path, "include_non_downloadable_files": False},
                timeout=15,
            )

        if resp.status_code != 200:
            log.error("Dropbox list_folder %d: %s", resp.status_code, resp.text[:500])
            raise HTTPException(
                502,
                f"Dropbox API error ({resp.status_code}): {resp.text[:200]}",
            )

        data = resp.json()
        entries = data.get("entries", [])

        folders = [
            {"name": e["name"], "path": e["path_lower"]}
            for e in entries if e[".tag"] == "folder"
        ]
        image_count = sum(
            1 for e in entries
            if e[".tag"] == "file" and e.get("name", "").lower().split(".")[-1] in ("png", "jpg", "jpeg", "gif", "webp")
        )

        return {"folders": folders, "image_count": image_count, "current_path": folder_path or "/"}
    except HTTPException:
        raise
    except Exception as e:
        log.error("Dropbox folder listing failed: %s", e)
        raise HTTPException(500, f"Failed to list Dropbox folders: {e}")


@router.post("/dropbox/select-folder", summary="Select folder and campaign for sync")
async def dropbox_select_folder(
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Set which Dropbox folder to sync and which campaign to import into."""
    body = await request.json()
    folder_path = body.get("folder_path", "")
    folder_name = body.get("folder_name", "")
    campaign_id = body.get("campaign_id")

    if not campaign_id:
        raise HTTPException(400, "campaign_id is required")

    supabase.table("integrations").update({
        "folder_path": folder_path,
        "folder_name": folder_name,
        "campaign_id": campaign_id,
    }).eq("organization_id", str(user.org_id))\
      .eq("provider", "dropbox")\
      .execute()

    return {"status": "folder_selected", "folder_path": folder_path, "campaign_id": campaign_id}


@router.post("/dropbox/sync", summary="Sync assets from Dropbox folder")
@limiter.limit("5/minute")
async def dropbox_sync(
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Pull images from the selected Dropbox folder and import as campaign assets."""
    integration = supabase.table("integrations")\
        .select("access_token, refresh_token, folder_path, campaign_id")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "dropbox")\
        .execute()

    if not integration.data:
        raise HTTPException(400, "Dropbox is not connected")

    row = integration.data[0]
    if not row.get("folder_path") and row.get("folder_path") != "":
        raise HTTPException(400, "No folder selected. Choose a folder first.")
    if not row.get("campaign_id"):
        raise HTTPException(400, "No campaign selected. Choose a campaign first.")

    from ..services.dropbox_service import sync_dropbox_folder

    result = sync_dropbox_folder(
        organization_id=user.org_id,
        access_token=row["access_token"],
        refresh_token=row["refresh_token"],
        folder_path=row["folder_path"],
        campaign_id=row["campaign_id"],
    )

    # Update last_synced_at
    supabase.table("integrations").update({
        "last_synced_at": "now()",
    }).eq("organization_id", str(user.org_id))\
      .eq("provider", "dropbox")\
      .execute()

    return result


def _refresh_dropbox_token(org_id, refresh_token: str):
    """Refresh an expired Dropbox access token."""
    settings = get_settings()
    try:
        resp = httpx.post(DBX_OAUTH_TOKEN, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.dropbox_client_id,
            "client_secret": settings.dropbox_client_secret,
        }, timeout=15)
        data = resp.json()
        new_token = data.get("access_token")
        if not new_token:
            return None
        supabase.table("integrations").update({
            "access_token": new_token,
        }).eq("organization_id", str(org_id))\
          .eq("provider", "dropbox")\
          .execute()
        return new_token
    except Exception:
        return None


# ─── Dropbox Webhook ────────────────────────────────────────────


@router.get("/dropbox/webhook", summary="Dropbox webhook verification")
async def dropbox_webhook_verify(challenge: str = ""):
    """Respond to Dropbox's webhook verification request."""
    return PlainTextResponse(content=challenge, headers={"X-Content-Type-Options": "nosniff"})


@router.post("/dropbox/webhook", summary="Dropbox webhook notification")
async def dropbox_webhook_notification(request: Request):
    """
    Receive change notifications from Dropbox.
    Dropbox sends a list of account IDs that have changed.
    We match them to our integrations and trigger auto-sync.
    """
    import threading

    try:
        body = await request.json()
    except Exception:
        return {"ok": True}

    accounts = body.get("list_folder", {}).get("accounts", [])
    if not accounts:
        return {"ok": True}

    for account_id in accounts:
        result = supabase.table("integrations")\
            .select("id, organization_id, access_token, refresh_token, external_account_id")\
            .eq("provider", "dropbox")\
            .eq("external_account_id", account_id)\
            .execute()

        if not result.data:
            continue

        integration = result.data[0]
        # Run sync in background thread to return 200 quickly
        thread = threading.Thread(
            target=_run_auto_sync,
            args=(integration,),
            daemon=True,
        )
        thread.start()

    return {"ok": True}


def _run_auto_sync(integration: dict):
    """Run auto-sync in a background thread."""
    from ..services.dropbox_service import auto_sync_org
    try:
        auto_sync_org(integration)
    except Exception as e:
        log.error("Dropbox auto-sync failed for org %s: %s", integration.get("organization_id"), e)


@router.post("/dropbox/auto-sync", summary="Trigger Dropbox auto-sync manually")
@limiter.limit("3/minute")
async def dropbox_trigger_auto_sync(
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Manually trigger the auto-sync process for the current org."""
    integration = supabase.table("integrations")\
        .select("id, organization_id, access_token, refresh_token, external_account_id")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "dropbox")\
        .execute()

    if not integration.data:
        raise HTTPException(400, "Dropbox is not connected")

    from ..services.dropbox_service import auto_sync_org

    result = auto_sync_org(integration.data[0])
    return {
        "success": True,
        "campaigns_created": result["campaigns_created"],
        "images_imported": result["images_imported"],
        "images_skipped": result["images_skipped"],
        "message": (
            f"Synced: {result['campaigns_created']} new campaign(s), "
            f"{result['images_imported']} image(s) imported, "
            f"{result['images_skipped']} skipped"
        ),
    }


# ─── Jira ───────────────────────────────────────────────────────


def _jira_redirect_uri() -> str:
    return _get_backend_base() + "/api/v1/integrations/jira/callback"


@router.get("/jira/install", summary="Start Jira OAuth flow")
async def jira_install(user: AuthUser = Depends(get_current_user)):
    """Redirect the user to Atlassian's OAuth consent screen."""
    settings = get_settings()
    if not settings.jira_client_id:
        raise HTTPException(500, "Jira integration is not configured")

    state = _sign_state(str(user.org_id))
    params = urlencode({
        "audience": "api.atlassian.com",
        "client_id": settings.jira_client_id,
        "scope": JIRA_SCOPES,
        "redirect_uri": _jira_redirect_uri(),
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    })
    return {"authorize_url": f"{JIRA_OAUTH_AUTHORIZE}?{params}"}


@router.get("/jira/callback", summary="Jira OAuth callback")
async def jira_callback(code: str, state: str):
    """Exchange the authorization code for tokens and store the integration."""
    org_id = _verify_state(state)
    settings = get_settings()

    try:
        resp = httpx.post(JIRA_OAUTH_TOKEN, json={
            "grant_type": "authorization_code",
            "client_id": settings.jira_client_id,
            "client_secret": settings.jira_client_secret,
            "code": code,
            "redirect_uri": _jira_redirect_uri(),
        }, timeout=15)
        data = resp.json()
    except Exception as e:
        log.error("Jira OAuth token exchange failed: %s", e)
        return RedirectResponse(f"{settings.frontend_url}/settings?jira=error")

    if "error" in data:
        log.error("Jira OAuth error: %s", data.get("error_description", data.get("error")))
        return RedirectResponse(f"{settings.frontend_url}/settings?jira=error")

    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")

    # Fetch accessible resources (cloud sites)
    cloud_id = ""
    site_name = ""
    try:
        res_resp = httpx.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resources = res_resp.json()
        if resources:
            cloud_id = resources[0].get("id", "")
            site_name = resources[0].get("name", "")
    except Exception:
        pass

    supabase.table("integrations").upsert({
        "organization_id": org_id,
        "provider": "jira",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "cloud_id": cloud_id,
        "workspace_name": site_name,
        "connected_at": "now()",
    }, on_conflict="organization_id,provider").execute()

    log.info("Jira connected for org %s — site '%s' (cloud %s)", org_id, site_name, cloud_id)
    return RedirectResponse(f"{settings.frontend_url}/settings?jira=connected")


@router.get("/jira/status", summary="Get Jira integration status")
async def jira_status(user: AuthUser = Depends(get_current_user)):
    """Return current Jira integration status for the org."""
    try:
        result = supabase.table("integrations")\
            .select("workspace_name, cloud_id, project_key, connected_at")\
            .eq("organization_id", str(user.org_id))\
            .eq("provider", "jira")\
            .execute()
    except Exception:
        return {"connected": False}

    if not result.data:
        return {"connected": False}

    row = result.data[0]
    return {
        "connected": True,
        "site_name": row.get("workspace_name", ""),
        "cloud_id": row.get("cloud_id", ""),
        "project_key": row.get("project_key"),
        "connected_at": row.get("connected_at"),
    }


@router.delete("/jira", summary="Disconnect Jira")
async def jira_disconnect(user: AuthUser = Depends(get_current_user)):
    """Remove the Jira integration for the org."""
    supabase.table("integrations")\
        .delete()\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "jira")\
        .execute()

    log.info("Jira disconnected for org %s", user.org_id)
    return {"status": "disconnected"}


@router.get("/jira/projects", summary="List Jira projects")
async def jira_list_projects(user: AuthUser = Depends(get_current_user)):
    """List available projects in the connected Jira site."""
    integration = supabase.table("integrations")\
        .select("access_token, refresh_token, cloud_id")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "jira")\
        .execute()

    if not integration.data:
        raise HTTPException(400, "Jira is not connected")

    row = integration.data[0]
    token = row["access_token"]
    cloud_id = row["cloud_id"]

    try:
        resp = httpx.get(
            f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )

        if resp.status_code == 401:
            token = _refresh_jira_token(user.org_id, row["refresh_token"])
            if not token:
                raise HTTPException(401, "Jira session expired. Please reconnect.")
            resp = httpx.get(
                f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=15,
            )

        if resp.status_code != 200:
            raise HTTPException(502, f"Jira API error: {resp.text[:200]}")

        data = resp.json()
        projects = [
            {"key": p["key"], "name": p["name"], "id": p["id"]}
            for p in data.get("values", [])
        ]
        return {"projects": projects}
    except HTTPException:
        raise
    except Exception as e:
        log.error("Jira project listing failed: %s", e)
        raise HTTPException(500, f"Failed to list Jira projects: {e}")


@router.post("/jira/select-project", summary="Select Jira project for violations")
async def jira_select_project(
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Set which Jira project to create violation issues in."""
    body = await request.json()
    project_key = body.get("project_key", "")

    if not project_key:
        raise HTTPException(400, "project_key is required")

    supabase.table("integrations").update({
        "project_key": project_key,
    }).eq("organization_id", str(user.org_id))\
      .eq("provider", "jira")\
      .execute()

    return {"status": "project_selected", "project_key": project_key}


@router.post("/jira/test", summary="Create test Jira issue")
@limiter.limit("5/minute")
async def jira_test(request: Request, user: AuthUser = Depends(get_current_user)):
    """Create a test issue in the selected Jira project."""
    result = supabase.table("integrations")\
        .select("access_token, refresh_token, cloud_id, project_key")\
        .eq("organization_id", str(user.org_id))\
        .eq("provider", "jira")\
        .execute()

    if not result.data:
        raise HTTPException(400, "Jira is not connected. Connect Jira first.")

    row = result.data[0]
    if not row.get("project_key"):
        raise HTTPException(400, "No Jira project selected. Choose a project first.")

    from ..services.notification_service import send_jira_test

    success = send_jira_test(organization_id=user.org_id)
    if success:
        return {"success": True, "message": "Test issue created in Jira"}
    raise HTTPException(500, "Failed to create test issue. Check the Jira connection.")


def _refresh_jira_token(org_id, refresh_token: str):
    """Refresh an expired Jira access token."""
    settings = get_settings()
    try:
        resp = httpx.post(JIRA_OAUTH_TOKEN, json={
            "grant_type": "refresh_token",
            "client_id": settings.jira_client_id,
            "client_secret": settings.jira_client_secret,
            "refresh_token": refresh_token,
        }, timeout=15)
        data = resp.json()
        new_token = data.get("access_token")
        if not new_token:
            return None
        supabase.table("integrations").update({
            "access_token": new_token,
        }).eq("organization_id", str(org_id))\
          .eq("provider", "jira")\
          .execute()
        return new_token
    except Exception:
        return None
