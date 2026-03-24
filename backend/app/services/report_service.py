"""Compliance report generation — PDF and CSV exports."""
import base64
import csv
import io
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
    Image as RLImage,
)

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.reports")

_DEFAULT_LOGO = Path(__file__).resolve().parent.parent / "assets" / "logo_default.png"

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_DEFAULT_BRAND = "#334155"  # Slate — clean, minimal, professional

_GRAY = colors.HexColor("#6b7280")
_GREEN = colors.HexColor("#16a34a")
_RED = colors.HexColor("#dc2626")
_AMBER = colors.HexColor("#d97706")


def _derive_palette(hex_color: str) -> dict:
    """Derive a full report palette from a single brand hex color."""
    brand = colors.HexColor(hex_color)
    r, g, b = brand.red, brand.green, brand.blue
    dark = colors.Color(r * 0.35, g * 0.35, b * 0.35)
    light_bg = colors.Color(
        1.0 - (1.0 - r) * 0.06,
        1.0 - (1.0 - g) * 0.06,
        1.0 - (1.0 - b) * 0.06,
    )
    return {"brand": brand, "dark": dark, "light_bg": light_bg}


def _resolve_brand_color(organization_id: Optional[UUID] = None) -> str:
    """Fetch the org's chosen brand color or fall back to the default."""
    if organization_id:
        try:
            result = supabase.table("organizations")\
                .select("report_brand_color")\
                .eq("id", str(organization_id))\
                .single()\
                .execute()
            stored = (result.data or {}).get("report_brand_color")
            if stored and stored.startswith("#") and len(stored) in (4, 7):
                return stored
        except Exception:
            pass
    return _DEFAULT_BRAND

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _fetch_report_data(
    *,
    days: int = 30,
    campaign_id: Optional[UUID] = None,
    distributor_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Pull matches, stats, and trend data for report generation."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    q = supabase.table("recent_matches").select("*").gte("created_at", cutoff)
    if campaign_id:
        q = q.eq("campaign_id", str(campaign_id))
    if distributor_id:
        q = q.eq("distributor_id", str(distributor_id))
    matches_result = q.order("created_at", desc=True).execute()
    matches = matches_result.data or []

    total = len(matches)
    compliant = sum(1 for m in matches if m.get("compliance_status") == "compliant")
    violations = sum(1 for m in matches if m.get("compliance_status") == "violation")
    pending = sum(1 for m in matches if m.get("compliance_status") == "pending")
    compliance_rate = round(compliant / max(total, 1) * 100, 1)

    channel_counts: Dict[str, int] = {}
    distributor_counts: Dict[str, Dict[str, Any]] = {}
    daily_stats: Dict[str, Dict[str, int]] = {}

    for m in matches:
        ch = m.get("channel") or "unknown"
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

        d_name = m.get("distributor_name") or "Unknown"
        if d_name not in distributor_counts:
            distributor_counts[d_name] = {"total": 0, "violations": 0, "compliant": 0}
        distributor_counts[d_name]["total"] += 1
        if m.get("compliance_status") == "violation":
            distributor_counts[d_name]["violations"] += 1
        elif m.get("compliance_status") == "compliant":
            distributor_counts[d_name]["compliant"] += 1

        day = (m.get("created_at") or "")[:10]
        if day:
            if day not in daily_stats:
                daily_stats[day] = {"total": 0, "compliant": 0, "violations": 0}
            daily_stats[day]["total"] += 1
            if m.get("compliance_status") == "compliant":
                daily_stats[day]["compliant"] += 1
            elif m.get("compliance_status") == "violation":
                daily_stats[day]["violations"] += 1

    scope_label = "Full Organization"
    if campaign_id:
        try:
            c = supabase.table("campaigns").select("name").eq("id", str(campaign_id)).single().execute()
            scope_label = f"Campaign: {c.data.get('name', str(campaign_id))}"
        except Exception:
            scope_label = f"Campaign: {campaign_id}"
    if distributor_id:
        try:
            d = supabase.table("distributors").select("name").eq("id", str(distributor_id)).single().execute()
            scope_label = f"Distributor: {d.data.get('name', str(distributor_id))}"
        except Exception:
            scope_label = f"Distributor: {distributor_id}"

    return {
        "matches": matches,
        "total": total,
        "compliant": compliant,
        "violations": violations,
        "pending": pending,
        "compliance_rate": compliance_rate,
        "channel_counts": channel_counts,
        "distributor_counts": distributor_counts,
        "daily_stats": daily_stats,
        "scope_label": scope_label,
        "days": days,
    }


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    ("Asset", "asset_name"),
    ("Distributor", "distributor_name"),
    ("Campaign", "campaign_name"),
    ("Channel", "channel"),
    ("Confidence", "confidence_score"),
    ("Match Type", "match_type"),
    ("Compliance", "compliance_status"),
    ("Source URL", "source_url"),
    ("Discovered", "created_at"),
]


