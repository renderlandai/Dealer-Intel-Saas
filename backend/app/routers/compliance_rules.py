"""Compliance rules CRUD — manage brand-compliance checks used during scans."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..plan_enforcement import OrgPlan, get_org_plan, check_compliance_rules_limit

log = logging.getLogger("dealer_intel.compliance_rules")

router = APIRouter(prefix="/compliance-rules", tags=["compliance-rules"])

VALID_RULE_TYPES = {"required_element", "forbidden_element", "date_check"}
VALID_SEVERITIES = {"info", "warning", "critical"}


class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    rule_type: str
    rule_config: Dict[str, Any]
    severity: str = "warning"


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[str] = None
    rule_config: Optional[Dict[str, Any]] = None
    severity: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("")
async def list_rules(
    active_only: bool = True,
    user: AuthUser = Depends(get_current_user),
):
    """List compliance rules for the user's organization."""
    q = supabase.table("compliance_rules") \
        .select("*") \
        .eq("organization_id", str(user.org_id)) \
        .order("created_at", desc=True)

    if active_only:
        q = q.eq("is_active", True)

    result = q.execute()
    return result.data


@router.get("/{rule_id}")
async def get_rule(
    rule_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """Get a single compliance rule."""
    result = supabase.table("compliance_rules") \
        .select("*") \
        .eq("id", str(rule_id)) \
        .eq("organization_id", str(user.org_id)) \
        .maybe_single() \
        .execute()

    if not result.data:
        raise HTTPException(404, "Compliance rule not found")

    return result.data


@router.post("")
async def create_rule(
    body: RuleCreate,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Create a new compliance rule. Subject to plan limits."""
    check_compliance_rules_limit(op)

    if body.rule_type not in VALID_RULE_TYPES:
        raise HTTPException(400, f"rule_type must be one of: {', '.join(sorted(VALID_RULE_TYPES))}")
    if body.severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}")

    result = supabase.table("compliance_rules").insert({
        "organization_id": str(user.org_id),
        "name": body.name,
        "description": body.description,
        "rule_type": body.rule_type,
        "rule_config": body.rule_config,
        "severity": body.severity,
    }).execute()

    if not result.data:
        raise HTTPException(500, "Failed to create compliance rule")

    log.info("Compliance rule created: %s (org %s)", result.data[0]["id"], user.org_id)
    return result.data[0]


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: UUID,
    body: RuleUpdate,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Update a compliance rule."""
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "No fields to update")

    if "rule_type" in data and data["rule_type"] not in VALID_RULE_TYPES:
        raise HTTPException(400, f"rule_type must be one of: {', '.join(sorted(VALID_RULE_TYPES))}")
    if "severity" in data and data["severity"] not in VALID_SEVERITIES:
        raise HTTPException(400, f"severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}")

    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    result = supabase.table("compliance_rules") \
        .update(data) \
        .eq("id", str(rule_id)) \
        .eq("organization_id", str(user.org_id)) \
        .execute()

    if not result.data:
        raise HTTPException(404, "Compliance rule not found")

    log.info("Compliance rule %s updated: %s", rule_id, list(data.keys()))
    return result.data[0]


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: UUID,
    user: AuthUser = Depends(get_current_user),
):
    """Delete a compliance rule."""
    result = supabase.table("compliance_rules") \
        .delete() \
        .eq("id", str(rule_id)) \
        .eq("organization_id", str(user.org_id)) \
        .execute()

    if not result.data:
        raise HTTPException(404, "Compliance rule not found")

    log.info("Compliance rule %s deleted (org %s)", rule_id, user.org_id)
    return {"status": "deleted", "rule_id": str(rule_id)}
