"""HubSpot two-way sync — inbound dealer import + outbound compliance push."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase

log = logging.getLogger("dealer_intel.hubspot_sync")

HS_API_BASE = "https://api.hubapi.com"

CUSTOM_PROPERTIES: List[Dict[str, Any]] = [
    {
        "name": "dealer_intel_id",
        "label": "Dealer Intel ID",
        "type": "string",
        "fieldType": "text",
        "groupName": "companyinformation",
        "description": "Links this Company to a dealer in Dealer Intel.",
    },
    {
        "name": "compliance_score",
        "label": "Compliance Score",
        "type": "number",
        "fieldType": "number",
        "groupName": "companyinformation",
        "description": "Latest compliance score (%) from Dealer Intel scans.",
    },
    {
        "name": "open_violations",
        "label": "Open Violations",
        "type": "number",
        "fieldType": "number",
        "groupName": "companyinformation",
        "description": "Number of open compliance violations from Dealer Intel.",
    },
    {
        "name": "has_compliance_violation",
        "label": "Has Compliance Violation",
        "type": "enumeration",
        "fieldType": "booleancheckbox",
        "groupName": "companyinformation",
        "description": "True when this dealer has open compliance violations.",
        "options": [
            {"label": "True", "value": "true"},
            {"label": "False", "value": "false"},
        ],
    },
    {
        "name": "last_scan_date",
        "label": "Last Scan Date",
        "type": "datetime",
        "fieldType": "date",
        "groupName": "companyinformation",
        "description": "When Dealer Intel last scanned this dealer.",
    },
]

INBOUND_FIELD_MAP: Dict[str, str] = {
    "name": "name",
    "domain": "website_url",
    "state": "region",
}


def _get_hubspot_integration(organization_id: UUID) -> Optional[Dict[str, Any]]:
    """Fetch the HubSpot integration row for an org."""
    try:
        result = supabase.table("integrations")\
            .select("access_token, refresh_token, workspace_name, hubspot_portal_id, hubspot_sync_filter, last_synced_at")\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "hubspot")\
            .maybe_single()\
            .execute()
        return result.data if result.data else None
    except Exception:
        return None


def _refresh_hubspot_token(organization_id: UUID, refresh_token: str) -> Optional[str]:
    """Refresh an expired HubSpot access token. Returns new token or None."""
    settings = get_settings()
    try:
        resp = httpx.post(f"{HS_API_BASE}/oauth/v1/token", data={
            "grant_type": "refresh_token",
            "client_id": settings.hubspot_client_id,
            "client_secret": settings.hubspot_client_secret,
            "refresh_token": refresh_token,
        }, timeout=15)
        data = resp.json()
        new_token = data.get("access_token")
        new_refresh = data.get("refresh_token", refresh_token)
        if not new_token:
            log.error("HubSpot token refresh returned no access_token: %s", data)
            return None
        supabase.table("integrations").update({
            "access_token": new_token,
            "refresh_token": new_refresh,
        }).eq("organization_id", str(organization_id))\
          .eq("provider", "hubspot")\
          .execute()
        return new_token
    except Exception as e:
        log.error("HubSpot token refresh failed: %s", e)
        return None


def _hs_api_request(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
    method: str,
    path: str,
    json_body: Any = None,
    params: Optional[Dict[str, str]] = None,
) -> Optional[httpx.Response]:
    """Make a HubSpot API request with automatic token refresh on 401."""
    token = integration["access_token"]
    url = f"{HS_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = httpx.request(method, url, headers=headers, json=json_body, params=params, timeout=30)
    except Exception as e:
        log.error("HubSpot API request failed: %s", e)
        return None

    if resp.status_code == 401:
        new_token = _refresh_hubspot_token(organization_id, integration.get("refresh_token", ""))
        if not new_token:
            return resp
        headers["Authorization"] = f"Bearer {new_token}"
        integration["access_token"] = new_token
        try:
            resp = httpx.request(method, url, headers=headers, json=json_body, params=params, timeout=30)
        except Exception as e:
            log.error("HubSpot API retry failed: %s", e)
            return None

    return resp


# ─── Auto-provision custom properties on connect ─────────────────


def provision_custom_properties(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
) -> Dict[str, Any]:
    """Create Dealer Intel custom properties on the HubSpot Company object.

    Uses the Properties API — idempotent (skips properties that already exist).
    """
    results = {"created": 0, "skipped": 0, "failed": 0, "errors": []}

    for prop_def in CUSTOM_PROPERTIES:
        prop_name = prop_def["name"]

        check_resp = _hs_api_request(
            organization_id=organization_id,
            integration=integration,
            method="GET",
            path=f"/crm/v3/properties/companies/{prop_name}",
        )

        if check_resp and check_resp.status_code == 200:
            log.debug("HubSpot property %s already exists — skipping", prop_name)
            results["skipped"] += 1
            continue

        resp = _hs_api_request(
            organization_id=organization_id,
            integration=integration,
            method="POST",
            path="/crm/v3/properties/companies",
            json_body=prop_def,
        )

        if resp and resp.status_code in (200, 201):
            log.info("Created HubSpot custom property: %s", prop_name)
            results["created"] += 1
        elif resp and resp.status_code == 409:
            log.debug("HubSpot property %s already exists (409) — skipping", prop_name)
            results["skipped"] += 1
        else:
            status = resp.status_code if resp else "no response"
            body = resp.text[:200] if resp else ""
            log.warning("Failed to create HubSpot property %s: %s %s", prop_name, status, body)
            results["failed"] += 1
            results["errors"].append(f"{prop_name}: HTTP {status}")

    log.info(
        "HubSpot property provisioning for org %s: created=%d skipped=%d failed=%d",
        organization_id, results["created"], results["skipped"], results["failed"],
    )
    return results


# ─── Discover filter options from HubSpot Company properties ─────


def fetch_company_filter_options(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
) -> Dict[str, Any]:
    """Fetch Company properties with enumeration values for use as sync filters.

    Returns the 'type' and 'industry' picklist values that users can use
    to decide which Companies to import as dealers.
    """
    result: Dict[str, Any] = {"company_types": [], "industries": []}

    for prop_name, result_key in [("type", "company_types"), ("industry", "industries")]:
        resp = _hs_api_request(
            organization_id=organization_id,
            integration=integration,
            method="GET",
            path=f"/crm/v3/properties/companies/{prop_name}",
        )

        if not resp or resp.status_code != 200:
            continue

        data = resp.json()
        for opt in data.get("options", []):
            if not opt.get("hidden"):
                result[result_key].append({
                    "label": opt.get("label", opt.get("value", "")),
                    "value": opt.get("value", ""),
                    "filter": f"{prop_name}={opt['value']}",
                })

    return result


# ─── Inbound: HubSpot Companies → distributors ──────────────────


def sync_dealers_from_hubspot(organization_id: UUID) -> Dict[str, Any]:
    """Pull Companies from HubSpot and upsert into the distributors table.

    Respects the hubspot_sync_filter saved on the integration row.
    """
    integration = _get_hubspot_integration(organization_id)
    if not integration:
        return {"error": "HubSpot not connected", "synced": 0}

    sync_filter = integration.get("hubspot_sync_filter") or ""
    if not sync_filter:
        log.info("No sync filter configured for org %s — skipping HubSpot inbound sync", organization_id)
        return {"synced": 0, "message": "No sync filter configured. Select which Companies to import in Settings."}

    filter_parts = sync_filter.split("=", 1)
    if len(filter_parts) != 2:
        return {"synced": 0, "message": "Invalid sync filter format."}

    filter_prop, filter_value = filter_parts

    hs_properties = list(INBOUND_FIELD_MAP.keys()) + ["hs_object_id"]

    search_body: Dict[str, Any] = {
        "filterGroups": [{
            "filters": [{
                "propertyName": filter_prop,
                "operator": "EQ",
                "value": filter_value,
            }]
        }],
        "properties": hs_properties,
        "limit": 100,
    }

    last_synced = integration.get("last_synced_at")
    if last_synced:
        search_body["filterGroups"][0]["filters"].append({
            "propertyName": "hs_lastmodifieddate",
            "operator": "GTE",
            "value": last_synced,
        })

    all_results: List[Dict[str, Any]] = []
    after = None

    for _ in range(20):  # max 2000 companies
        if after:
            search_body["after"] = after

        resp = _hs_api_request(
            organization_id=organization_id,
            integration=integration,
            method="POST",
            path="/crm/v3/objects/companies/search",
            json_body=search_body,
        )

        if not resp or resp.status_code != 200:
            error_msg = resp.text[:200] if resp else "no response"
            log.error("HubSpot search failed: %s", error_msg)
            return {"error": f"HubSpot search failed ({resp.status_code if resp else 'N/A'})", "synced": 0}

        data = resp.json()
        all_results.extend(data.get("results", []))

        paging = data.get("paging", {}).get("next", {})
        after = paging.get("after")
        if not after:
            break

    if not all_results:
        _touch_sync_timestamp(organization_id)
        return {"synced": 0, "created": 0, "updated": 0, "message": "No new/modified companies"}

    results = {"synced": 0, "created": 0, "updated": 0, "errors": 0}

    for company in all_results:
        hs_id = company.get("id")
        props = company.get("properties", {})
        if not hs_id:
            continue

        dealer_data: Dict[str, Any] = {}
        for hs_field, di_field in INBOUND_FIELD_MAP.items():
            value = props.get(hs_field)
            if value is not None:
                if hs_field == "domain" and value and not value.startswith("http"):
                    value = f"https://{value}"
                dealer_data[di_field] = value

        if not dealer_data.get("name"):
            continue

        try:
            existing = supabase.table("distributors")\
                .select("id")\
                .eq("organization_id", str(organization_id))\
                .eq("hubspot_id", hs_id)\
                .maybe_single()\
                .execute()

            now = datetime.now(timezone.utc).isoformat()

            if existing and existing.data:
                dealer_data["hubspot_synced_at"] = now
                dealer_data["updated_at"] = now
                supabase.table("distributors")\
                    .update(dealer_data)\
                    .eq("id", existing.data["id"])\
                    .execute()
                results["updated"] += 1
            else:
                name_match = supabase.table("distributors")\
                    .select("id")\
                    .eq("organization_id", str(organization_id))\
                    .eq("name", dealer_data["name"])\
                    .is_("hubspot_id", "null")\
                    .maybe_single()\
                    .execute()

                if name_match and name_match.data:
                    dealer_data["hubspot_id"] = hs_id
                    dealer_data["hubspot_synced_at"] = now
                    dealer_data["updated_at"] = now
                    supabase.table("distributors")\
                        .update(dealer_data)\
                        .eq("id", name_match.data["id"])\
                        .execute()
                    results["updated"] += 1
                    log.info("Linked existing dealer '%s' to HubSpot Company %s", dealer_data["name"], hs_id)
                else:
                    dealer_data["organization_id"] = str(organization_id)
                    dealer_data["hubspot_id"] = hs_id
                    dealer_data["hubspot_synced_at"] = now
                    dealer_data["status"] = "active"
                    supabase.table("distributors")\
                        .insert(dealer_data)\
                        .execute()
                    results["created"] += 1

            results["synced"] += 1

        except Exception as e:
            log.warning("Failed to sync HubSpot Company %s: %s", hs_id, e)
            results["errors"] += 1

    _touch_sync_timestamp(organization_id)

    log.info(
        "HubSpot inbound sync for org %s: %d synced (%d created, %d updated, %d errors)",
        organization_id, results["synced"], results["created"],
        results["updated"], results.get("errors", 0),
    )
    return results


def _touch_sync_timestamp(organization_id: UUID) -> None:
    """Update the last_synced_at on the HubSpot integration row."""
    try:
        supabase.table("integrations")\
            .update({"last_synced_at": datetime.now(timezone.utc).isoformat()})\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "hubspot")\
            .execute()
    except Exception:
        pass


# ─── Outbound: compliance data → HubSpot Company properties ─────


def push_compliance_to_hubspot(
    *,
    organization_id: UUID,
    distributor_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Push compliance scores to HubSpot Company custom properties.

    If distributor_ids is None, pushes for all distributors with a hubspot_id.
    """
    integration = _get_hubspot_integration(organization_id)
    if not integration:
        return {"error": "HubSpot not connected", "pushed": 0}

    query = supabase.table("distributors")\
        .select("id, hubspot_id")\
        .eq("organization_id", str(organization_id))\
        .not_.is_("hubspot_id", "null")

    if distributor_ids:
        query = query.in_("id", distributor_ids)

    try:
        dist_rows = query.execute()
    except Exception as e:
        log.error("Failed to query distributors for HubSpot push: %s", e)
        return {"error": str(e), "pushed": 0}

    dealers = dist_rows.data or []
    if not dealers:
        return {"pushed": 0, "message": "No HubSpot-linked distributors"}

    dealer_ids = [d["id"] for d in dealers]

    try:
        matches_data = supabase.table("matches")\
            .select("distributor_id, compliance_status")\
            .in_("distributor_id", dealer_ids)\
            .execute()
    except Exception as e:
        log.error("Failed to query match compliance: %s", e)
        return {"error": str(e), "pushed": 0}

    compliance_map: Dict[str, Dict[str, int]] = {}
    for m in (matches_data.data or []):
        did = m.get("distributor_id")
        if not did:
            continue
        if did not in compliance_map:
            compliance_map[did] = {"total": 0, "compliant": 0, "violations": 0}
        compliance_map[did]["total"] += 1
        status = m.get("compliance_status", "")
        if status == "compliant":
            compliance_map[did]["compliant"] += 1
        elif status == "violation":
            compliance_map[did]["violations"] += 1

    results = {"pushed": 0, "skipped": 0, "errors": 0}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    for dealer in dealers:
        hs_id = dealer["hubspot_id"]
        di_id = dealer["id"]
        stats = compliance_map.get(di_id, {"total": 0, "compliant": 0, "violations": 0})

        total = stats["total"]
        violations = stats["violations"]
        rate = round(stats["compliant"] / max(total, 1) * 100, 1) if total > 0 else 0.0

        properties = {
            "dealer_intel_id": di_id,
            "compliance_score": rate,
            "open_violations": violations,
            "has_compliance_violation": "true" if violations > 0 else "false",
            "last_scan_date": now_ms,
        }

        resp = _hs_api_request(
            organization_id=organization_id,
            integration=integration,
            method="PATCH",
            path=f"/crm/v3/objects/companies/{hs_id}",
            json_body={"properties": properties},
        )

        if resp and resp.status_code in (200, 201):
            results["pushed"] += 1
        elif resp and resp.status_code == 404:
            log.debug("HubSpot Company %s not found — skipping", hs_id)
            results["skipped"] += 1
        else:
            status_code = resp.status_code if resp else "no response"
            log.warning("Failed to push compliance for %s to HubSpot: %s", di_id, status_code)
            results["errors"] += 1

    log.info(
        "HubSpot compliance push for org %s: %d pushed, %d skipped, %d errors",
        organization_id, results["pushed"], results["skipped"], results["errors"],
    )
    return results


# ─── Scheduled sync for all connected orgs ───────────────────────


async def run_hubspot_sync_all() -> None:
    """Run inbound dealer sync for every org with an active HubSpot integration.

    Called by APScheduler on a cron schedule.
    """
    try:
        rows = supabase.table("integrations")\
            .select("organization_id")\
            .eq("provider", "hubspot")\
            .execute()
    except Exception:
        log.warning("Could not query HubSpot integrations for scheduled sync")
        return

    orgs = rows.data or []
    if not orgs:
        return

    log.info("Running scheduled HubSpot sync for %d org(s)", len(orgs))

    for row in orgs:
        org_id = row.get("organization_id")
        if not org_id:
            continue
        try:
            result = sync_dealers_from_hubspot(UUID(org_id))
            log.info("HubSpot sync org %s: %s", org_id, result)
        except Exception:
            log.exception("HubSpot sync failed for org %s", org_id)
