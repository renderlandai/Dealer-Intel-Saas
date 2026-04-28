"""Scan runner coroutines — pure scan-pipeline logic, no FastAPI deps.

Extracted from `routers/scanning.py` (Phase 4.5) so any non-API caller —
a future worker process, a CLI, a test harness — can import the runners
without dragging in fastapi / auth / slowapi / plan_enforcement.

Every HTTP entry point in `routers/scanning.py` still creates the
`scan_jobs` row and calls `app.tasks.dispatch_task`; `dispatch_task`
imports the public coroutines below. The HTTP handlers themselves never
call these directly.

Public coroutines (called by `app.tasks`):
- `run_website_scan`
- `run_google_ads_scan`
- `run_facebook_scan`
- `run_instagram_scan`
- `auto_analyze_scan`        (campaign-linked auto-analyse after discovery)
- `run_image_analysis`       (Facebook / Google / manual analyse loop)

Internal helpers (used only by the runners):
- `_utc_now`, `_heartbeat`
- `_persist_cost`, `_send_scan_notifications`
- `_fetch_campaign_assets`
- `_prune_duplicate_matches`
- `_analyze_single_image`
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from ..database import supabase
from . import (
    extraction_service,
    ai_service,
    serpapi_service,
    apify_meta_service,
    apify_instagram_service,
)
from .bulk_writers import (
    _safe_insert_discovered_image,
    MatchBuffer,
    PendingMatch,
    bulk_insert_matches,
    ProcessedImageBuffer,
    bulk_mark_images_processed,
)
from .cost_tracker import scan_cost_context, ScanCostTracker
from .notification_service import (
    notify_scan_complete,
    notify_slack_scan_complete,
    notify_salesforce_scan_complete,
    notify_jira_scan_complete,
)
from .salesforce_sync_service import push_compliance_to_salesforce
from .hubspot_sync_service import push_compliance_to_hubspot

log = logging.getLogger("dealer_intel.scan_runners")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    """Return current UTC timestamp as ISO-8601 string for Supabase."""
    return datetime.now(timezone.utc).isoformat()


def _heartbeat(scan_job_id) -> None:
    """Stamp `scan_jobs.last_heartbeat_at` so the cleanup job knows we're alive.

    Writes ONLY `last_heartbeat_at` — never `started_at`. The 2026-04-01 bug
    that motivated turning the original heartbeat into a no-op was that it
    was clobbering `started_at`, which broke scan-duration metrics in the
    dashboard. The dedicated `last_heartbeat_at` column (migration 029)
    avoids that conflict entirely.

    Best-effort: failures are logged at debug level and swallowed so a
    transient Supabase hiccup never fails an otherwise-healthy scan.
    Called once per page from the website runner and at major phase
    boundaries; per-image calls would be too chatty for the value.
    """
    try:
        supabase.table("scan_jobs").update({
            "last_heartbeat_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()
    except Exception as e:
        log.debug("Heartbeat write failed for %s: %s", scan_job_id, e)


# Substrings used to detect Playwright "browser binary missing" failures.
# Matched case-insensitively against the raw exception text.  Kept narrow on
# purpose so unrelated Playwright errors (timeouts, navigation, etc.) still
# surface their original message.
_PLAYWRIGHT_MISSING_MARKERS = (
    "browsertype.launch: executable doesn't exist",
    "looks like playwright was just installed or updated",
    "playwright install",
    "chrome-headless-shell",
)


def _normalize_scan_error(exc: BaseException) -> str:
    """Return a stable, user-facing ``error_message`` for ``scan_jobs``.

    Most exceptions are stored verbatim, but a handful of infrastructure
    failures produce noisy multi-line tracebacks that mask what's actually
    wrong.  Normalising them here keeps the dashboard message actionable
    while still preserving the original cause for logs / Sentry.

    Currently handled:
      * Missing Playwright browser binaries (local dev sandbox or a worker
        image that skipped ``playwright install``).
    """
    raw = str(exc) or exc.__class__.__name__
    raw_one_line = " ".join(raw.split())
    haystack = raw_one_line.lower()

    if any(marker in haystack for marker in _PLAYWRIGHT_MISSING_MARKERS):
        snippet = raw_one_line[:240]
        return (
            "Browser runtime not installed: the scan worker cannot launch "
            "Chromium because Playwright browser binaries are missing. "
            "If running locally, execute backend/scripts/install_playwright.sh; "
            "in production, redeploy the worker so the Docker image runs "
            "`playwright install chromium --with-deps`. "
            f"Original: {snippet}"
        )

    return raw


def _persist_cost(scan_job_id: UUID, tracker: ScanCostTracker) -> Dict[str, Any]:
    """Write tracker totals onto the scan_jobs row.

    Best-effort: failures are logged and swallowed so a cost-write hiccup
    can never fail an otherwise-successful scan.  Returns the summary dict
    for callers that want to merge it into pipeline_stats.
    """
    summary = tracker.to_summary(include_line_items=True)
    try:
        supabase.table("scan_jobs").update({
            "cost_usd": tracker.total_usd,
            "cost_breakdown": summary,
        }).eq("id", str(scan_job_id)).execute()
        log.info(
            "Scan %s cost: $%.4f (%s)",
            scan_job_id, tracker.total_usd, tracker.by_vendor(),
        )
    except Exception as e:
        log.warning("Failed to persist scan cost for %s: %s", scan_job_id, e)
    return summary


def _send_scan_notifications(
    scan_job_id: UUID,
    scan_source: str = "",
    pipeline_stats: Optional[Dict[str, Any]] = None,
) -> None:
    """Query scan results and send a combined scan report + violations email."""
    try:
        job = supabase.table("scan_jobs")\
            .select("organization_id, total_items, processed_items, matches_count")\
            .eq("id", str(scan_job_id))\
            .single().execute()
        job_data = job.data or {}
        org_id = job_data.get("organization_id")
        if not org_id:
            return

        stats = pipeline_stats or {}
        total_matches = stats.get("matched_new", 0) + stats.get("matched_confirmed", 0)
        if not total_matches:
            total_matches = job_data.get("matches_count", 0)

        img_rows = supabase.table("discovered_images")\
            .select("id")\
            .eq("scan_job_id", str(scan_job_id))\
            .execute()
        img_ids = [r["id"] for r in (img_rows.data or [])]

        compliant = 0
        violation_count = 0
        if img_ids:
            all_matches = supabase.table("matches")\
                .select("compliance_status")\
                .in_("discovered_image_id", img_ids)\
                .execute()
            for m in (all_matches.data or []):
                if m.get("compliance_status") == "compliant":
                    compliant += 1
                elif m.get("compliance_status") == "violation":
                    violation_count += 1
        if compliant == 0 and violation_count == 0:
            compliant = total_matches

        total_images = stats.get("total_images", job_data.get("processed_items", 0))
        total_all = compliant + violation_count
        rate = round(compliant / max(total_all, 1) * 100, 1) if total_all > 0 else 100.0

        summary = {
            "total_images": total_images,
            "matches": total_matches,
            "compliant": compliant,
            "violations": violation_count,
            "compliance_rate": rate,
            "pages_scanned": stats.get("pages_scanned", 0),
            "pages_blocked": stats.get("pages_blocked", 0),
            "pages_failed": stats.get("pages_failed", 0),
            "pages_empty": stats.get("pages_empty", 0),
            "dealers_total": stats.get("dealers_total", 0),
            "dealers_ok": stats.get("dealers_ok", 0),
            "dealers_partial": stats.get("dealers_partial", 0),
            "dealers_blocked": stats.get("dealers_blocked", 0),
            "dealers_failed": stats.get("dealers_failed", 0),
        }

        violations_formatted: List[Dict[str, Any]] = []
        if violation_count > 0 and img_ids:
            try:
                v_matches = supabase.table("matches")\
                    .select("*, assets(name), distributors(name)")\
                    .eq("compliance_status", "violation")\
                    .in_("discovered_image_id", img_ids)\
                    .execute()
                for m in (v_matches.data or []):
                    analysis = m.get("ai_analysis", {}) or {}
                    comp_summary = ""
                    if isinstance(analysis, dict):
                        comp_summary = analysis.get("compliance", {}).get("summary", "")
                    violations_formatted.append({
                        "match_id": m.get("id"),
                        "asset_name": (m.get("assets") or {}).get("name", "Unknown"),
                        "distributor_name": (m.get("distributors") or {}).get("name", "Unknown"),
                        "channel": m.get("channel", scan_source),
                        "confidence_score": m.get("confidence_score", 0),
                        "compliance_summary": comp_summary,
                    })
            except Exception as ve:
                log.warning("Could not fetch violation details: %s", ve)

        notify_scan_complete(
            organization_id=UUID(org_id),
            scan_source=scan_source,
            summary=summary,
            violations=violations_formatted,
        )
        notify_slack_scan_complete(
            organization_id=UUID(org_id),
            scan_source=scan_source,
            summary=summary,
            violations=violations_formatted,
        )
        notify_salesforce_scan_complete(
            organization_id=UUID(org_id),
            scan_source=scan_source,
            summary=summary,
            violations=violations_formatted,
        )
        try:
            push_compliance_to_salesforce(organization_id=UUID(org_id))
        except Exception as sf_push_err:
            log.warning("SF compliance push failed for %s: %s", org_id, sf_push_err)
        notify_jira_scan_complete(
            organization_id=UUID(org_id),
            scan_source=scan_source,
            summary=summary,
            violations=violations_formatted,
        )
        try:
            push_compliance_to_hubspot(organization_id=UUID(org_id))
        except Exception as hs_push_err:
            log.warning("HubSpot compliance push failed for %s: %s", org_id, hs_push_err)
    except Exception as e:
        log.warning("Failed to send scan notifications for %s: %s", scan_job_id, e)


async def _fetch_campaign_assets(
    campaign_id: Optional[UUID],
    source: Optional[str] = None,
) -> List[Dict]:
    """Fetch campaign assets for a scan.

    When `source` is provided, only assets that are eligible for that channel
    are returned. An asset is eligible if its ``target_platforms`` array is
    empty (legacy / "all channels") or contains the requested source. This is
    the per-channel creative tagging introduced alongside migration 028.
    """
    if not campaign_id:
        return []
    try:
        result = supabase.table("assets")\
            .select("id, name, file_url, target_platforms")\
            .eq("campaign_id", str(campaign_id))\
            .execute()
        rows = result.data or []
        if source:
            filtered = [
                r for r in rows
                if not r.get("target_platforms") or source in (r.get("target_platforms") or [])
            ]
            skipped = len(rows) - len(filtered)
            if skipped:
                log.info(
                    "Channel filter for %s: using %d of %d asset(s) (%d skipped — tagged for other channels)",
                    source, len(filtered), len(rows), skipped,
                )
            return filtered
        return rows
    except Exception as e:
        log.error("Failed to fetch campaign assets: %s", e)
        return []


# ---------------------------------------------------------------------------
# Per-source runners (Google Ads, Facebook, Instagram)
#
# All three follow the same skeleton — only the discovery step differs. Phase
# 4.8 collapsed them onto `_run_source_scan(source, scan_job_id, campaign_id,
# discover)`; each public runner is now a thin wrapper that supplies the
# source label and the source-specific discovery callable. The wrappers keep
# their original public signatures because `app.tasks.dispatch_task` and the
# routers / scheduler import them by name.
#
# `run_website_scan` deliberately stays separate — its early-stop and page-
# cache logic does not fit the post-scan-analyse model the other three share.
# ---------------------------------------------------------------------------

# A discovery callable receives the loaded campaign_assets list and returns
# the count of `discovered_images` rows it created. The callable is async so
# wrappers can await source-specific clients (SerpApi, Apify, Playwright).
DiscoverFn = Callable[[List[Dict[str, Any]]], Awaitable[int]]


async def _run_source_scan(
    *,
    source: str,
    scan_job_id: UUID,
    campaign_id: Optional[UUID],
    discover: DiscoverFn,
) -> None:
    """Shared post-scan-analyse driver for non-website source runners.

    Sequencing (must match the per-source runners that existed pre-4.8 so
    nothing observable changes):

    1. Open `scan_cost_context`.
    2. Mark `scan_jobs.status = running` + `started_at`.
    3. Load campaign assets.
    4. Call `discover(campaign_assets)` → number of rows written to
       `discovered_images`.
    5. If a campaign is attached and discovery wrote anything, fire
       `auto_analyze_scan(scan_job_id, campaign_id)` (errors logged, scan
       still completes — analysis can be re-run later).
    6. Persist cost, mark `scan_jobs.status = completed`, send notifications.

    On exception: persist cost best-effort and write `status = failed` +
    `error_message`. Notifications are intentionally NOT sent on failure
    (matches the prior behaviour).
    """
    with scan_cost_context(str(scan_job_id)) as tracker:
        try:
            now = _utc_now()
            supabase.table("scan_jobs").update({
                "status": "running",
                "started_at": now,
                "last_heartbeat_at": now,
            }).eq("id", str(scan_job_id)).execute()

            campaign_assets = await _fetch_campaign_assets(campaign_id, source=source)
            _heartbeat(scan_job_id)
            discovered_count = await discover(campaign_assets)
            _heartbeat(scan_job_id)

            if campaign_id and discovered_count > 0:
                try:
                    await auto_analyze_scan(scan_job_id, campaign_id)
                except Exception as analyze_err:
                    log.error(
                        "%s auto-analysis failed (scan still completed): %s",
                        source, analyze_err, exc_info=True,
                    )

            _persist_cost(scan_job_id, tracker)
            supabase.table("scan_jobs").update({
                "status": "completed",
                "completed_at": _utc_now(),
            }).eq("id", str(scan_job_id)).execute()

            _send_scan_notifications(scan_job_id, scan_source=source)

        except Exception as e:
            log.error("%s scan failed: %s", source, e, exc_info=True)
            _persist_cost(scan_job_id, tracker)
            supabase.table("scan_jobs").update({
                "status": "failed",
                "error_message": _normalize_scan_error(e),
            }).eq("id", str(scan_job_id)).execute()


async def run_google_ads_scan(
    advertiser_ids: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None,
):
    """Background task — fetch ad creatives via SerpApi, then analyse."""
    async def discover(campaign_assets: List[Dict[str, Any]]) -> int:
        from ..config import get_settings
        _settings = get_settings()

        if _settings.serpapi_api_key:
            log.info("Using SerpApi for Google Ads scan")
            return await serpapi_service.scan_google_ads(
                advertiser_ids, scan_job_id, distributor_mapping,
                campaign_assets=campaign_assets,
            )
        log.info("SerpApi key not set — falling back to Playwright extraction")
        return await extraction_service.scan_google_ads(
            advertiser_ids, scan_job_id, distributor_mapping,
            campaign_assets=campaign_assets,
        )

    await _run_source_scan(
        source="google_ads",
        scan_job_id=scan_job_id,
        campaign_id=campaign_id,
        discover=discover,
    )


async def run_facebook_scan(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None,
    channel: str = "facebook",
):
    """Background task — extract ad images from Meta Ad Library pages."""
    async def discover(campaign_assets: List[Dict[str, Any]]) -> int:
        from ..config import get_settings
        _settings = get_settings()

        if _settings.apify_api_key:
            log.info("Using Apify Meta Ads Scraper Pro for %s scan", channel)
            return await apify_meta_service.scan_meta_ads(
                page_urls, scan_job_id, distributor_mapping,
                channel=channel,
                campaign_assets=campaign_assets,
            )
        log.info("Apify key not set — falling back to Playwright extraction")
        return await extraction_service.scan_facebook_ads(
            page_urls, scan_job_id, distributor_mapping,
            campaign_assets=campaign_assets,
        )

    # Note: `source` is intentionally "facebook" even when `channel` is
    # something else — `_send_scan_notifications` keys off `scan_source`
    # and historically that has always been "facebook" here.
    await _run_source_scan(
        source="facebook",
        scan_job_id=scan_job_id,
        campaign_id=campaign_id,
        discover=discover,
    )


async def run_instagram_scan(
    profile_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None,
):
    """Background task — extract organic post images from Instagram profiles."""
    async def discover(campaign_assets: List[Dict[str, Any]]) -> int:
        return await apify_instagram_service.scan_instagram_organic(
            profile_urls, scan_job_id, distributor_mapping,
            campaign_assets=campaign_assets,
        )

    await _run_source_scan(
        source="instagram",
        scan_job_id=scan_job_id,
        campaign_id=campaign_id,
        discover=discover,
    )


# ---------------------------------------------------------------------------
# Match dedupe + per-image analysis
# ---------------------------------------------------------------------------

async def _prune_duplicate_matches(scan_job_id: UUID) -> int:
    """Keep only the highest-confidence match per (asset_id, distributor_id).

    When scanning many pages, multiple images may match the same campaign
    asset for the same distributor at different confidence levels.  Only
    the best one should survive — the rest are noise.

    Returns the number of pruned (deleted) match rows.
    """
    try:
        img_rows = supabase.table("discovered_images")\
            .select("id")\
            .eq("scan_job_id", str(scan_job_id))\
            .execute()
        img_ids = [r["id"] for r in (img_rows.data or [])]
        if not img_ids:
            return 0

        all_matches = supabase.table("matches")\
            .select("id, asset_id, distributor_id, confidence_score")\
            .in_("discovered_image_id", img_ids)\
            .order("confidence_score", desc=True)\
            .execute()

        if not all_matches.data:
            return 0

        best: dict[tuple, str] = {}
        to_delete: list[str] = []

        for m in all_matches.data:
            key = (m.get("asset_id"), m.get("distributor_id"))
            if key not in best:
                best[key] = m["id"]
            else:
                to_delete.append(m["id"])

        if not to_delete:
            return 0

        # Batch delete in chunks of 100 (Supabase REST URL length is the limit
        # on .in_() list size — keep well under the practical 8KB cap).
        deleted = 0
        CHUNK = 100
        for i in range(0, len(to_delete), CHUNK):
            chunk = to_delete[i:i + CHUNK]
            supabase.table("matches").delete().in_("id", chunk).execute()
            deleted += len(chunk)

        log.info("Pruned %d duplicate matches for scan %s", deleted, scan_job_id)
        return deleted

    except Exception as e:
        log.warning("Match deduplication failed (non-fatal): %s", e)
        return 0


async def _analyze_single_image(
    image: Dict,
    campaign_assets: List[Dict],
    brand_rules: Dict[str, Any],
    organization_id: Optional[str],
    scan_job_id: str,
    asset_hashes: Dict,
    asset_embeddings: Dict,
    pipeline_stats: Dict[str, Any],
    match_buffer: Optional[MatchBuffer] = None,
    processed_buffer: Optional[ProcessedImageBuffer] = None,
) -> Optional[str]:
    """Process one image through the AI pipeline and create/update match records.

    Mutates *pipeline_stats* in place.
    Returns the matched asset_id (str) when a match is recorded, else None.
    """
    try:
        result, stage = await ai_service.process_discovered_image(
            image["id"],
            image["image_url"],
            campaign_assets,
            brand_rules,
            source_type=image.get("source_type"),
            channel=image.get("channel"),
            asset_hashes_cache=asset_hashes,
            asset_embeddings_cache=asset_embeddings,
        )

        if stage != "matched":
            pipeline_stats[stage] = pipeline_stats.get(stage, 0) + 1

        matched_asset_id: Optional[str] = None

        if result:
            log.info(
                "Match found for image %s — asset=%s confidence=%s%% type=%s compliance=%s",
                image["id"], result["asset_id"], result["confidence_score"],
                result["match_type"], result["compliance_status"],
            )
            try:
                existing = supabase.table("matches")\
                    .select("id, compliance_status, confidence_score, scan_count")\
                    .eq("asset_id", str(result["asset_id"]))\
                    .eq("source_url", image.get("source_url", ""))\
                    .execute()

                if existing.data:
                    old = existing.data[0]
                    old_status = old.get("compliance_status")
                    new_status = result["compliance_status"]
                    new_count = (old.get("scan_count") or 1) + 1

                    update_payload = {
                        "last_seen_at": _utc_now(),
                        "scan_count": new_count,
                        "confidence_score": result["confidence_score"],
                        "match_type": result["match_type"],
                        "is_modified": result["is_modified"],
                        "modifications": result["modifications"],
                        "compliance_status": new_status,
                        "compliance_issues": result["compliance_issues"],
                        "ai_analysis": result["ai_analysis"],
                    }

                    has_drift = old_status and old_status != new_status
                    if has_drift:
                        update_payload["previous_compliance_status"] = old_status
                        pipeline_stats["drift_detected"] = pipeline_stats.get("drift_detected", 0) + 1
                        log.warning(
                            "Compliance DRIFT on match %s: %s → %s",
                            old["id"], old_status, new_status,
                        )

                    supabase.table("matches").update(update_payload)\
                        .eq("id", old["id"]).execute()

                    pipeline_stats["matched_confirmed"] = pipeline_stats.get("matched_confirmed", 0) + 1
                    matched_asset_id = str(result["asset_id"])
                    log.info(
                        "Existing match %s confirmed (seen %dx)%s",
                        old["id"], new_count,
                        f" — DRIFT: {old_status}→{new_status}" if has_drift else "",
                    )

                    if has_drift and new_status == "violation":
                        org_id = organization_id or image.get("organization_id")
                        if org_id:
                            supabase.table("alerts").insert({
                                "organization_id": org_id,
                                "match_id": old["id"],
                                "distributor_id": image.get("distributor_id"),
                                "alert_type": "compliance_drift",
                                "severity": "critical",
                                "title": "Compliance drift detected — was compliant, now violation",
                                "description": result["ai_analysis"].get("compliance", {}).get("summary", ""),
                            }).execute()
                else:
                    match_payload = {
                        "asset_id": str(result["asset_id"]),
                        "discovered_image_id": image["id"],
                        "distributor_id": image.get("distributor_id"),
                        "confidence_score": result["confidence_score"],
                        "match_type": result["match_type"],
                        "is_modified": result["is_modified"],
                        "modifications": result["modifications"],
                        "channel": image.get("channel"),
                        "source_url": image.get("source_url"),
                        "screenshot_url": image.get("image_url"),
                        "compliance_status": result["compliance_status"],
                        "compliance_issues": result["compliance_issues"],
                        "ai_analysis": result["ai_analysis"],
                        "discovered_at": image.get("discovered_at"),
                        "last_seen_at": _utc_now(),
                        "scan_count": 1,
                    }

                    alert_template: Optional[Dict[str, Any]] = None
                    if result["compliance_status"] == "violation":
                        org_id = organization_id or image.get("organization_id")
                        if org_id:
                            alert_template = {
                                "organization_id": org_id,
                                "distributor_id": image.get("distributor_id"),
                                "alert_type": "compliance_violation",
                                "severity": "warning",
                                "title": "Compliance violation detected",
                                "description": result["ai_analysis"].get("compliance", {}).get("summary", ""),
                            }

                    if match_buffer is not None:
                        match_buffer.add(match_payload, alert_template=alert_template)
                        log.info("Match queued (buffered) for asset %s", result["asset_id"])
                    else:
                        # Fallback path: immediate single-row insert (used when no
                        # buffer is supplied — keeps legacy callers working).
                        results = bulk_insert_matches([
                            PendingMatch(payload=match_payload, alert_template=alert_template),
                        ])
                        inserted = results[0] if results else None
                        log.info(
                            "Match record created: %s",
                            inserted.get("id") if inserted else "unknown",
                        )

                    pipeline_stats["matched_new"] = pipeline_stats.get("matched_new", 0) + 1
                    matched_asset_id = str(result["asset_id"])
            except Exception as db_error:
                log.error("Failed to create/update match record: %s", db_error)
                pipeline_stats["errors"] = pipeline_stats.get("errors", 0) + 1

        if processed_buffer is not None:
            processed_buffer.add(image["id"])
        else:
            supabase.table("discovered_images").update({
                "is_processed": True
            }).eq("id", image["id"]).execute()

        return matched_asset_id

    except Exception as e:
        log.error("Error analyzing image %s: %s", image["id"], e, exc_info=True)
        pipeline_stats["errors"] = pipeline_stats.get("errors", 0) + 1
        if processed_buffer is not None:
            processed_buffer.add(image["id"])
        else:
            supabase.table("discovered_images").update({
                "is_processed": True
            }).eq("id", image["id"]).execute()
        return None


# ---------------------------------------------------------------------------
# Per-dealer concurrency helpers (Phase 5-minimal)
# ---------------------------------------------------------------------------

async def page_discovery_discover(base_url: str) -> List[str]:
    """Local wrapper around ``page_discovery.discover_pages`` that respects
    the per-site cap and isolates the import. Pulled out so the website
    runner does not have to import `page_discovery` at top level (it would
    cycle with `page_cache_service` otherwise)."""
    from . import page_discovery
    from ..config import get_settings as _gs
    s = _gs()
    if not s.enable_page_discovery:
        return [base_url]
    return await page_discovery.discover_pages(base_url, max_pages=s.max_pages_per_site)


async def _process_one_dealer(
    *,
    base_url: str,
    page_urls: List[str],
    distributor_id: Optional[Any],
    scan_job_id: UUID,
    campaign_assets: List[Dict[str, Any]],
    brand_rules: Dict[str, Any],
    org_id: Optional[str],
    asset_hashes: Dict,
    asset_embeddings: Dict,
    can_early_stop: bool,
    all_asset_ids: set,
    matched_asset_ids: set,
    matched_lock: asyncio.Lock,
    early_stop_event: asyncio.Event,
    sem: asyncio.Semaphore,
    settings,
) -> Dict[str, Any]:
    """Process one dealer's pages sequentially, with its own buffers.

    Designed to be invoked from `run_website_scan`'s `asyncio.gather` over
    every dealer in the scan. Each dealer instance:

    * Holds the shared semaphore for the duration of its work — so the
      number of concurrent Playwright contexts AND concurrent in-flight
      AI batches is bounded by `settings.max_concurrent_dealers`.
    * Owns its own `MatchBuffer` and `ProcessedImageBuffer` (the bulk
      writers are explicitly NOT coroutine-safe; sharing across dealers
      would race on `_pending`).
    * Owns its own `pipeline_increments` dict and returns it for the
      caller to fold into the run-wide stats — avoids a contended Lock
      around ints that fire dozens of times per page.
    * Honours the global early-stop set via `matched_lock` + the shared
      `early_stop_event`. The Event is the cheap notify channel; the
      Lock+set is the source of truth for "do we have everything yet."

    Returns an aggregation payload the caller folds back in. Any raised
    exception bubbles out; the gather caller logs it and marks the
    pipeline_stats `errors` counter.
    """
    async with sem:
        local_buffer = MatchBuffer()
        local_processed = ProcessedImageBuffer()
        local_total_discovered = 0
        local_pages_scanned = 0       # pages that returned >=1 real image
        local_pages_empty = 0         # pages that loaded but had no images
        local_pages_blocked = 0       # WAF / 4xx / ERR_ABORTED
        local_pages_failed = 0        # timeouts / playwright crashes
        local_total_images = 0
        local_pages_skipped = 0
        local_page_match_tracker: Dict[str, set] = {}
        local_block_details: List[Dict[str, Any]] = []
        local_pipeline: Dict[str, Any] = {
            "download_failed": 0,
            "hash_rejected": 0,
            "clip_rejected": 0,
            "filter_rejected": 0,
            "below_threshold": 0,
            "verification_rejected": 0,
            "matched_new": 0,
            "matched_confirmed": 0,
            "drift_detected": 0,
            "errors": 0,
        }

        try:
            for page_idx, page_url in enumerate(page_urls):
                if early_stop_event.is_set():
                    local_pages_skipped = len(page_urls) - page_idx
                    log.info(
                        "[%s] early-stop signalled — skipping %d remaining page(s)",
                        base_url, local_pages_skipped,
                    )
                    break

                log.info("[%s] [page %d/%d] Extracting: %s",
                         base_url, page_idx + 1, len(page_urls), page_url)
                _heartbeat(scan_job_id)

                try:
                    res = await extraction_service.extract_dealer_website(
                        page_url, scan_job_id, distributor_id,
                        campaign_assets=campaign_assets,
                    )
                except Exception as page_err:
                    log.error(
                        "[%s] page extraction crashed for %s: %s",
                        base_url, page_url, page_err, exc_info=True,
                    )
                    local_pipeline["errors"] += 1
                    local_pages_failed += 1
                    local_block_details.append({
                        "page_url": page_url,
                        "outcome": extraction_service.OUTCOME_CRASHED,
                        "reason": str(page_err)[:200],
                    })
                    continue

                count = res.count
                evidence_url = res.evidence_url
                outcome = res.outcome

                # Bin the page outcome. The inserted screenshot row is now
                # optional and never bumps `pages_scanned` — it exists only
                # so the user can see *what* was on the page (a WAF
                # challenge, a 404, an empty SPA shell, etc.).
                if outcome == extraction_service.OUTCOME_IMAGES:
                    local_total_discovered += count
                    local_pages_scanned += 1
                elif outcome == extraction_service.OUTCOME_EMPTY:
                    local_pages_empty += 1
                    if (
                        settings.enable_tiling_fallback
                        and evidence_url
                    ):
                        log.info(
                            "[%s] zero images from %s — inserting screenshot for tiling fallback",
                            base_url, page_url,
                        )
                        _safe_insert_discovered_image({
                            "scan_job_id": str(scan_job_id),
                            "distributor_id": str(distributor_id) if distributor_id else None,
                            "source_url": page_url,
                            "image_url": evidence_url,
                            "source_type": "page_screenshot",
                            "channel": "website",
                            "metadata": {
                                "capture_method": "playwright_fallback",
                                "full_page": True,
                                "reason": "no_images_extracted",
                            },
                        })
                        # Tiling fallback can produce a usable creative, so
                        # treat as a real (low-confidence) scanned page.
                        count = 1
                        local_total_discovered += 1
                        local_pages_scanned += 1
                elif outcome == extraction_service.OUTCOME_BLOCKED:
                    local_pages_blocked += 1
                    local_block_details.append({
                        "page_url": page_url,
                        "outcome": outcome,
                        "reason": res.block_reason,
                        "http_status": res.http_status,
                    })
                    if evidence_url:
                        # Surface the WAF/error page itself so the user can
                        # see *why* we couldn't scan, but mark it clearly
                        # as evidence of a block — not as a scanned page.
                        _safe_insert_discovered_image({
                            "scan_job_id": str(scan_job_id),
                            "distributor_id": str(distributor_id) if distributor_id else None,
                            "source_url": page_url,
                            "image_url": evidence_url,
                            "source_type": "page_screenshot",
                            "channel": "website",
                            "metadata": {
                                "capture_method": "blocked_evidence",
                                "full_page": True,
                                "reason": res.block_reason or "blocked",
                                "http_status": res.http_status,
                            },
                        })
                    log.warning(
                        "[%s] page %s blocked (%s, http=%s)",
                        base_url, page_url, res.block_reason, res.http_status,
                    )
                else:
                    local_pages_failed += 1
                    local_block_details.append({
                        "page_url": page_url,
                        "outcome": outcome,
                        "reason": res.block_reason,
                    })
                    log.warning(
                        "[%s] page %s failed (%s, %s)",
                        base_url, page_url, outcome, res.block_reason,
                    )

                if can_early_stop and count > 0:
                    page_images = supabase.table("discovered_images")\
                        .select("*")\
                        .eq("scan_job_id", str(scan_job_id))\
                        .eq("source_url", page_url)\
                        .eq("is_processed", False)\
                        .execute()

                    for image in (page_images.data or []):
                        local_total_images += 1
                        asset_id = await _analyze_single_image(
                            image, campaign_assets, brand_rules,
                            org_id, str(scan_job_id),
                            asset_hashes, asset_embeddings, local_pipeline,
                            match_buffer=local_buffer,
                            processed_buffer=local_processed,
                        )
                        if asset_id:
                            local_page_match_tracker.setdefault(page_url, set()).add(asset_id)
                            async with matched_lock:
                                matched_asset_ids.add(asset_id)
                                if all_asset_ids and matched_asset_ids >= all_asset_ids:
                                    early_stop_event.set()

                # End-of-page check for early-stop so we leave the loop
                # before paying for the next page's Playwright load.
                if all_asset_ids:
                    async with matched_lock:
                        if matched_asset_ids >= all_asset_ids:
                            early_stop_event.set()
                if early_stop_event.is_set():
                    local_pages_skipped = len(page_urls) - (page_idx + 1)
                    if local_pages_skipped > 0:
                        log.info(
                            "[%s] early-stop after page %d/%d (%d skipped)",
                            base_url, page_idx + 1, len(page_urls), local_pages_skipped,
                        )
                    break

        finally:
            inserted = local_buffer.flush_all()
            if inserted or local_buffer.total_failed:
                log.info(
                    "[%s] match buffer flushed: %d inserted, %d failed",
                    base_url, inserted, local_buffer.total_failed,
                )
            marked = local_processed.flush_all()
            if marked:
                log.debug("[%s] processed buffer flushed: %d marked", base_url, marked)

        # Per-dealer status used by the aggregator and email summary.
        if local_pages_scanned == 0 and local_pages_blocked > 0:
            dealer_status = "blocked"
        elif local_pages_scanned == 0 and local_pages_failed > 0:
            dealer_status = "failed"
        elif local_pages_scanned == 0:
            dealer_status = "empty"
        elif local_pages_blocked > 0 or local_pages_failed > 0:
            dealer_status = "partial"
        else:
            dealer_status = "ok"

        return {
            "total_discovered": local_total_discovered,
            "pages_scanned": local_pages_scanned,
            "pages_empty": local_pages_empty,
            "pages_blocked": local_pages_blocked,
            "pages_failed": local_pages_failed,
            "total_images": local_total_images,
            "pages_skipped": local_pages_skipped,
            "pipeline_increments": local_pipeline,
            "page_match_tracker": local_page_match_tracker,
            "block_details": local_block_details,
            "dealer_status": dealer_status,
            "base_url": base_url,
            "distributor_id": str(distributor_id) if distributor_id else None,
        }


# ---------------------------------------------------------------------------
# Website runner — the only "online" runner (analyses page-by-page so it
# can early-stop once every campaign asset has been matched).
# ---------------------------------------------------------------------------

async def run_website_scan(
    website_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None,
):
    """Background task — extract images from dealer websites via Playwright.

    Supports **early stopping**: when all campaign assets have been matched,
    remaining pages are skipped to save time and API costs.

    Supports **page hit caching**: on repeat scans, pages that previously
    produced matches are scanned first. If all assets are matched from
    cached pages alone, full page discovery is skipped entirely.
    """
    from . import page_cache_service

    log.info("Website scan started for job %s — URLs: %s, campaign: %s",
             scan_job_id, website_urls, campaign_id)

    cost_ctx = scan_cost_context(str(scan_job_id))
    tracker = cost_ctx.__enter__()
    try:
        # Mark running IMMEDIATELY so the cleanup job doesn't kill us
        # during the (potentially slow) prep phase. Stamp `last_heartbeat_at`
        # at the same time so a scan that gets stuck in prep is still
        # protected by the heartbeat-aware cleanup.
        now = _utc_now()
        supabase.table("scan_jobs").update({
            "status": "running",
            "started_at": now,
            "last_heartbeat_at": now,
        }).eq("id", str(scan_job_id)).execute()

        from ..config import get_settings
        _settings = get_settings()

        campaign_assets = await _fetch_campaign_assets(campaign_id, source="website")
        if campaign_assets:
            log.info("Loaded %d campaign asset(s)", len(campaign_assets))

        can_early_stop = bool(campaign_id and campaign_assets)
        all_asset_ids = {str(a["id"]) for a in campaign_assets} if can_early_stop else set()
        matched_asset_ids: set = set()

        page_match_tracker: Dict[str, set] = {}

        # Buffer match inserts (and their alert payloads) so each page's batch
        # of detections becomes one HTTP call instead of one per match.
        match_buffer = MatchBuffer()

        # Buffer the trailing `is_processed=True` flips so a long scan does
        # not fire one HTTP UPDATE per analysed image (Phase 4.7).
        processed_buffer = ProcessedImageBuffer()

        asset_hashes: Dict = {}
        asset_embeddings: Dict = {}
        brand_rules: Dict[str, Any] = {}
        org_id: Optional[str] = None

        job_data = supabase.table("scan_jobs")\
            .select("organization_id").eq("id", str(scan_job_id)).single().execute()
        org_id = job_data.data.get("organization_id") if job_data.data else None

        if can_early_stop:
            log.info("Early stopping enabled — will stop after all %d assets are matched", len(all_asset_ids))
            asset_hashes = await ai_service._precompute_asset_hashes(campaign_assets)
            asset_embeddings = await ai_service._precompute_asset_embeddings(campaign_assets)
            log.info("Cached %d hash sets, %d CLIP embeddings", len(asset_hashes), len(asset_embeddings))
            _heartbeat(scan_job_id)

            if org_id:
                rules = supabase.table("compliance_rules")\
                    .select("*").eq("organization_id", org_id)\
                    .eq("is_active", True).execute()
                for rule in (rules.data or []):
                    if rule["rule_type"] == "required_element":
                        brand_rules.setdefault("required_elements", []).append(
                            rule["rule_config"].get("element"))
                    elif rule["rule_type"] == "forbidden_element":
                        brand_rules.setdefault("forbidden_elements", []).append(
                            rule["rule_config"].get("element"))

        # ---- Phase 1: Try cached hot pages first ----
        cached_pages: List[str] = []
        cache_early_stopped = False
        if can_early_stop and org_id:
            for base_url in website_urls:
                dist_id = extraction_service._match_distributor_by_domain(
                    base_url, distributor_mapping)
                if dist_id:
                    cached = page_cache_service.get_cached_pages(
                        org_id, str(dist_id),
                        str(campaign_id) if campaign_id else None,
                    )
                    cached_pages.extend(cached)

        total_discovered = 0

        if cached_pages:
            log.info("Phase 1: Scanning %d cached hot page(s) first", len(cached_pages))

            for cidx, page_url in enumerate(cached_pages):
                log.info("[Cache %d/%d] Extracting: %s", cidx + 1, len(cached_pages), page_url)

                distributor_id = extraction_service._match_distributor_by_domain(
                    page_url, distributor_mapping)
                res = await extraction_service.extract_dealer_website(
                    page_url, scan_job_id, distributor_id,
                    campaign_assets=campaign_assets,
                )
                count = res.count
                evidence_url = res.evidence_url
                if (
                    count == 0
                    and _settings.enable_tiling_fallback
                    and evidence_url
                    and res.outcome == extraction_service.OUTCOME_EMPTY
                ):
                    _safe_insert_discovered_image({
                        "scan_job_id": str(scan_job_id),
                        "distributor_id": str(distributor_id) if distributor_id else None,
                        "source_url": page_url,
                        "image_url": evidence_url,
                        "source_type": "page_screenshot",
                        "channel": "website",
                        "metadata": {"capture_method": "playwright_fallback", "full_page": True},
                    })
                    count = 1
                elif res.outcome == extraction_service.OUTCOME_BLOCKED and evidence_url:
                    _safe_insert_discovered_image({
                        "scan_job_id": str(scan_job_id),
                        "distributor_id": str(distributor_id) if distributor_id else None,
                        "source_url": page_url,
                        "image_url": evidence_url,
                        "source_type": "page_screenshot",
                        "channel": "website",
                        "metadata": {
                            "capture_method": "blocked_evidence",
                            "full_page": True,
                            "reason": res.block_reason or "blocked",
                            "http_status": res.http_status,
                        },
                    })

                total_discovered += count

                if can_early_stop and count > 0:
                    page_images = supabase.table("discovered_images")\
                        .select("*")\
                        .eq("scan_job_id", str(scan_job_id))\
                        .eq("source_url", page_url)\
                        .eq("is_processed", False)\
                        .execute()

                    for image in (page_images.data or []):
                        asset_id = await _analyze_single_image(
                            image, campaign_assets, brand_rules,
                            org_id, str(scan_job_id),
                            asset_hashes, asset_embeddings, {},
                            match_buffer=match_buffer,
                            processed_buffer=processed_buffer,
                        )
                        if asset_id:
                            matched_asset_ids.add(asset_id)
                            page_match_tracker.setdefault(page_url, set()).add(asset_id)

                    if all_asset_ids and matched_asset_ids >= all_asset_ids:
                        log.info(
                            "CACHE HIT: All %d assets matched from %d cached page(s) — skipping discovery",
                            len(all_asset_ids), cidx + 1,
                        )
                        cache_early_stopped = True
                        break

        # ---- Phase 2: Per-dealer concurrent discovery + analysis ----
        #
        # Phase 5-minimal change: instead of a single sequential `for page in
        # discovered_pages` loop across every dealer, we expand pages per
        # dealer, then process up to `settings.max_concurrent_dealers`
        # dealers in parallel via asyncio.gather. Each dealer task owns its
        # own MatchBuffer / ProcessedImageBuffer (they are NOT coroutine-
        # safe — see bulk_writers.py docstrings) and accumulates its own
        # pipeline stats. Shared state is restricted to (1) the early-stop
        # set guarded by a Lock and (2) an Event that lets dealer tasks
        # notice the global early-stop without polling the set.
        #
        # The cache-phase MatchBuffer / ProcessedImageBuffer above stay
        # shared because Phase 1 is still sequential (cached pages are
        # short, and serialising them keeps cache-hit accounting simple).
        # They get drained at the end of the function alongside the
        # per-dealer flushes that already happen inside each task.
        cached_set = set(cached_pages)

        per_dealer_pages: Dict[str, List[str]] = {}
        per_dealer_dist_id: Dict[str, Optional[str]] = {}
        if cache_early_stopped:
            total_pages = len(cached_pages)
            pages_from_discovery = 0
        else:
            for base_url in website_urls:
                try:
                    discovered = await page_discovery_discover(base_url)
                except Exception as e:
                    log.error("Page discovery failed for %s: %s", base_url, e)
                    discovered = [base_url]
                pages_for_dealer = [u for u in discovered if u not in cached_set]
                per_dealer_pages[base_url] = pages_for_dealer
                per_dealer_dist_id[base_url] = extraction_service._match_distributor_by_domain(
                    base_url, distributor_mapping
                )
            pages_from_discovery = sum(len(p) for p in per_dealer_pages.values())
            total_pages = len(cached_pages) + pages_from_discovery
            log.info(
                "Phase 2: %d additional page(s) across %d dealer(s) (after %d cached)",
                pages_from_discovery, len(per_dealer_pages), len(cached_pages),
            )
            _heartbeat(scan_job_id)

        pipeline_stats: Dict[str, Any] = {
            "total_images": 0,
            "download_failed": 0,
            "hash_rejected": 0,
            "clip_rejected": 0,
            "filter_rejected": 0,
            "below_threshold": 0,
            "verification_rejected": 0,
            "matched_new": 0,
            "matched_confirmed": 0,
            "drift_detected": 0,
            "errors": 0,
            "pages_discovered": total_pages,
            "pages_scanned": len(cached_pages) if cache_early_stopped else 0,
            "pages_empty": 0,
            "pages_blocked": 0,
            "pages_failed": 0,
            "pages_skipped": 0,
            "dealers_total": 0,
            "dealers_ok": 0,
            "dealers_partial": 0,
            "dealers_blocked": 0,
            "dealers_failed": 0,
            "dealers_empty": 0,
            "blocked_details": [],   # [{base_url, distributor_id, pages: [{page_url, reason, http_status}]}]
            "early_stopped": cache_early_stopped,
            "cache_hit": cache_early_stopped,
            "cached_pages_used": len(cached_pages),
            "concurrent_dealers": _settings.max_concurrent_dealers,
        }

        early_stopped = cache_early_stopped

        if not cache_early_stopped and per_dealer_pages:
            early_stop_event = asyncio.Event()
            matched_lock = asyncio.Lock()
            sem = asyncio.Semaphore(max(1, _settings.max_concurrent_dealers))

            dealer_tasks = [
                asyncio.create_task(
                    _process_one_dealer(
                        base_url=base_url,
                        page_urls=pages,
                        distributor_id=per_dealer_dist_id.get(base_url),
                        scan_job_id=scan_job_id,
                        campaign_assets=campaign_assets,
                        brand_rules=brand_rules,
                        org_id=org_id,
                        asset_hashes=asset_hashes,
                        asset_embeddings=asset_embeddings,
                        can_early_stop=can_early_stop,
                        all_asset_ids=all_asset_ids,
                        matched_asset_ids=matched_asset_ids,
                        matched_lock=matched_lock,
                        early_stop_event=early_stop_event,
                        sem=sem,
                        settings=_settings,
                    ),
                    name=f"dealer:{base_url}",
                )
                for base_url, pages in per_dealer_pages.items()
                if pages
            ]

            dealer_results = await asyncio.gather(*dealer_tasks, return_exceptions=True)

            for result in dealer_results:
                if isinstance(result, BaseException):
                    log.error("Per-dealer task crashed: %s", result, exc_info=result)
                    pipeline_stats["errors"] += 1
                    pipeline_stats["dealers_failed"] += 1
                    pipeline_stats["dealers_total"] += 1
                    continue
                total_discovered += result["total_discovered"]
                pipeline_stats["pages_scanned"] += result["pages_scanned"]
                pipeline_stats["pages_empty"] += result.get("pages_empty", 0)
                pipeline_stats["pages_blocked"] += result.get("pages_blocked", 0)
                pipeline_stats["pages_failed"] += result.get("pages_failed", 0)
                pipeline_stats["total_images"] += result["total_images"]
                pipeline_stats["pages_skipped"] += result["pages_skipped"]
                for k, v in result["pipeline_increments"].items():
                    pipeline_stats[k] = pipeline_stats.get(k, 0) + v
                for page_url, asset_ids in result["page_match_tracker"].items():
                    page_match_tracker.setdefault(page_url, set()).update(asset_ids)

                pipeline_stats["dealers_total"] += 1
                status = result.get("dealer_status", "ok")
                key = f"dealers_{status}"
                pipeline_stats[key] = pipeline_stats.get(key, 0) + 1
                block_pages = result.get("block_details") or []
                if block_pages:
                    pipeline_stats["blocked_details"].append({
                        "base_url": result.get("base_url"),
                        "distributor_id": result.get("distributor_id"),
                        "dealer_status": status,
                        "pages": block_pages,
                    })

            if early_stop_event.is_set():
                early_stopped = True
                pipeline_stats["early_stopped"] = True
                log.info(
                    "EARLY STOP: All %d assets matched across %d dealer(s)",
                    len(all_asset_ids), len(per_dealer_pages),
                )

        if not can_early_stop and campaign_id and total_discovered > 0:
            log.info("Starting batch analysis for campaign %s", campaign_id)
            try:
                await auto_analyze_scan(scan_job_id, campaign_id)
            except Exception as analyze_err:
                log.error("Website auto-analysis failed (scan still completed): %s", analyze_err, exc_info=True)

        # Persist any matches still queued in the buffer BEFORE the dedupe step
        # below (which queries the matches table) and BEFORE we report counts.
        flushed_matches = match_buffer.flush_all()
        if flushed_matches or match_buffer.total_failed:
            log.info(
                "Match buffer flushed: %d inserted, %d failed",
                flushed_matches, match_buffer.total_failed,
            )

        # Drain the trailing is_processed flips before the scan reports
        # `processed_items` so the count and the row state agree.
        flushed_processed = processed_buffer.flush_all()
        if flushed_processed:
            log.info(
                "Processed-image buffer flushed: %d rows marked",
                flushed_processed,
            )

        # ---- Deduplicate: keep only the best match per asset per distributor ----
        pruned = await _prune_duplicate_matches(scan_job_id)
        pipeline_stats["matches_pruned"] = pruned

        total_matches = (
            pipeline_stats["matched_new"]
            + pipeline_stats["matched_confirmed"]
            - pruned
        )

        cache_stats = ai_service.get_image_cache_stats()
        pipeline_stats["image_cache"] = cache_stats

        # ---- Update page hit cache ----
        if org_id and page_match_tracker:
            for page_url, asset_ids in page_match_tracker.items():
                dist_id = extraction_service._match_distributor_by_domain(
                    page_url, distributor_mapping)
                if dist_id:
                    page_cache_service.record_page_hits(
                        org_id, str(dist_id),
                        str(campaign_id) if campaign_id else None,
                        {page_url: asset_ids},
                    )

        log.info(
            "Website scan complete — pages=%d/%d images=%d matches=%d "
            "(new=%d confirmed=%d) early_stop=%s cache_hit=%s",
            pipeline_stats["pages_scanned"], total_pages,
            pipeline_stats["total_images"], total_matches,
            pipeline_stats["matched_new"], pipeline_stats["matched_confirmed"],
            early_stopped, cache_early_stopped,
        )
        log.info("Pipeline funnel: %s", pipeline_stats)

        cost_summary = _persist_cost(scan_job_id, tracker)
        pipeline_stats["cost"] = cost_summary

        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": _utc_now(),
            "total_items": total_discovered,
            "processed_items": pipeline_stats["total_images"],
            "matches_count": total_matches,
            "pipeline_stats": pipeline_stats,
        }).eq("id", str(scan_job_id)).execute()

        _send_scan_notifications(scan_job_id, scan_source="website", pipeline_stats=pipeline_stats)

    except Exception as e:
        log.error("Website scan failed: %s", e, exc_info=True)
        try:
            # Persist any matches queued before the failure so partial work
            # is not lost.
            match_buffer.flush_all()
        except Exception as flush_err:
            log.warning("Match buffer flush during failure path errored: %s", flush_err)
        try:
            # Mirror the success path so partially-analysed images aren't
            # re-processed forever on the next scan.
            processed_buffer.flush_all()
        except Exception as flush_err:
            log.warning("Processed-image buffer flush during failure path errored: %s", flush_err)
        try:
            _persist_cost(scan_job_id, tracker)
        except Exception:
            pass
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": _normalize_scan_error(e),
        }).eq("id", str(scan_job_id)).execute()
    finally:
        cost_ctx.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Post-scan analyse paths (used by Facebook / Google / manual / reprocess)
# ---------------------------------------------------------------------------

async def auto_analyze_scan(scan_job_id: UUID, campaign_id: UUID):
    """
    Automatically analyze discovered images after scan completion.

    This function is called automatically when a campaign-linked scan completes.
    It matches discovered images against campaign assets and performs compliance checks.
    """
    log.info("Starting auto-analysis for scan %s, campaign %s", scan_job_id, campaign_id)

    try:
        # Get scan job details
        job = supabase.table("scan_jobs")\
            .select("*")\
            .eq("id", str(scan_job_id))\
            .single()\
            .execute()

        if not job.data:
            log.error("Scan job %s not found", scan_job_id)
            return

        log.info("Scan job found: %s", job.data.get('status'))
        log.info("Organization ID: %s", job.data.get('organization_id'))

        # Get unprocessed discovered images
        images = supabase.table("discovered_images")\
            .select("*")\
            .eq("scan_job_id", str(scan_job_id))\
            .eq("is_processed", False)\
            .execute()

        log.info("Found %d unprocessed images", len(images.data) if images.data else 0)

        if not images.data:
            log.info("No unprocessed images found for scan %s", scan_job_id)
            # Update scan job to show 0 processed
            supabase.table("scan_jobs").update({
                "processed_items": 0
            }).eq("id", str(scan_job_id)).execute()
            return

        # Log discovered images
        log.debug("Discovered images to analyze:")
        for idx, img in enumerate(images.data):
            log.debug("  [%d] ID: %s", idx + 1, img.get('id'))
            log.debug("      URL: %s", img.get('image_url', 'N/A')[:100])
            log.debug("      Source: %s", img.get('source_url', 'N/A')[:80])
            log.debug("      Type: %s", img.get('source_type', 'N/A'))
            log.debug("      Channel: %s", img.get('channel', 'N/A'))

        # Get campaign assets, restricted to assets eligible for this scan's source.
        scan_source = job.data.get("source") if job.data else None
        assets = supabase.table("assets")\
            .select("*")\
            .eq("campaign_id", str(campaign_id))\
            .execute()
        all_asset_rows = assets.data or []
        if scan_source:
            eligible_rows = [
                r for r in all_asset_rows
                if not r.get("target_platforms") or scan_source in (r.get("target_platforms") or [])
            ]
            skipped = len(all_asset_rows) - len(eligible_rows)
            if skipped:
                log.info(
                    "Auto-analyse: filtered to %d of %d asset(s) eligible for source=%s (%d skipped)",
                    len(eligible_rows), len(all_asset_rows), scan_source, skipped,
                )
            assets.data = eligible_rows

        log.info("Found %d campaign assets", len(assets.data) if assets.data else 0)

        if not assets.data:
            log.warning("No assets found for campaign %s — cannot audit without campaign assets", campaign_id)
            # Mark images as processed anyway to avoid re-processing.
            # One bulk UPDATE replaces N round-trips here (Phase 4.7).
            bulk_mark_images_processed([img["id"] for img in images.data])
            supabase.table("scan_jobs").update({
                "processed_items": len(images.data),
                "error_message": "No campaign assets to match against"
            }).eq("id", str(scan_job_id)).execute()
            return

        # Log campaign assets with accessibility check
        log.debug("Campaign assets to match against:")
        for idx, asset in enumerate(assets.data):
            asset_url = asset.get('file_url', 'N/A')
            log.debug("  [%d] ID: %s", idx + 1, asset.get('id'))
            log.debug("      Name: %s", asset.get('name', 'N/A'))
            log.debug("      URL: %s", asset_url[:100])
            # Check if URL looks like a Supabase storage URL
            if 'supabase' in asset_url.lower() and '/storage/v1/' in asset_url:
                log.warning("Supabase storage URL for asset %s — ensure bucket is public", asset.get('id'))

        # Get brand rules
        rules = supabase.table("compliance_rules")\
            .select("*")\
            .eq("organization_id", job.data["organization_id"])\
            .eq("is_active", True)\
            .execute()

        log.info("Found %d compliance rules", len(rules.data) if rules.data else 0)

        brand_rules = {}
        for rule in rules.data:
            if rule["rule_type"] == "required_element":
                brand_rules.setdefault("required_elements", []).append(
                    rule["rule_config"].get("element")
                )
            elif rule["rule_type"] == "forbidden_element":
                brand_rules.setdefault("forbidden_elements", []).append(
                    rule["rule_config"].get("element")
                )

        log.debug("Brand rules: %s", brand_rules)
        log.info("Starting Claude image analysis")

        # Run analysis
        await run_image_analysis(
            images.data,
            assets.data,
            brand_rules,
            job.data["organization_id"],
            str(scan_job_id)  # Pass scan_job_id for matches_count update
        )

        # Update scan job with processed count
        supabase.table("scan_jobs").update({
            "processed_items": len(images.data)
        }).eq("id", str(scan_job_id)).execute()

        log.info("Auto-analysis completed for scan %s — processed %d images", scan_job_id, len(images.data))

    except Exception as e:
        log.error("Critical error in auto-analysis for scan %s: %s", scan_job_id, e, exc_info=True)
        try:
            supabase.table("scan_jobs").update({
                "status": "failed",
                "error_message": f"Analysis failed: {_normalize_scan_error(e)}"
            }).eq("id", str(scan_job_id)).execute()
        except Exception as db_err:
            log.error("Failed to update scan job status after analysis error: %s", db_err)


async def run_image_analysis(
    discovered_images: List[Dict],
    campaign_assets: List[Dict],
    brand_rules: Dict[str, Any],
    organization_id: Optional[str] = None,
    scan_job_id: Optional[str] = None
):
    """Background task to analyze images and create matches.

    Used by Facebook / Google / manual analysis paths.
    Website scans use inline page-by-page analysis with early stopping instead.
    """
    log.info("Starting image analysis — %d images, %d assets, org=%s, job=%s",
             len(discovered_images), len(campaign_assets), organization_id, scan_job_id)

    log.info("Pre-computing asset hashes and CLIP embeddings...")
    asset_hashes = await ai_service._precompute_asset_hashes(campaign_assets)
    asset_embeddings = await ai_service._precompute_asset_embeddings(campaign_assets)
    log.info("Cached %d hash sets, %d CLIP embeddings", len(asset_hashes), len(asset_embeddings))

    pipeline_stats: Dict[str, Any] = {
        "total_images": len(discovered_images),
        "download_failed": 0,
        "hash_rejected": 0,
        "clip_rejected": 0,
        "filter_rejected": 0,
        "below_threshold": 0,
        "verification_rejected": 0,
        "matched_new": 0,
        "matched_confirmed": 0,
        "drift_detected": 0,
        "errors": 0,
    }

    match_buffer = MatchBuffer()
    processed_buffer = ProcessedImageBuffer()

    for idx, image in enumerate(discovered_images):
        log.info("[%d/%d] Processing image %s — URL: %s, source: %s, channel: %s",
                 idx + 1, len(discovered_images), image["id"],
                 image["image_url"][:100], image.get("source_type", "unknown"),
                 image.get("channel", "unknown"))

        await _analyze_single_image(
            image, campaign_assets, brand_rules,
            organization_id, scan_job_id,
            asset_hashes, asset_embeddings, pipeline_stats,
            match_buffer=match_buffer,
            processed_buffer=processed_buffer,
        )

    flushed = match_buffer.flush_all()
    if flushed or match_buffer.total_failed:
        log.info(
            "Match buffer flushed: %d inserted, %d failed",
            flushed, match_buffer.total_failed,
        )

    flushed_processed = processed_buffer.flush_all()
    if flushed_processed:
        log.info(
            "Processed-image buffer flushed: %d rows marked",
            flushed_processed,
        )

    total_matches = pipeline_stats["matched_new"] + pipeline_stats["matched_confirmed"]

    cache_stats = ai_service.get_image_cache_stats()
    pipeline_stats["image_cache"] = cache_stats

    log.info(
        "Image analysis complete — processed=%d new=%d confirmed=%d drift=%d errors=%d",
        len(discovered_images), pipeline_stats["matched_new"],
        pipeline_stats["matched_confirmed"], pipeline_stats["drift_detected"],
        pipeline_stats["errors"],
    )
    log.info("Pipeline funnel: %s", pipeline_stats)
    log.info("Image cache: %d hits, %d misses (%.1f%% hit rate, %.2f MB cached)",
             cache_stats["hits"], cache_stats["misses"],
             cache_stats["hit_rate"], cache_stats["cached_mb"])

    job_id = scan_job_id
    if not job_id and discovered_images:
        job_id = discovered_images[0].get("scan_job_id")

    if job_id:
        from . import cost_tracker as _ct
        active_tracker = _ct.get_tracker()
        if active_tracker is not None:
            try:
                pipeline_stats["cost"] = active_tracker.to_summary(include_line_items=False)
            except Exception:
                pass

        log.info("Updating scan job %s with matches_count=%d (new=%d, confirmed=%d)",
                 job_id, total_matches,
                 pipeline_stats["matched_new"], pipeline_stats["matched_confirmed"])
        supabase.table("scan_jobs").update({
            "matches_count": total_matches,
            "pipeline_stats": pipeline_stats,
        }).eq("id", str(job_id)).execute()
