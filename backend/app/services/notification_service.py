"""Notification service — email via Resend + Slack via Bot API."""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.notifications")

RESEND_URL = "https://api.resend.com/emails"
SLACK_POST_MESSAGE = "https://slack.com/api/chat.postMessage"


# ─── Deep-link helpers ──────────────────────────────────────────
#
# Every notification points back into the dashboard so recipients can act on
# the result without hunting for it. The URLs are built from
# `settings.frontend_url` (already used by OAuth + Stripe redirects) and the
# routes that exist today in `frontend/app/`:
#
#   /matches                    — full match list
#   /matches?status=violation   — filtered to violations only
#   /matches/{id}               — per-match detail
#
# Per-scan filtering (`?scan_job_id=…`) is intentionally NOT used here because
# `routers/matches.py` does not yet accept that query param. If/when it does,
# add it to `_dashboard_link` and the per-channel callers below.


def _dashboard_link(path: str = "") -> str:
    """Return an absolute URL into the dashboard for the given relative path."""
    base = get_settings().frontend_url.rstrip("/")
    if not path:
        return base
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _matches_url() -> str:
    return _dashboard_link("/matches")


def _violations_url() -> str:
    return _dashboard_link("/matches?status=violation")


def _match_detail_url(match_id: Optional[str]) -> Optional[str]:
    if not match_id:
        return None
    return _dashboard_link(f"/matches/{match_id}")


def _get_org_notify_email(organization_id: UUID) -> Optional[str]:
    """Return the org's notification email if notifications are enabled."""
    try:
        result = supabase.table("organizations")\
            .select("name, notify_email, notify_on_violation")\
            .eq("id", str(organization_id))\
            .single()\
            .execute()
    except Exception:
        return None

    data = result.data or {}
    if not data.get("notify_email"):
        return None
    if not data.get("notify_on_violation", True):
        return None
    return data["notify_email"]


def _get_org_name(organization_id: UUID) -> str:
    try:
        result = supabase.table("organizations")\
            .select("name")\
            .eq("id", str(organization_id))\
            .single()\
            .execute()
        return (result.data or {}).get("name", "Your Organization")
    except Exception:
        return "Your Organization"