def generate_csv(
    *,
    days: int = 30,
    campaign_id: Optional[UUID] = None,
    distributor_id: Optional[UUID] = None,
    organization_id: Optional[UUID] = None,
) -> bytes:
    """Return CSV bytes for the compliance report."""
    data = _fetch_report_data(days=days, campaign_id=campaign_id, distributor_id=distributor_id)
    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["Dealer Intel Compliance Report"])
    writer.writerow([f"Scope: {data['scope_label']}"])
    writer.writerow([f"Period: Last {data['days']} days"])
    writer.writerow([f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"])
    writer.writerow([])
    writer.writerow([
        f"Total Matches: {data['total']}",
        f"Compliant: {data['compliant']}",
        f"Violations: {data['violations']}",
        f"Compliance Rate: {data['compliance_rate']}%",
    ])
    writer.writerow([])

    writer.writerow([col[0] for col in _CSV_COLUMNS])
    for m in data["matches"]:
        row = []
        for _, key in _CSV_COLUMNS:
            val = m.get(key, "")
            if key == "confidence_score" and val:
                val = f"{val}%"
            if key == "created_at" and val:
                val = val[:19].replace("T", " ")
            row.append(val or "")
        writer.writerow(row)

    if data["distributor_counts"]:
        writer.writerow([])
        writer.writerow(["--- Distributor Summary ---"])
        writer.writerow(["Distributor", "Total", "Compliant", "Violations", "Compliance Rate"])
        for name, counts in sorted(data["distributor_counts"].items(), key=lambda x: -x[1]["violations"]):
            rate = round(counts["compliant"] / max(counts["total"], 1) * 100, 1)
            writer.writerow([name, counts["total"], counts["compliant"], counts["violations"], f"{rate}%"])

    if data["channel_counts"]:
        writer.writerow([])
        writer.writerow(["--- Channel Breakdown ---"])
        writer.writerow(["Channel", "Matches"])
        for ch, count in sorted(data["channel_counts"].items(), key=lambda x: -x[1]):
            writer.writerow([ch, count])

    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------


def _styles(pal: dict):
    """Build custom paragraph styles from a derived palette."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontSize=22,
            textColor=pal["dark"],
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontSize=10,
            textColor=_GRAY,
            spaceAfter=16,
        ),
        "section": ParagraphStyle(
            "SectionHeader",
            parent=base["Heading2"],
            fontSize=13,
            textColor=pal["brand"],
            spaceBefore=20,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "BodyText",
            parent=base["Normal"],
            fontSize=9,
            textColor=pal["dark"],
            leading=13,
        ),
        "stat_label": ParagraphStyle(
            "StatLabel",
            parent=base["Normal"],
            fontSize=8,
            textColor=_GRAY,
        ),
        "stat_value": ParagraphStyle(
            "StatValue",
            parent=base["Normal"],
            fontSize=18,
            textColor=pal["dark"],
            leading=22,
        ),
        "th": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.white,
            leading=13,
        ),
    }


def _stat_cell(label: str, value: str, st) -> List:
    """Return a two-paragraph list for a stat KPI."""
    return [Paragraph(label, st["stat_label"]), Paragraph(str(value), st["stat_value"])]


def _resolve_logo(organization_id: Optional[UUID] = None) -> Optional[str]:
    """
    Resolve logo for PDF header — 3-tier priority:
      1. Org-uploaded logo (from organizations.logo_url)
      2. REPORT_LOGO_PATH env var
      3. Bundled default
    Returns a file path (str) suitable for ReportLab Image, or None.
    """
    # Tier 1: org-specific logo
    if organization_id:
        try:
            try:
                result = supabase.table("organizations")\
                    .select("logo_url")\
                    .eq("id", str(organization_id))\
                    .single()\
                    .execute()
            except Exception:
                result = None
            logo_url = (result.data or {}).get("logo_url") if result else None
            if logo_url:
                if logo_url.startswith("data:"):
                    header, b64 = logo_url.split(",", 1)
                    img_bytes = base64.b64decode(b64)
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.write(img_bytes)
                    tmp.flush()
                    return tmp.name
                resp = httpx.get(logo_url, timeout=10, follow_redirects=True)
                if resp.status_code == 200 and len(resp.content) > 0:
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.write(resp.content)
                    tmp.flush()
                    return tmp.name
        except Exception as e:
            log.warning("Could not load org logo for %s: %s", organization_id, e)

    # Tier 2: config file path
    settings = get_settings()
    if settings.report_logo_path:
        p = Path(settings.report_logo_path)
        if p.is_file():
            return str(p)
        log.warning("Configured report_logo_path not found: %s", p)

    # Tier 3: bundled default
    if _DEFAULT_LOGO.is_file():
        return str(_DEFAULT_LOGO)
    return None


def _build_header(
    elements: List,
    doc,
    st,
    data: Dict[str, Any],
    pal: dict,
    organization_id: Optional[UUID] = None,
) -> None:
    """Render the side-by-side logo + title header row."""
    logo_path = _resolve_logo(organization_id)
    subtitle_text = (
        f"{data['scope_label']}  &bull;  Last {data['days']} days  &bull;  "
        f"Generated {datetime.now(timezone.utc).strftime('%b %d, %Y %H:%M UTC')}"
    )

    title_block = [
        Paragraph("Compliance Report", st["title"]),
        Paragraph(subtitle_text, st["subtitle"]),
    ]

    if logo_path:
        logo = RLImage(logo_path, width=1.4 * inch, height=0.35 * inch)
        logo.hAlign = "LEFT"
        header_table = Table(
            [[[logo], title_block]],
            colWidths=[1.6 * inch, doc.width - 1.6 * inch],
        )
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
    else:
        elements.extend(title_block)

    elements.append(HRFlowable(width="100%", color=pal["brand"], thickness=1.5, spaceAfter=12))


def generate_pdf(
    *,
    days: int = 30,
    campaign_id: Optional[UUID] = None,
    distributor_id: Optional[UUID] = None,
    organization_id: Optional[UUID] = None,
) -> bytes:
    """Return PDF bytes for the compliance report."""
    data = _fetch_report_data(days=days, campaign_id=campaign_id, distributor_id=distributor_id)
    brand_hex = _resolve_brand_color(organization_id)
    pal = _derive_palette(brand_hex)
    st = _styles(pal)
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    elements: List = []

    # --- Header (logo + title side-by-side) ---
    _build_header(elements, doc, st, data, pal, organization_id=organization_id)

    # --- KPI cards row ---
    kpi_data = [
        [
            _stat_cell("Total Matches", str(data["total"]), st),
            _stat_cell("Compliant", str(data["compliant"]), st),
            _stat_cell("Violations", str(data["violations"]), st),
            _stat_cell("Pending", str(data["pending"]), st),
            _stat_cell("Compliance Rate", f"{data['compliance_rate']}%", st),
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[doc.width / 5] * 5)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pal["light_bg"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 0.5, pal["brand"]),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 14))

    # --- Distributor Breakdown ---
    if data["distributor_counts"]:
        elements.append(Paragraph("Distributor Compliance Summary", st["section"]))
        header = [
            Paragraph("<b>Distributor</b>", st["th"]),
            Paragraph("<b>Matches</b>", st["th"]),
            Paragraph("<b>Compliant</b>", st["th"]),
            Paragraph("<b>Violations</b>", st["th"]),
            Paragraph("<b>Rate</b>", st["th"]),
        ]
        rows = [header]
        for name, counts in sorted(data["distributor_counts"].items(), key=lambda x: -x[1]["violations"]):
            rate = round(counts["compliant"] / max(counts["total"], 1) * 100, 1)
            rate_color = _GREEN if rate >= 80 else (_AMBER if rate >= 60 else _RED)
            rows.append([
                Paragraph(str(name), st["body"]),
                Paragraph(str(counts["total"]), st["body"]),
                Paragraph(str(counts["compliant"]), st["body"]),
                Paragraph(str(counts["violations"]), st["body"]),
                Paragraph(f'<font color="{rate_color.hexval()}">{rate}%</font>', st["body"]),
            ])
        dist_table = Table(rows, colWidths=[doc.width * 0.35, doc.width * 0.15, doc.width * 0.15, doc.width * 0.15, doc.width * 0.2])
        dist_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), pal["brand"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pal["light_bg"]]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(dist_table)
        elements.append(Spacer(1, 14))

    # --- Channel Breakdown ---
    if data["channel_counts"]:
        elements.append(Paragraph("Matches by Channel", st["section"]))
        ch_header = [
            Paragraph("<b>Channel</b>", st["th"]),
            Paragraph("<b>Matches</b>", st["th"]),
        ]
        ch_rows = [ch_header]
        for ch, count in sorted(data["channel_counts"].items(), key=lambda x: -x[1]):
            ch_rows.append([
                Paragraph(ch.replace("_", " ").title(), st["body"]),
                Paragraph(str(count), st["body"]),
            ])
        ch_table = Table(ch_rows, colWidths=[doc.width * 0.5, doc.width * 0.5])
        ch_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), pal["brand"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pal["light_bg"]]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(ch_table)
        elements.append(Spacer(1, 14))

    # --- Violations Detail ---
    violation_matches = [m for m in data["matches"] if m.get("compliance_status") == "violation"]
    if violation_matches:
        elements.append(Paragraph(f"Violation Details ({len(violation_matches)})", st["section"]))
        v_header = [
            Paragraph("<b>Asset</b>", st["th"]),
            Paragraph("<b>Distributor</b>", st["th"]),
            Paragraph("<b>Channel</b>", st["th"]),
            Paragraph("<b>Confidence</b>", st["th"]),
            Paragraph("<b>Source URL</b>", st["th"]),
            Paragraph("<b>Discovered</b>", st["th"]),
        ]
        v_rows = [v_header]
        for m in violation_matches[:50]:
            source_url = m.get("source_url") or ""
            if len(source_url) > 40:
                source_url = source_url[:37] + "..."
            discovered = (m.get("created_at") or "")[:10]
            v_rows.append([
                Paragraph(str(m.get("asset_name") or "Unknown"), st["body"]),
                Paragraph(str(m.get("distributor_name") or "Unknown"), st["body"]),
                Paragraph((m.get("channel") or "").replace("_", " ").title(), st["body"]),
                Paragraph(f"{m.get('confidence_score', 0)}%", st["body"]),
                Paragraph(source_url, st["body"]),
                Paragraph(discovered, st["body"]),
            ])
        col_w = doc.width
        v_table = Table(v_rows, colWidths=[col_w * 0.18, col_w * 0.17, col_w * 0.12, col_w * 0.1, col_w * 0.28, col_w * 0.15])
        v_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _RED),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fef2f2")]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(v_table)
        if len(violation_matches) > 50:
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(
                f"Showing first 50 of {len(violation_matches)} violations. Export CSV for full data.",
                st["body"],
            ))
        elements.append(Spacer(1, 14))

    # --- All Matches Table ---
    elements.append(Paragraph(f"All Matches ({data['total']})", st["section"]))
    a_header = [
        Paragraph("<b>Asset</b>", st["th"]),
        Paragraph("<b>Distributor</b>", st["th"]),
        Paragraph("<b>Channel</b>", st["th"]),
        Paragraph("<b>Confidence</b>", st["th"]),
        Paragraph("<b>Type</b>", st["th"]),
        Paragraph("<b>Status</b>", st["th"]),
        Paragraph("<b>Discovered</b>", st["th"]),
    ]
    a_rows = [a_header]
    display_limit = min(len(data["matches"]), 100)
    for m in data["matches"][:display_limit]:
        status = m.get("compliance_status", "pending")
        status_color = _GREEN if status == "compliant" else (_RED if status == "violation" else _GRAY)
        discovered = (m.get("created_at") or "")[:10]
        a_rows.append([
            Paragraph(str(m.get("asset_name") or "Unknown"), st["body"]),
            Paragraph(str(m.get("distributor_name") or "Unknown"), st["body"]),
            Paragraph((m.get("channel") or "").replace("_", " ").title(), st["body"]),
            Paragraph(f"{m.get('confidence_score', 0)}%", st["body"]),
            Paragraph(str(m.get("match_type") or ""), st["body"]),
            Paragraph(f'<font color="{status_color.hexval()}">{status.title()}</font>', st["body"]),
            Paragraph(discovered, st["body"]),
        ])
    col_w = doc.width
    a_table = Table(a_rows, colWidths=[
        col_w * 0.18, col_w * 0.17, col_w * 0.12, col_w * 0.11, col_w * 0.1, col_w * 0.12, col_w * 0.2
    ])
    a_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), pal["brand"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pal["light_bg"]]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(a_table)
    if data["total"] > display_limit:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(
            f"Showing first {display_limit} of {data['total']} matches. Export CSV for full data.",
            st["body"],
        ))

    # --- Footer ---
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", color=_GRAY, thickness=0.5, spaceAfter=6))
    elements.append(Paragraph(
        "Generated by Dealer Intel &mdash; AI-powered campaign asset compliance monitoring",
        ParagraphStyle("Footer", parent=st["body"], fontSize=7, textColor=_GRAY, alignment=1),
    ))

    doc.build(elements)
    return buf.getvalue()
