"""Compliance report download endpoints — PDF and CSV."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from ..auth import AuthUser, get_current_user
from ..services.report_service import generate_csv, generate_pdf
from ..plan_enforcement import OrgPlan, get_org_plan, check_pdf_reports

log = logging.getLogger("dealer_intel.reports")

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/compliance")
async def download_compliance_report(
    format: str = Query("pdf", pattern="^(pdf|csv)$"),
    days: int = Query(30, ge=1, le=365),
    campaign_id: Optional[UUID] = None,
    distributor_id: Optional[UUID] = None,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """
    Generate and download a compliance report.

    - **format**: `pdf` or `csv`
    - **days**: lookback window (1–365, default 30)
    - **campaign_id**: scope to a single campaign (optional)
    - **distributor_id**: scope to a single distributor (optional)
    - **organization_id**: org whose logo to use in PDF header (optional)
    """
    if format == "pdf":
        check_pdf_reports(op)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    organization_id = user.org_id

    scope = "full"
    if campaign_id:
        scope = "campaign"
    elif distributor_id:
        scope = "distributor"

    log.info(
        "Generating %s report — scope=%s, days=%d, campaign=%s, distributor=%s, org=%s",
        format, scope, days, campaign_id, distributor_id, organization_id,
    )

    if format == "csv":
        content = generate_csv(
            days=days,
            campaign_id=campaign_id,
            distributor_id=distributor_id,
            organization_id=organization_id,
        )
        filename = f"dealer_intel_compliance_{scope}_{timestamp}.csv"
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    content = generate_pdf(
        days=days,
        campaign_id=campaign_id,
        distributor_id=distributor_id,
        organization_id=organization_id,
    )
    filename = f"dealer_intel_compliance_{scope}_{timestamp}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