def _send_via_resend(*, to: str, subject: str, html: str) -> bool:
    """Send email via Resend API. Returns True on success."""
    settings = get_settings()
    if not settings.resend_api_key:
        log.warning("RESEND_API_KEY not set — skipping email")
        return False

    try:
        resp = httpx.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.resend_from_email,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            log.info("Email sent to %s*** — %s", to[:3], subject)
            return True
        log.error("Resend API error %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        log.error("Failed to send email to %s***: %s", to[:3], e)
        return False


def _build_scan_report_email(
    *,
    org_name: str,
    scan_source: str,
    summary: Dict[str, Any],
    violations: List[Dict[str, Any]],
) -> tuple[str, str]:
    """Build subject + HTML for a combined scan completion + violations email."""
    total = summary.get("total_images", 0)
    matches = summary.get("matches", 0)
    compliant = summary.get("compliant", 0)
    violation_count = len(violations)
    pages = summary.get("pages_scanned", 0)
    channel = (scan_source or "scan").replace("_", " ").title()

    if violation_count > 0:
        subject = f"[Dealer Intel] Scan complete — {violation_count} violation{'s' if violation_count != 1 else ''} found"
    else:
        subject = f"[Dealer Intel] Scan complete — all clear"

    compliance_rate = summary.get("compliance_rate", 0)
    rate_color = "#16a34a" if compliance_rate >= 80 else ("#d97706" if compliance_rate >= 60 else "#dc2626")

    stats_html = f"""
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
      <tr>
        <td style="padding:12px 16px;background:#f8fafc;border:1px solid #e5e7eb;text-align:center;width:20%;">
          <div style="font-size:22px;font-weight:600;color:#111827;">{total}</div>
          <div style="font-size:11px;color:#6b7280;margin-top:2px;">Images Analyzed</div>
        </td>
        <td style="padding:12px 16px;background:#f8fafc;border:1px solid #e5e7eb;text-align:center;width:20%;">
          <div style="font-size:22px;font-weight:600;color:#111827;">{matches}</div>
          <div style="font-size:11px;color:#6b7280;margin-top:2px;">Matches</div>
        </td>
        <td style="padding:12px 16px;background:#f8fafc;border:1px solid #e5e7eb;text-align:center;width:20%;">
          <div style="font-size:22px;font-weight:600;color:#16a34a;">{compliant}</div>
          <div style="font-size:11px;color:#6b7280;margin-top:2px;">Compliant</div>
        </td>
        <td style="padding:12px 16px;background:#f8fafc;border:1px solid #e5e7eb;text-align:center;width:20%;">
          <div style="font-size:22px;font-weight:600;color:#dc2626;">{violation_count}</div>
          <div style="font-size:11px;color:#6b7280;margin-top:2px;">Violations</div>
        </td>
        <td style="padding:12px 16px;background:#f8fafc;border:1px solid #e5e7eb;text-align:center;width:20%;">
          <div style="font-size:22px;font-weight:600;color:{rate_color};">{compliance_rate}%</div>
          <div style="font-size:11px;color:#6b7280;margin-top:2px;">Compliance</div>
        </td>
      </tr>
    </table>"""

    violations_html = ""
    if violations:
        rows = ""
        for v in violations[:20]:
            detail_url = _match_detail_url(v.get("match_id"))
            review_cell = (
                f'<a href="{detail_url}" style="color:#334155;text-decoration:underline;font-size:12px;">Review</a>'
                if detail_url
                else '<span style="color:#9ca3af;font-size:12px;">—</span>'
            )
            rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('asset_name', 'Unknown')}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('distributor_name', 'Unknown')}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('channel', channel)}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('confidence_score', 0)}%</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#6b7280;">{v.get('compliance_summary', '')}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{review_cell}</td>
            </tr>"""

        truncation = ""
        if violation_count > 20:
            truncation = (
                f'<p style="color:#6b7280;font-size:12px;margin-top:8px;">'
                f'Showing 20 of {violation_count} violations. '
                f'<a href="{_violations_url()}" style="color:#334155;">View all in the dashboard</a>.'
                f'</p>'
            )

        violations_html = f"""
        <h3 style="font-size:14px;color:#dc2626;margin:20px 0 10px 0;">Violation Details</h3>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#fef2f2;">
              <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #fecaca;color:#991b1b;">Asset</th>
              <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #fecaca;color:#991b1b;">Distributor</th>
              <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #fecaca;color:#991b1b;">Channel</th>
              <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #fecaca;color:#991b1b;">Confidence</th>
              <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #fecaca;color:#991b1b;">Details</th>
              <th style="padding:8px 12px;text-align:right;border-bottom:2px solid #fecaca;color:#991b1b;"></th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        {truncation}"""

    # Primary CTA — violations link if any, otherwise the matches dashboard.
    if violation_count > 0:
        cta_label = f"Review {violation_count} Violation{'s' if violation_count != 1 else ''}"
        cta_href = _violations_url()
    else:
        cta_label = "Open Dashboard"
        cta_href = _matches_url()

    cta_html = f"""
    <div style="margin:24px 0 8px 0;">
      <a href="{cta_href}"
         style="display:inline-block;background:#334155;color:#ffffff;text-decoration:none;
                padding:11px 22px;font-size:14px;font-weight:600;border-radius:4px;">
        {cta_label}
      </a>
      <a href="{_matches_url()}"
         style="display:inline-block;margin-left:12px;color:#334155;text-decoration:underline;
                font-size:13px;line-height:38px;vertical-align:top;">
        View all matches
      </a>
    </div>"""

    pages_line = f" across {pages} pages" if pages > 0 else ""

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:0 auto;">
      <div style="background:#334155;padding:20px 24px;">
        <h1 style="color:#ffffff;font-size:18px;margin:0;">Dealer Intel</h1>
      </div>
      <div style="padding:24px;background:#ffffff;">
        <h2 style="font-size:16px;color:#111827;margin:0 0 4px 0;">
          {channel} Scan Complete
        </h2>
        <p style="color:#6b7280;font-size:13px;margin:0 0 20px 0;">
          {org_name} &mdash; {total} images analyzed{pages_line}
        </p>
        {stats_html}
        {violations_html}
        {cta_html}
      </div>
      <div style="padding:16px 24px;background:#f8fafc;border-top:1px solid #e5e7eb;">
        <p style="color:#9ca3af;font-size:11px;margin:0;">
          Sent by Dealer Intel &mdash; AI-powered campaign asset compliance monitoring
        </p>
      </div>
    </div>"""

    return subject, html


