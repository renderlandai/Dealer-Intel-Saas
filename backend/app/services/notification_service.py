"""Email notification service via Resend — single HTTP POST, zero SMTP config."""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.notifications")

RESEND_URL = "https://api.resend.com/emails"


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
            rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('asset_name', 'Unknown')}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('distributor_name', 'Unknown')}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('channel', channel)}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{v.get('confidence_score', 0)}%</td>
              <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#6b7280;">{v.get('compliance_summary', '')}</td>
            </tr>"""

        truncation = ""
        if violation_count > 20:
            truncation = f'<p style="color:#6b7280;font-size:12px;margin-top:8px;">Showing 20 of {violation_count} violations. Log in to view all.</p>'

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
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        {truncation}"""

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
