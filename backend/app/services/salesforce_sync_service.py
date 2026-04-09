"""Salesforce two-way sync — inbound dealer import + outbound compliance push."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase
from .notification_service import (
    _get_salesforce_integration,
    _sf_api_request,
)

log = logging.getLogger("dealer_intel.salesforce_sync")

SF_API_VERSION = "v59.0"

CUSTOM_FIELDS: List[Dict[str, Any]] = [
    {
        "FullName": "Account.Dealer_Intel_ID__c",
        "Metadata": {
            "label": "Dealer Intel ID",
            "type": "Text",
            "length": 36,
            "externalId": True,
            "unique": True,
            "required": False,
            "description": "Links this Account to a dealer in Dealer Intel.",
        },
    },
    {
        "FullName": "Account.Compliance_Score__c",
        "Metadata": {
            "label": "Compliance Score",
            "type": "Percent",
            "precision": 5,
            "scale": 1,
            "required": False,
            "description": "Latest compliance score from Dealer Intel scans.",
        },
    },
    {
        "FullName": "Account.Open_Violations__c",
        "Metadata": {
            "label": "Open Violations",
            "type": "Number",
            "precision": 4,
            "scale": 0,
            "required": False,
            "description": "Number of open compliance violations from Dealer Intel.",
        },
    },
    {
        "FullName": "Account.Has_Compliance_Violation__c",
        "Metadata": {
            "label": "Has Compliance Violation",
            "type": "Checkbox",
            "defaultValue": False,
            "required": False,
            "description": "True when this dealer has open compliance violations.",
        },
    },
    {
        "FullName": "Account.Last_Scan_Date__c",
        "Metadata": {
            "label": "Last Scan Date",
            "type": "DateTime",
            "required": False,
            "description": "When Dealer Intel last scanned this dealer.",
        },
    },
    {
        "FullName": "Account.Facebook_URL__c",
        "Metadata": {
            "label": "Facebook URL",
            "type": "Url",
            "required": False,
            "description": "Facebook page URL for Dealer Intel scanning.",
        },
    },
    {
        "FullName": "Account.Instagram_URL__c",
        "Metadata": {
            "label": "Instagram URL",
            "type": "Url",
            "required": False,
            "description": "Instagram profile URL for Dealer Intel scanning.",
        },
    },
    {
        "FullName": "Account.YouTube_URL__c",
        "Metadata": {
            "label": "YouTube URL",
            "type": "Url",
            "required": False,
            "description": "YouTube channel URL for Dealer Intel scanning.",
        },
    },
    {
        "FullName": "Account.Google_Ads_Advertiser_ID__c",
        "Metadata": {
            "label": "Google Ads Advertiser ID",
            "type": "Text",
            "length": 50,
            "required": False,
            "description": "Google Ads advertiser ID for Dealer Intel scanning.",
        },
    },
]

# SF Account field → distributors column
INBOUND_FIELD_MAP: Dict[str, str] = {
    "Name": "name",
    "Website": "website_url",
    "AccountNumber": "code",
    "BillingState": "region",
    "Facebook_URL__c": "facebook_url",
    "Instagram_URL__c": "instagram_url",
    "YouTube_URL__c": "youtube_url",
    "Google_Ads_Advertiser_ID__c": "google_ads_advertiser_id",
}

SF_SOQL_FIELDS = "Id, " + ", ".join(INBOUND_FIELD_MAP.keys())


# ─── Auto-provision custom fields on connect ────────────────────


def provision_custom_fields(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
) -> Dict[str, Any]:
    """Create Dealer Intel custom fields on the SF Account object.

    Uses the Tooling API — idempotent (skips fields that already exist).
    Returns a summary dict with created/skipped/failed counts.
    """
    results = {"created": 0, "skipped": 0, "failed": 0, "errors": []}

    for field_def in CUSTOM_FIELDS:
        full_name = field_def["FullName"]
        api_name = full_name.split(".")[-1]

        # Check if field already exists
        check_resp = _sf_api_request(
            organization_id=organization_id,
            integration=integration,
            method="GET",
            path=(
                f"/services/data/{SF_API_VERSION}/tooling/query"
                f"?q=SELECT+Id+FROM+CustomField+WHERE+DeveloperName='{api_name.replace('__c', '')}'"
                f"+AND+TableEnumOrId='Account'"
            ),
        )

        if check_resp and check_resp.status_code == 200:
            records = check_resp.json().get("records", [])
            if records:
                log.debug("SF field %s already exists — skipping", api_name)
                results["skipped"] += 1
                continue

        resp = _sf_api_request(
            organization_id=organization_id,
            integration=integration,
            method="POST",
            path=f"/services/data/{SF_API_VERSION}/tooling/sobjects/CustomField",
            json_body=field_def,
        )

        if resp and resp.status_code in (200, 201):
            log.info("Created SF custom field: %s", api_name)
            results["created"] += 1
        elif resp and resp.status_code == 400:
            body = resp.json() if resp.text else []
            errors = body if isinstance(body, list) else [body]
            already_exists = any(
                "duplicate" in str(e).lower() or "already exists" in str(e).lower()
                for e in errors
            )
            if already_exists:
                log.debug("SF field %s already exists (400) — skipping", api_name)
                results["skipped"] += 1
            else:
                log.warning("Failed to create SF field %s: %s", api_name, resp.text[:300])
                results["failed"] += 1
                results["errors"].append(f"{api_name}: {resp.text[:200]}")
        else:
            status = resp.status_code if resp else "no response"
            log.warning("Failed to create SF field %s: %s", api_name, status)
            results["failed"] += 1
            results["errors"].append(f"{api_name}: HTTP {status}")

    log.info(
        "SF field provisioning for org %s: created=%d skipped=%d failed=%d",
        organization_id, results["created"], results["skipped"], results["failed"],
    )
    return results


# ─── Discover filter options from SF Account describe ────────────


def fetch_account_filter_options(
    *,
    organization_id: UUID,
    integration: Dict[str, Any],
) -> Dict[str, Any]:
    """Query SF Account describe to return Record Types and Type picklist values."""
    resp = _sf_api_request(
        organization_id=organization_id,
        integration=integration,
        method="GET",
        path=f"/services/data/{SF_API_VERSION}/sobjects/Account/describe",
    )

    result: Dict[str, Any] = {"record_types": [], "account_types": []}

    if not resp or resp.status_code != 200:
        log.warning("SF Account describe failed: %s", resp.status_code if resp else "no response")
        return result

    data = resp.json()

    for rt in data.get("recordTypeInfos", []):
        if rt.get("available") and rt.get("name") != "Master":
            result["record_types"].append({
                "name": rt["name"],
                "filter": f"RecordType.Name = '{rt['name']}'",
            })

    for field in data.get("fields", []):
        if field.get("name") == "Type":
            for pv in field.get("picklistValues", []):
                if pv.get("active"):
                    result["account_types"].append({
                        "label": pv["label"],
                        "value": pv["value"],
                        "filter": f"Type = '{pv['value']}'",
                    })
            break

    return result


# ─── Inbound: Salesforce Accounts → distributors ────────────────


def sync_dealers_from_salesforce(organization_id: UUID) -> Dict[str, Any]:
    """Pull Accounts from Salesforce and upsert into the distributors table.

    Respects the salesforce_sync_filter saved on the integration row.
    Returns a summary dict with created/updated/skipped/error counts.
    """
    integration = _get_salesforce_integration(organization_id)
    if not integration:
        return {"error": "Salesforce not connected", "synced": 0}

    # Get the last sync timestamp and filter
    try:
        int_row = supabase.table("integrations")\
            .select("last_synced_at, salesforce_sync_filter")\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "salesforce")\
            .maybe_single()\
            .execute()
        row_data = int_row.data or {}
        last_synced = row_data.get("last_synced_at")
        sync_filter = row_data.get("salesforce_sync_filter") or ""
    except Exception:
        last_synced = None
        sync_filter = ""

    if not sync_filter:
        log.info("No sync filter configured for org %s — skipping inbound sync", organization_id)
        return {"synced": 0, "message": "No sync filter configured. Select which Accounts to import in Settings."}

    # Build SOQL with filter and optional incremental timestamp
    where_clauses: List[str] = [sync_filter]
    if last_synced:
        where_clauses.append(f"LastModifiedDate > {last_synced}")

    soql = f"SELECT {SF_SOQL_FIELDS} FROM Account"
    if where_clauses:
        soql += " WHERE " + " AND ".join(where_clauses)
    soql += " ORDER BY LastModifiedDate ASC LIMIT 2000"

    instance_url = integration["instance_url"]
    token = integration["access_token"]

    try:
        query_resp = httpx.get(
            f"{instance_url}/services/data/{SF_API_VERSION}/query",
            params={"q": soql},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
    except Exception as e:
        log.error("Salesforce SOQL query failed: %s", e)
        return {"error": str(e), "synced": 0}

    if query_resp.status_code == 401:
        from .notification_service import _refresh_salesforce_token
        new_token = _refresh_salesforce_token(organization_id, integration["refresh_token"])
        if not new_token:
            return {"error": "Token refresh failed", "synced": 0}
        try:
            query_resp = httpx.get(
                f"{instance_url}/services/data/{SF_API_VERSION}/query",
                params={"q": soql},
                headers={"Authorization": f"Bearer {new_token}", "Content-Type": "application/json"},
                timeout=30,
            )
        except Exception as e:
            return {"error": str(e), "synced": 0}

    if query_resp.status_code != 200:
        log.error("SF SOQL error %d: %s", query_resp.status_code, query_resp.text[:300])
        return {"error": f"SOQL query failed ({query_resp.status_code})", "synced": 0}

    records = query_resp.json().get("records", [])
    if not records:
        _touch_sync_timestamp(organization_id)
        return {"synced": 0, "created": 0, "updated": 0, "message": "No new/modified accounts"}

    results = {"synced": 0, "created": 0, "updated": 0, "errors": 0}

    for record in records:
        sf_id = record.get("Id")
        if not sf_id:
            continue

        dealer_data: Dict[str, Any] = {}
        for sf_field, di_field in INBOUND_FIELD_MAP.items():
            value = record.get(sf_field)
            if value is not None:
                dealer_data[di_field] = value

        if not dealer_data.get("name"):
            continue

        try:
            existing = supabase.table("distributors")\
                .select("id")\
                .eq("organization_id", str(organization_id))\
                .eq("salesforce_id", sf_id)\
                .maybe_single()\
                .execute()

            now = datetime.now(timezone.utc).isoformat()

            if existing and existing.data:
                dealer_data["salesforce_synced_at"] = now
                dealer_data["updated_at"] = now
                supabase.table("distributors")\
                    .update(dealer_data)\
                    .eq("id", existing.data["id"])\
                    .execute()
                results["updated"] += 1
            else:
                # Also check for name match without SF ID (link existing dealer)
                name_match = supabase.table("distributors")\
                    .select("id")\
                    .eq("organization_id", str(organization_id))\
                    .eq("name", dealer_data["name"])\
                    .is_("salesforce_id", "null")\
                    .maybe_single()\
                    .execute()

                if name_match and name_match.data:
                    dealer_data["salesforce_id"] = sf_id
                    dealer_data["salesforce_synced_at"] = now
                    dealer_data["updated_at"] = now
                    supabase.table("distributors")\
                        .update(dealer_data)\
                        .eq("id", name_match.data["id"])\
                        .execute()
                    results["updated"] += 1
                    log.info("Linked existing dealer '%s' to SF Account %s", dealer_data["name"], sf_id)
                else:
                    dealer_data["organization_id"] = str(organization_id)
                    dealer_data["salesforce_id"] = sf_id
                    dealer_data["salesforce_synced_at"] = now
                    dealer_data["status"] = "active"
                    supabase.table("distributors")\
                        .insert(dealer_data)\
                        .execute()
                    results["created"] += 1

            results["synced"] += 1

        except Exception as e:
            log.warning("Failed to sync SF Account %s: %s", sf_id, e)
            results["errors"] += 1

    _touch_sync_timestamp(organization_id)

    log.info(
        "SF inbound sync for org %s: %d synced (%d created, %d updated, %d errors)",
        organization_id, results["synced"], results["created"],
        results["updated"], results["errors"],
    )
    return results


def _touch_sync_timestamp(organization_id: UUID) -> None:
    """Update the last_synced_at on the Salesforce integration row."""
    try:
        supabase.table("integrations")\
            .update({"last_synced_at": datetime.now(timezone.utc).isoformat()})\
            .eq("organization_id", str(organization_id))\
            .eq("provider", "salesforce")\
            .execute()
    except Exception:
        pass


# ─── Outbound: compliance data → Salesforce Account fields ──────


def push_compliance_to_salesforce(
    *,
    organization_id: UUID,
    distributor_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Push compliance scores to Salesforce Account custom fields.

    If distributor_ids is None, pushes for all distributors with a salesforce_id.
    """
    integration = _get_salesforce_integration(organization_id)
    if not integration:
        return {"error": "Salesforce not connected", "pushed": 0}

    query = supabase.table("distributors")\
        .select("id, salesforce_id")\
        .eq("organization_id", str(organization_id))\
        .not_.is_("salesforce_id", "null")

    if distributor_ids:
        query = query.in_("id", distributor_ids)

    try:
        dist_rows = query.execute()
    except Exception as e:
        log.error("Failed to query distributors for SF push: %s", e)
        return {"error": str(e), "pushed": 0}

    dealers = dist_rows.data or []
    if not dealers:
        return {"pushed": 0, "message": "No SF-linked distributors"}

    dealer_ids = [d["id"] for d in dealers]

    # Batch-fetch compliance stats for all dealers
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
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    for dealer in dealers:
        sf_id = dealer["salesforce_id"]
        di_id = dealer["id"]
        stats = compliance_map.get(di_id, {"total": 0, "compliant": 0, "violations": 0})

        total = stats["total"]
        violations = stats["violations"]
        rate = round(stats["compliant"] / max(total, 1) * 100, 1) if total > 0 else 0.0

        payload = {
            "Compliance_Score__c": rate,
            "Open_Violations__c": violations,
            "Has_Compliance_Violation__c": violations > 0,
            "Last_Scan_Date__c": now_iso,
        }

        resp = _sf_api_request(
            organization_id=organization_id,
            integration=integration,
            method="PATCH",
            path=f"/services/data/{SF_API_VERSION}/sobjects/Account/Dealer_Intel_ID__c/{di_id}",
            json_body=payload,
        )

        if resp and resp.status_code in (200, 201, 204):
            results["pushed"] += 1
        elif resp and resp.status_code == 404:
            log.debug("SF Account with Dealer_Intel_ID__c=%s not found — skipping", di_id)
            results["skipped"] += 1
        else:
            status_code = resp.status_code if resp else "no response"
            log.warning("Failed to push compliance for %s to SF: %s", di_id, status_code)
            results["errors"] += 1

    log.info(
        "SF compliance push for org %s: %d pushed, %d skipped, %d errors",
        organization_id, results["pushed"], results["skipped"], results["errors"],
    )
    return results


# ─── Scheduled sync for all connected orgs ──────────────────────


async def run_salesforce_sync_all() -> None:
    """Run inbound dealer sync for every org with an active Salesforce integration.

    Called by APScheduler on a cron schedule.
    """
    try:
        rows = supabase.table("integrations")\
            .select("organization_id")\
            .eq("provider", "salesforce")\
            .execute()
    except Exception:
        log.warning("Could not query Salesforce integrations for scheduled sync")
        return

    orgs = rows.data or []
    if not orgs:
        return

    log.info("Running scheduled Salesforce sync for %d org(s)", len(orgs))

    for row in orgs:
        org_id = row.get("organization_id")
        if not org_id:
            continue
        try:
            result = sync_dealers_from_salesforce(UUID(org_id))
            log.info("SF sync org %s: %s", org_id, result)
        except Exception:
            log.exception("SF sync failed for org %s", org_id)