def notify_scan_complete(
    *,
    organization_id: UUID,
    scan_source: str = "",
    summary: Dict[str, Any],
    violations: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Send a scan completion email with summary stats and any violations.
    Called from the scanning pipeline when a scan finishes.
    """
    to_email = _get_org_notify_email(organization_id)
    if not to_email:
        log.debug("No notification email for org %s — skipping", organization_id)
        return False

    org_name = _get_org_name(organization_id)
    subject, html = _build_scan_report_email(
        org_name=org_name,
        scan_source=scan_source,
        summary=summary,
        violations=violations or [],
    )

    return _send_via_resend(to=to_email, subject=subject, html=html)


def send_invite_email(
    *,
    to_email: str,
    org_name: str,
    inviter_email: str,
    role: str,
    accept_url: str,
) -> bool:
    """Send a team invite email with an accept link."""
    subject = f"[Dealer Intel] You've been invited to join {org_name}"

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:500px;margin:0 auto;">
      <div style="background:#334155;padding:20px 24px;">
        <h1 style="color:#ffffff;font-size:18px;margin:0;">Dealer Intel</h1>
      </div>
      <div style="padding:24px;background:#ffffff;">
        <h2 style="font-size:16px;color:#111827;margin:0 0 8px 0;">You're Invited</h2>
        <p style="color:#374151;font-size:14px;line-height:1.6;margin:0 0 16px 0;">
          <strong>{inviter_email}</strong> has invited you to join
          <strong>{org_name}</strong> as a <strong>{role}</strong> on Dealer Intel.
        </p>
        <a href="{accept_url}"
           style="display:inline-block;background:#334155;color:#ffffff;text-decoration:none;padding:12px 24px;font-size:14px;font-weight:600;">
          Accept Invitation
        </a>
        <p style="color:#6b7280;font-size:12px;margin:16px 0 0 0;">
          This invitation expires in 7 days. If you don't have an account yet,
          you'll be asked to sign up first.
        </p>
      </div>
      <div style="padding:16px 24px;background:#f8fafc;border-top:1px solid #e5e7eb;">
        <p style="color:#9ca3af;font-size:11px;margin:0;">
          Sent by Dealer Intel &mdash; AI-powered campaign asset compliance monitoring
        </p>
      </div>
    </div>"""

    return _send_via_resend(to=to_email, subject=subject, html=html)


def send_test_email(organization_id: UUID) -> dict:
    """Send a test email to verify notifications are working."""
    to_email = _get_org_notify_email(organization_id)
    if not to_email:
        return {"success": False, "error": "No notification email configured. Save an email address first."}

    settings = get_settings()
    if not settings.resend_api_key:
        return {"success": False, "error": "Email service not configured. Contact your administrator."}

    org_name = _get_org_name(organization_id)

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:500px;margin:0 auto;">
      <div style="background:#334155;padding:20px 24px;">
        <h1 style="color:#ffffff;font-size:18px;margin:0;">Dealer Intel</h1>
      </div>
      <div style="padding:24px;background:#ffffff;">
        <h2 style="font-size:16px;color:#111827;margin:0 0 8px 0;">Test Email Successful</h2>
        <p style="color:#6b7280;font-size:14px;margin:0;">
          Notifications are configured correctly for <strong>{org_name}</strong>.
          You will receive scan summaries and violation alerts at this address.
        </p>
      </div>
      <div style="padding:16px 24px;background:#f8fafc;border-top:1px solid #e5e7eb;">
        <p style="color:#9ca3af;font-size:11px;margin:0;">
          Sent by Dealer Intel &mdash; AI-powered campaign asset compliance monitoring
        </p>
      </div>
    </div>"""

    success = _send_via_resend(
        to=to_email,
        subject="[Dealer Intel] Test notification",
        html=html,
    )

    if success:
        masked = to_email[:3] + "***" + to_email[to_email.index("@"):] if "@" in to_email else to_email[:3] + "***"
        return {"success": True, "message": f"Test email sent to {masked}"}
    return {"success": False, "error": "Failed to send email. Check the server logs for details."}


# ─── Slack ──────────────────────────────────────────────────────


def _get_slack_integration(organization_id: UUID) -> Optional[Dict[str, Any]]:
    """Return the Slack integration row for the org, or None."""
    try:
        result = supabase.table("integrations")\
            .select("access_token, channel_id, webhook_url")\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "slack")\
            .maybe_single()\
            .execute()
        return result.data
    except Exception:
        return None


def _post_slack_message(*, access_token: str, channel_id: str, blocks: list) -> bool:
    """Post a Block Kit message via Slack's chat.postMessage API."""
    try:
        resp = httpx.post(
            SLACK_POST_MESSAGE,
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json; charset=utf-8"},
            json={"channel": channel_id, "blocks": blocks},
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            log.info("Slack message sent to channel %s", channel_id)
            return True
        log.error("Slack API error: %s", data.get("error"))
        return False
    except Exception as e:
        log.error("Slack message failed: %s", e)
        return False


def _post_slack_webhook(*, webhook_url: str, blocks: list) -> bool:
    """Fallback: post via Incoming Webhook if channel_id is missing."""
    try:
        resp = httpx.post(webhook_url, json={"blocks": blocks}, timeout=10)
        if resp.status_code == 200:
            log.info("Slack webhook message sent")
            return True
        log.error("Slack webhook error %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        log.error("Slack webhook failed: %s", e)
        return False


def _build_scan_slack_blocks(
    *,
    org_name: str,
    scan_source: str,
    summary: Dict[str, Any],
    violations: List[Dict[str, Any]],
) -> list:
    """Build Slack Block Kit blocks for a scan report."""
    total = summary.get("total_images", 0)
    matches = summary.get("matches", 0)
    violation_count = len(violations)
    compliance_rate = summary.get("compliance_rate", 0)
    channel = (scan_source or "scan").replace("_", " ").title()

    status_emoji = ":white_check_mark:" if violation_count == 0 else ":warning:"
    status_text = "all clear" if violation_count == 0 else f"{violation_count} violation{'s' if violation_count != 1 else ''} found"

    blocks: list = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{status_emoji} {channel} Scan Complete", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{org_name}* — {status_text}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Images Analyzed:*\n{total}"},
                {"type": "mrkdwn", "text": f"*Matches:*\n{matches}"},
                {"type": "mrkdwn", "text": f"*Violations:*\n{violation_count}"},
                {"type": "mrkdwn", "text": f"*Compliance:*\n{compliance_rate}%"},
            ],
        },
    ]

    if violations:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Top Violations:*"},
        })
        # One section per violation so each row can carry its own "Review"
        # button accessory pointing at /matches/{id}. Slack allows only one
        # accessory per section, hence the per-row layout.
        for v in violations[:10]:
            text = (
                f"• *{v.get('asset_name', '?')}* at {v.get('distributor_name', '?')} "
                f"— {v.get('confidence_score', 0)}% confidence"
            )
            section: Dict[str, Any] = {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
            detail_url = _match_detail_url(v.get("match_id"))
            if detail_url:
                section["accessory"] = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Review", "emoji": True},
                    "url": detail_url,
                    "action_id": f"match_review_{v.get('match_id')}",
                }
            blocks.append(section)
        if violation_count > 10:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_...and {violation_count - 10} more_"}],
            })

    # Always include a final actions block so users land in the dashboard
    # even when there are no violations to review individually.
    primary_text = (
        f"Review {violation_count} Violation{'s' if violation_count != 1 else ''}"
        if violation_count > 0
        else "Open Dashboard"
    )
    primary_url = _violations_url() if violation_count > 0 else _matches_url()

    actions_block: Dict[str, Any] = {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": primary_text, "emoji": True},
                "url": primary_url,
                "style": "primary",
                "action_id": "scan_primary_cta",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View All Matches", "emoji": True},
                "url": _matches_url(),
                "action_id": "scan_view_all_matches",
            },
        ],
    }
    blocks.append(actions_block)

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "Sent by *Dealer Intel* — AI-powered campaign compliance"}],
    })

    return blocks


def notify_slack_scan_complete(
    *,
    organization_id: UUID,
    scan_source: str = "",
    summary: Dict[str, Any],
    violations: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Send a scan report to Slack if connected. Returns True on success."""
    integration = _get_slack_integration(organization_id)
    if not integration:
        return False

    org_name = _get_org_name(organization_id)
    blocks = _build_scan_slack_blocks(
        org_name=org_name,
        scan_source=scan_source,
        summary=summary,
        violations=violations or [],
    )

    access_token = integration.get("access_token", "")
    channel_id = integration.get("channel_id", "")
    webhook_url = integration.get("webhook_url", "")

    if access_token and channel_id:
        return _post_slack_message(access_token=access_token, channel_id=channel_id, blocks=blocks)
    elif webhook_url:
        return _post_slack_webhook(webhook_url=webhook_url, blocks=blocks)

    log.warning("Slack integration for org %s has no token or webhook", organization_id)
    return False


def send_slack_test(*, access_token: str, channel_id: str, webhook_url: str) -> bool:
    """Send a test message to Slack."""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: *Dealer Intel — Slack Connected*\n"
                        "You will receive scan summaries and violation alerts in this channel.",
            },
        },
    ]

    if access_token and channel_id:
        return _post_slack_message(access_token=access_token, channel_id=channel_id, blocks=blocks)
    elif webhook_url:
        return _post_slack_webhook(webhook_url=webhook_url, blocks=blocks)
    return False


# ─── Salesforce ─────────────────────────────────────────────────


def _get_salesforce_integration(organization_id: UUID) -> Optional[Dict[str, Any]]:
    """Return the Salesforce integration row for the org, or None."""
    try:
        result = supabase.table("integrations")\
            .select("access_token, refresh_token, instance_url")\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "salesforce")\
            .maybe_single()\
            .execute()
        return result.data
    except Exception:
        return None


def _refresh_salesforce_token(organization_id: UUID, refresh_token: str) -> Optional[str]:
    """Refresh an expired Salesforce access token. Returns new token or None."""
    settings = get_settings()
    try:
        resp = httpx.post("https://login.salesforce.com/services/oauth2/token", data={
            "grant_type": "refresh_token",
            "client_id": settings.salesforce_client_id,
            "client_secret": settings.salesforce_client_secret,
            "refresh_token": refresh_token,
        }, timeout=15)
        data = resp.json()
        new_token = data.get("access_token")
        if not new_token:
            log.error("Salesforce token refresh failed: %s", data.get("error"))
            return None

        supabase.table("integrations")\
            .update({"access_token": new_token})\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "salesforce")\
            .execute()

        log.info("Salesforce token refreshed for org %s", organization_id)
        return new_token
    except Exception as e:
        log.error("Salesforce token refresh error: %s", e)
        return None


def _sf_api_request(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
    method: str,
    path: str,
    json_body: Optional[Dict] = None,
) -> Optional[httpx.Response]:
    """Make a Salesforce REST API request with automatic token refresh on 401."""
    instance_url = integration["instance_url"]
    token = integration["access_token"]
    url = f"{instance_url}{path}"

    for attempt in range(2):
        try:
            resp = httpx.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=json_body,
                timeout=15,
            )
            if resp.status_code == 401 and attempt == 0:
                new_token = _refresh_salesforce_token(organization_id, integration["refresh_token"])
                if new_token:
                    token = new_token
                    continue
                return None
            return resp
        except Exception as e:
            log.error("Salesforce API request failed: %s", e)
            return None
    return None


def _create_sf_task(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
    subject: str,
    description: str,
    priority: str = "Normal",
) -> bool:
    """Create a Task record in Salesforce."""
    resp = _sf_api_request(
        organization_id=organization_id,
        integration=integration,
        method="POST",
        path="/services/data/v59.0/sobjects/Task",
        json_body={
            "Subject": subject,
            "Description": description,
            "Priority": priority,
            "Status": "Not Started",
        },
    )
    if resp and resp.status_code in (200, 201):
        log.info("Salesforce Task created for org %s: %s", organization_id, subject)
        return True
    if resp:
        log.error("Salesforce Task creation failed %d: %s", resp.status_code, resp.text[:300])
    return False


def notify_salesforce_scan_complete(
    *,
    organization_id: UUID,
    scan_source: str = "",
    summary: Dict[str, Any],
    violations: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Create a Salesforce Task for scan results if connected. Returns True on success."""
    integration = _get_salesforce_integration(organization_id)
    if not integration:
        return False

    violations = violations or []
    violation_count = len(violations)
    total = summary.get("total_images", 0)
    compliance_rate = summary.get("compliance_rate", 0)
    channel = (scan_source or "scan").replace("_", " ").title()
    org_name = _get_org_name(organization_id)

    if violation_count > 0:
        subject = f"[Dealer Intel] {channel} Scan — {violation_count} violation{'s' if violation_count != 1 else ''} found"
        priority = "High"
    else:
        subject = f"[Dealer Intel] {channel} Scan — All Clear"
        priority = "Normal"

    lines = [
        f"Organization: {org_name}",
        f"Channel: {channel}",
        f"Images Analyzed: {total}",
        f"Matches: {summary.get('matches', 0)}",
        f"Violations: {violation_count}",
        f"Compliance Rate: {compliance_rate}%",
        "",
    ]

    # Plain URLs auto-linkify in the Salesforce Task UI, so listing them in
    # the description is enough — no rich-text payload needed.
    if violation_count > 0:
        lines.append(f"Review violations: {_violations_url()}")
    lines.append(f"Open dashboard: {_matches_url()}")

    if violations:
        lines.append("")
        lines.append("--- Top Violations ---")
        for v in violations[:15]:
            base = (
                f"• {v.get('asset_name', '?')} at {v.get('distributor_name', '?')} "
                f"— {v.get('confidence_score', 0)}% confidence"
            )
            detail_url = _match_detail_url(v.get("match_id"))
            if detail_url:
                base += f" — {detail_url}"
            lines.append(base)
        if violation_count > 15:
            lines.append(f"...and {violation_count - 15} more — {_violations_url()}")

    description = "\n".join(lines)

    return _create_sf_task(
        organization_id=organization_id,
        integration=integration,
        subject=subject,
        description=description,
        priority=priority,
    )


def send_salesforce_test(*, organization_id: UUID) -> bool:
    """Create a test Task in Salesforce."""
    integration = _get_salesforce_integration(organization_id)
    if not integration:
        return False

    return _create_sf_task(
        organization_id=organization_id,
        integration=integration,
        subject="[Dealer Intel] Connection Test — Salesforce Connected",
        description="This is a test task from Dealer Intel.\n\n"
                    "Scan results and violation alerts will appear as Tasks automatically.",
        priority="Low",
    )


# ─── Jira ────────────────────────────────────────────────────────


def _get_jira_integration(organization_id: UUID) -> Optional[Dict[str, Any]]:
    """Return the Jira integration row for the org, or None."""
    try:
        result = supabase.table("integrations")\
            .select("access_token, refresh_token, cloud_id, project_key")\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "jira")\
            .execute()
        if result.data:
            return result.data[0]
    except Exception:
        pass
    return None


def _refresh_jira_token(organization_id: UUID, refresh_token: str) -> Optional[str]:
    """Refresh an expired Jira access token. Returns new token or None."""
    from ..config import get_settings
    settings = get_settings()
    try:
        resp = httpx.post("https://auth.atlassian.com/oauth/token", json={
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
        }).eq("organization_id", str(organization_id))\
          .eq("provider", "jira")\
          .execute()
        return new_token
    except Exception as e:
        log.error("Jira token refresh failed for org %s: %s", organization_id, e)
    return None


def _jira_api_request(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
    method: str,
    path: str,
    json_body: Optional[Dict] = None,
) -> Optional[httpx.Response]:
    """Make a Jira REST API request with automatic token refresh on 401."""
    cloud_id = integration.get("cloud_id", "")
    token = integration["access_token"]
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}{path}"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}

    try:
        resp = httpx.request(method, url, headers=headers, json=json_body, timeout=15)
    except Exception as e:
        log.error("Jira API request failed: %s", e)
        return None

    if resp.status_code == 401:
        new_token = _refresh_jira_token(organization_id, integration.get("refresh_token", ""))
        if not new_token:
            return resp
        headers["Authorization"] = f"Bearer {new_token}"
        try:
            resp = httpx.request(method, url, headers=headers, json=json_body, timeout=15)
        except Exception:
            return None

    return resp


def _adf_text(text: str, href: Optional[str] = None) -> Dict[str, Any]:
    """Build an ADF text node, optionally wrapped in a clickable link mark."""
    node: Dict[str, Any] = {"type": "text", "text": text}
    if href:
        node["marks"] = [{"type": "link", "attrs": {"href": href}}]
    return node


def _adf_paragraph(*nodes: Dict[str, Any]) -> Dict[str, Any]:
    """Build an ADF paragraph block from one or more text/link nodes."""
    return {"type": "paragraph", "content": list(nodes)}


def _adf_doc_from_text(text: str) -> Dict[str, Any]:
    """Wrap a plain string in a minimal ADF doc — one paragraph per line so
    multi-line plain content (like the test issue) renders correctly."""
    paragraphs: List[Dict[str, Any]] = []
    for line in text.split("\n"):
        if line:
            paragraphs.append(_adf_paragraph(_adf_text(line)))
        else:
            paragraphs.append({"type": "paragraph", "content": []})
    return {"type": "doc", "version": 1, "content": paragraphs}


def _create_jira_issue(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
    summary: str,
    description: Optional[str] = None,
    description_doc: Optional[Dict[str, Any]] = None,
    priority: str = "Medium",
    issue_type: str = "Task",
) -> bool:
    """Create an issue in the selected Jira project.

    Pass either *description* (plain text — wrapped in a minimal ADF doc) or
    *description_doc* (a fully-built ADF document, used by the scan-complete
    flow to embed clickable links).
    """
    project_key = integration.get("project_key")
    if not project_key:
        log.warning("Jira project_key not set for org %s", organization_id)
        return False

    if description_doc is None:
        description_doc = _adf_doc_from_text(description or "")

    resp = _jira_api_request(
        organization_id=organization_id,
        integration=integration,
        method="POST",
        path="/rest/api/3/issue",
        json_body={
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": description_doc,
                "issuetype": {"name": issue_type},
                "priority": {"name": priority},
            }
        },
    )
    if resp and resp.status_code in (200, 201):
        issue_key = resp.json().get("key", "")
        log.info("Jira issue %s created for org %s: %s", issue_key, organization_id, summary)
        return True
    if resp:
        log.error("Jira issue creation failed %d: %s", resp.status_code, resp.text[:300])
    return False


def notify_jira_scan_complete(
    *,
    organization_id: UUID,
    scan_source: str = "",
    summary: Dict[str, Any],
    violations: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Create Jira issues for scan violations if connected. Returns True on success."""
    integration = _get_jira_integration(organization_id)
    if not integration or not integration.get("project_key"):
        return False

    violations = violations or []
    if not violations:
        return False

    total = summary.get("total_images", 0)
    compliance_rate = summary.get("compliance_rate", 0)
    channel = (scan_source or "scan").replace("_", " ").title()

    issue_summary = (
        f"[Dealer Intel] {channel} Scan — "
        f"{len(violations)} violation{'s' if len(violations) != 1 else ''} found "
        f"({compliance_rate}% compliance)"
    )

    # Build an ADF doc so the dashboard / per-match links are clickable in
    # the Jira issue — plain-string descriptions render as inert text.
    doc_content: List[Dict[str, Any]] = [
        _adf_paragraph(_adf_text(f"Scan Source: {channel}")),
        _adf_paragraph(_adf_text(f"Total Images Analyzed: {total}")),
        _adf_paragraph(_adf_text(f"Compliance Rate: {compliance_rate}%")),
        _adf_paragraph(_adf_text(f"Violations: {len(violations)}")),
        _adf_paragraph(
            _adf_text("Review violations: "),
            _adf_text(_violations_url(), href=_violations_url()),
        ),
        _adf_paragraph(
            _adf_text("Open dashboard: "),
            _adf_text(_matches_url(), href=_matches_url()),
        ),
        _adf_paragraph(_adf_text("--- Violations ---")),
    ]

    # One paragraph per violation; per-match link rendered as a trailing
    # "Review" hyperlink so the row stays scannable.
    for v in violations[:20]:
        row_text = (
            f"• {v.get('asset_name', '?')} at {v.get('distributor_name', '?')} "
            f"— {v.get('confidence_score', 0)}% confidence"
        )
        nodes: List[Dict[str, Any]] = [_adf_text(row_text)]
        detail_url = _match_detail_url(v.get("match_id"))
        if detail_url:
            nodes.append(_adf_text(" — "))
            nodes.append(_adf_text("Review", href=detail_url))
        doc_content.append(_adf_paragraph(*nodes))

    if len(violations) > 20:
        doc_content.append(_adf_paragraph(
            _adf_text(f"...and {len(violations) - 20} more — "),
            _adf_text("View all", href=_violations_url()),
        ))

    description_doc = {"type": "doc", "version": 1, "content": doc_content}
    priority = "High" if len(violations) >= 5 else "Medium"

    return _create_jira_issue(
        organization_id=organization_id,
        integration=integration,
        summary=issue_summary,
        description_doc=description_doc,
        priority=priority,
    )


def send_jira_test(*, organization_id: UUID) -> bool:
    """Create a test issue in Jira."""
    integration = _get_jira_integration(organization_id)
    if not integration:
        return False

    return _create_jira_issue(
        organization_id=organization_id,
        integration=integration,
        summary="[Dealer Intel] Connection Test — Jira Connected",
        description="This is a test issue from Dealer Intel.\n\n"
                    "Scan violations will appear as issues in this project automatically.",
        priority="Low",
    )
