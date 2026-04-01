"""Scanning and analysis routes."""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Optional, Dict, Any
from uuid import UUID

from ..auth import AuthUser, get_current_user
from ..database import supabase
from ..models import ScanJobCreate, ScanJob, ScanSource
from ..services import screenshot_service, extraction_service, ai_service, serpapi_service, apify_meta_service, apify_instagram_service
from ..services.notification_service import notify_scan_complete
from ..plan_enforcement import (
    OrgPlan, get_org_plan,
    check_scan_quota, check_concurrent_scans, check_channel_allowed,
)
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

log = logging.getLogger("dealer_intel.scanning")


def _utc_now() -> str:
    """Return current UTC timestamp as ISO-8601 string for Supabase."""
    return datetime.now(timezone.utc).isoformat()


def _heartbeat(scan_job_id) -> None:
    """Touch the scan job's updated_at so the cleanup job knows we're alive."""
    try:
        supabase.table("scan_jobs").update({
            "updated_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()
    except Exception:
        pass


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
        }

        violations_formatted: List[Dict[str, Any]] = []
        if violation_count > 0:
            try:
                v_matches = supabase.table("matches")\
                    .select("*")\
                    .eq("compliance_status", "violation")\
                    .execute()
                for m in (v_matches.data or []):
                    img = supabase.table("discovered_images")\
                        .select("scan_job_id")\
                        .eq("id", m.get("discovered_image_id", ""))\
                        .single().execute()
                    if img.data and img.data.get("scan_job_id") == str(scan_job_id):
                        analysis = m.get("ai_analysis", {}) or {}
                        comp_summary = ""
                        if isinstance(analysis, dict):
                            comp_summary = analysis.get("compliance", {}).get("summary", "")
                        violations_formatted.append({
                            "asset_name": m.get("asset_name", "Unknown"),
                            "distributor_name": m.get("distributor_name", "Unknown"),
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
    except Exception as e:
        log.warning("Failed to send scan notifications for %s: %s", scan_job_id, e)


router = APIRouter(prefix="/scans", tags=["scanning"])


@router.post("/start", response_model=ScanJob, summary="Start scan job")
@limiter.limit("10/minute")
async def start_scan(
    request: Request,
    scan_request: ScanJobCreate,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """
    Start a new scan job.
    
    Dispatches the scan as a background task.
    """
    check_channel_allowed(op, scan_request.source.value)
    check_scan_quota(op)
    check_concurrent_scans(op)
    from ..tasks import dispatch_task

    job_data = {
        "organization_id": str(user.org_id),
        "campaign_id": str(scan_request.campaign_id) if scan_request.campaign_id else None,
        "source": scan_request.source.value,
        "status": "pending"
    }
    
    result = supabase.table("scan_jobs").insert(job_data).execute()
    scan_job = result.data[0]
    scan_job_id = scan_job["id"]
    
    if scan_request.campaign_id:
        campaign_check = supabase.table("campaigns")\
            .select("id")\
            .eq("id", str(scan_request.campaign_id))\
            .eq("organization_id", str(user.org_id))\
            .maybe_single()\
            .execute()
        if not campaign_check.data:
            raise HTTPException(status_code=404, detail="Campaign not found")

    if scan_request.distributor_ids:
        distributors = supabase.table("distributors")\
            .select("*")\
            .in_("id", [str(d) for d in scan_request.distributor_ids])\
            .eq("organization_id", str(user.org_id))\
            .execute()
    else:
        distributors = supabase.table("distributors")\
            .select("*")\
            .eq("organization_id", str(user.org_id))\
            .eq("status", "active")\
            .execute()
    
    distributor_list = distributors.data
    campaign_id_str = str(scan_request.campaign_id) if scan_request.campaign_id else None
    dispatched = False
    
    if scan_request.source == ScanSource.GOOGLE_ADS:
        names = [d.get("google_ads_advertiser_id") or d["name"] for d in distributor_list]
        mapping = {
            (d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"]
            for d in distributor_list
        }
        log.info("Starting Google Ads scan for %d advertisers, job=%s", len(names), scan_job_id)
        dispatched = await dispatch_task("run_google_ads_scan_task", [names, scan_job_id, mapping, campaign_id_str], scan_job_id, "google_ads")
        
    elif scan_request.source == ScanSource.INSTAGRAM:
        urls = [d["instagram_url"] for d in distributor_list if d.get("instagram_url")]
        mapping = {}
        for d in distributor_list:
            ig_url = d.get("instagram_url")
            if ig_url:
                username = apify_instagram_service._extract_username(ig_url)
                if username:
                    mapping[username.lower()] = d["id"]
                mapping[d["name"].lower()] = d["id"]
        log.info("Starting Instagram organic scan for %d profiles, job=%s", len(urls), scan_job_id)
        dispatched = await dispatch_task("run_instagram_scan_task", [urls, scan_job_id, mapping, campaign_id_str], scan_job_id, "instagram")

    elif scan_request.source == ScanSource.FACEBOOK:
        urls = [d["facebook_url"] for d in distributor_list if d.get("facebook_url")]
        mapping = {d["name"].lower(): d["id"] for d in distributor_list}
        log.info("Starting Facebook scan for %d pages, job=%s", len(urls), scan_job_id)
        dispatched = await dispatch_task("run_facebook_scan_task", [urls, scan_job_id, mapping, campaign_id_str, "facebook"], scan_job_id, "facebook")
        
    elif scan_request.source == ScanSource.WEBSITE:
        urls = [d["website_url"] for d in distributor_list if d.get("website_url")]
        mapping = {
            d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
            for d in distributor_list if d.get("website_url")
        }
        log.info("Starting website scan for %d URLs, job=%s: %s", len(urls), scan_job_id, urls)
        dispatched = await dispatch_task("run_website_scan_task", [urls, scan_job_id, mapping, campaign_id_str], scan_job_id, "website")

    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to start scan task. Please try again.")
    
    return scan_job


async def _fetch_campaign_assets(campaign_id: Optional[UUID]) -> List[Dict]:
    """Fetch campaign assets from the database for AI localization."""
    if not campaign_id:
        return []
    try:
        result = supabase.table("assets")\
            .select("id, name, file_url")\
            .eq("campaign_id", str(campaign_id))\
            .execute()
        return result.data or []
    except Exception as e:
        log.error("Failed to fetch campaign assets: %s", e)
        return []


async def run_google_ads_scan(
    advertiser_ids: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None,
):
    """Background task — fetch ad creatives via SerpApi, then analyse."""
    try:
        supabase.table("scan_jobs").update({
            "status": "running",
            "started_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()

        campaign_assets = await _fetch_campaign_assets(campaign_id)

        from ..config import get_settings
        _settings = get_settings()

        if _settings.serpapi_api_key:
            log.info("Using SerpApi for Google Ads scan")
            discovered_count = await serpapi_service.scan_google_ads(
                advertiser_ids, scan_job_id, distributor_mapping,
                campaign_assets=campaign_assets,
            )
        else:
            log.info("SerpApi key not set — falling back to Playwright extraction")
            discovered_count = await extraction_service.scan_google_ads(
                advertiser_ids, scan_job_id, distributor_mapping,
                campaign_assets=campaign_assets,
            )

        if campaign_id and discovered_count > 0:
            await auto_analyze_scan(scan_job_id, campaign_id)

        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()

        _send_scan_notifications(scan_job_id, scan_source="google_ads")

    except Exception as e:
        log.error("Google Ads scan failed: %s", e, exc_info=True)
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", str(scan_job_id)).execute()


async def run_facebook_scan(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None,
    channel: str = "facebook",
):
    """Background task — extract ad images from Meta Ad Library pages."""
    try:
        supabase.table("scan_jobs").update({
            "status": "running",
            "started_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()

        campaign_assets = await _fetch_campaign_assets(campaign_id)

        from ..config import get_settings
        _settings = get_settings()

        if _settings.apify_api_key:
            log.info("Using Apify Meta Ads Scraper Pro for %s scan", channel)
            discovered_count = await apify_meta_service.scan_meta_ads(
                page_urls, scan_job_id, distributor_mapping,
                channel=channel,
                campaign_assets=campaign_assets,
            )
        else:
            log.info("Apify key not set — falling back to Playwright extraction")
            discovered_count = await extraction_service.scan_facebook_ads(
                page_urls, scan_job_id, distributor_mapping,
                campaign_assets=campaign_assets,
            )

        if campaign_id and discovered_count > 0:
            await auto_analyze_scan(scan_job_id, campaign_id)

        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()

        _send_scan_notifications(scan_job_id, scan_source="facebook")

    except Exception as e:
        log.error("Facebook scan failed: %s", e, exc_info=True)
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", str(scan_job_id)).execute()


async def run_instagram_scan(
    profile_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    campaign_id: Optional[UUID] = None,
):
    """Background task — extract organic post images from Instagram profiles."""
    try:
        supabase.table("scan_jobs").update({
            "status": "running",
            "started_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()

        campaign_assets = await _fetch_campaign_assets(campaign_id)

        discovered_count = await apify_instagram_service.scan_instagram_organic(
            profile_urls, scan_job_id, distributor_mapping,
            campaign_assets=campaign_assets,
        )

        if campaign_id and discovered_count > 0:
            await auto_analyze_scan(scan_job_id, campaign_id)

        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()

        _send_scan_notifications(scan_job_id, scan_source="instagram")

    except Exception as e:
        log.error("Instagram scan failed: %s", e, exc_info=True)
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", str(scan_job_id)).execute()


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

        for match_id in to_delete:
            supabase.table("matches").delete().eq("id", match_id).execute()

        log.info("Pruned %d duplicate matches for scan %s", len(to_delete), scan_job_id)
        return len(to_delete)

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
                                "severity": "high",
                                "title": "Compliance drift detected — was compliant, now violation",
                                "description": result["ai_analysis"].get("compliance", {}).get("summary", ""),
                            }).execute()
                else:
                    match_record = supabase.table("matches").insert({
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
                    }).execute()

                    pipeline_stats["matched_new"] = pipeline_stats.get("matched_new", 0) + 1
                    matched_asset_id = str(result["asset_id"])
                    log.info("Match record created: %s",
                             match_record.data[0]["id"] if match_record.data else "unknown")

                    if result["compliance_status"] == "violation":
                        org_id = organization_id or image.get("organization_id")
                        if org_id:
                            supabase.table("alerts").insert({
                                "organization_id": org_id,
                                "match_id": match_record.data[0]["id"] if match_record.data else None,
                                "distributor_id": image.get("distributor_id"),
                                "alert_type": "compliance_violation",
                                "severity": "warning",
                                "title": "Compliance violation detected",
                                "description": result["ai_analysis"].get("compliance", {}).get("summary", ""),
                            }).execute()
            except Exception as db_error:
                log.error("Failed to create/update match record: %s", db_error)
                pipeline_stats["errors"] = pipeline_stats.get("errors", 0) + 1

        supabase.table("discovered_images").update({
            "is_processed": True
        }).eq("id", image["id"]).execute()

        return matched_asset_id

    except Exception as e:
        log.error("Error analyzing image %s: %s", image["id"], e, exc_info=True)
        pipeline_stats["errors"] = pipeline_stats.get("errors", 0) + 1
        supabase.table("discovered_images").update({
            "is_processed": True
        }).eq("id", image["id"]).execute()
        return None


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
    from ..services import page_cache_service

    log.info("Website scan started for job %s — URLs: %s, campaign: %s",
             scan_job_id, website_urls, campaign_id)

    try:
        # Mark running IMMEDIATELY so the cleanup job doesn't kill us
        # during the (potentially slow) prep phase.
        supabase.table("scan_jobs").update({
            "status": "running",
            "started_at": _utc_now(),
        }).eq("id", str(scan_job_id)).execute()

        from ..config import get_settings
        _settings = get_settings()

        campaign_assets = await _fetch_campaign_assets(campaign_id)
        if campaign_assets:
            log.info("Loaded %d campaign asset(s)", len(campaign_assets))

        can_early_stop = bool(campaign_id and campaign_assets)
        all_asset_ids = {str(a["id"]) for a in campaign_assets} if can_early_stop else set()
        matched_asset_ids: set = set()

        page_match_tracker: Dict[str, set] = {}

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
                count, evidence_url = await extraction_service.extract_dealer_website(
                    page_url, scan_job_id, distributor_id,
                    campaign_assets=campaign_assets,
                )
                if count == 0 and _settings.enable_tiling_fallback and evidence_url:
                    supabase.table("discovered_images").insert({
                        "scan_job_id": str(scan_job_id),
                        "distributor_id": str(distributor_id) if distributor_id else None,
                        "source_url": page_url,
                        "image_url": evidence_url,
                        "source_type": "page_screenshot",
                        "channel": "website",
                        "metadata": {"capture_method": "playwright_fallback", "full_page": True},
                    }).execute()
                    count = 1

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

        # ---- Phase 2: Full page discovery (skipped if cache covered everything) ----
        if cache_early_stopped:
            expanded_urls = cached_pages
            total_pages = len(cached_pages)
            pages_from_discovery = 0
        else:
            expanded_urls = await extraction_service.discover_website_urls(website_urls)

            # Exclude pages already scanned from cache phase
            cached_set = set(cached_pages)
            remaining_urls = [u for u in expanded_urls if u not in cached_set]
            total_pages = len(cached_pages) + len(remaining_urls)
            pages_from_discovery = len(remaining_urls)

            log.info("Phase 2: %d additional page(s) from discovery (after %d cached)",
                     pages_from_discovery, len(cached_pages))
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
            "pages_scanned": len(cached_pages) if cache_early_stopped else len(cached_pages),
            "pages_skipped": 0,
            "early_stopped": cache_early_stopped,
            "cache_hit": cache_early_stopped,
            "cached_pages_used": len(cached_pages),
        }

        early_stopped = cache_early_stopped

        if not cache_early_stopped:
            remaining_to_scan = [u for u in expanded_urls if u not in set(cached_pages)] if cached_pages else expanded_urls

            for page_idx, page_url in enumerate(remaining_to_scan):
                overall_idx = len(cached_pages) + page_idx
                log.info("[Page %d/%d] Extracting: %s", overall_idx + 1, total_pages, page_url)
                _heartbeat(scan_job_id)

                distributor_id = extraction_service._match_distributor_by_domain(
                    page_url, distributor_mapping)

                count, evidence_url = await extraction_service.extract_dealer_website(
                    page_url, scan_job_id, distributor_id,
                    campaign_assets=campaign_assets,
                )

                if count == 0 and _settings.enable_tiling_fallback and evidence_url:
                    log.info("Zero images from %s — inserting screenshot for tiling", page_url)
                    supabase.table("discovered_images").insert({
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
                    }).execute()
                    count = 1

                total_discovered += count
                pipeline_stats["pages_scanned"] += 1

                if can_early_stop and count > 0:
                    page_images = supabase.table("discovered_images")\
                        .select("*")\
                        .eq("scan_job_id", str(scan_job_id))\
                        .eq("source_url", page_url)\
                        .eq("is_processed", False)\
                        .execute()

                    for image in (page_images.data or []):
                        pipeline_stats["total_images"] += 1
                        log.info("[Page %d/%d] Analyzing image %s",
                                 overall_idx + 1, total_pages, image["id"])
                        asset_id = await _analyze_single_image(
                            image, campaign_assets, brand_rules,
                            org_id, str(scan_job_id),
                            asset_hashes, asset_embeddings, pipeline_stats,
                        )
                        if asset_id:
                            matched_asset_ids.add(asset_id)
                            page_match_tracker.setdefault(page_url, set()).add(asset_id)

                    if all_asset_ids and matched_asset_ids >= all_asset_ids:
                        remaining = len(remaining_to_scan) - (page_idx + 1)
                        pipeline_stats["early_stopped"] = True
                        pipeline_stats["pages_skipped"] = remaining
                        log.info(
                            "EARLY STOP: All %d assets matched after %d/%d pages (%d skipped)",
                            len(all_asset_ids), overall_idx + 1, total_pages, remaining,
                        )
                        early_stopped = True
                        break

        if not can_early_stop and campaign_id and total_discovered > 0:
            log.info("Starting batch analysis for campaign %s", campaign_id)
            await auto_analyze_scan(scan_job_id, campaign_id)

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
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", str(scan_job_id)).execute()


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
        
        # Get campaign assets
        assets = supabase.table("assets")\
            .select("*")\
            .eq("campaign_id", str(campaign_id))\
            .execute()
        
        log.info("Found %d campaign assets", len(assets.data) if assets.data else 0)
        
        if not assets.data:
            log.warning("No assets found for campaign %s — cannot audit without campaign assets", campaign_id)
            # Mark images as processed anyway to avoid re-processing
            for img in images.data:
                supabase.table("discovered_images").update({
                    "is_processed": True
                }).eq("id", img["id"]).execute()
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
                "error_message": f"Analysis failed: {str(e)}"
            }).eq("id", str(scan_job_id)).execute()
        except Exception as db_err:
            log.error("Failed to update scan job status after analysis error: %s", db_err)


@router.get("", response_model=List[ScanJob], summary="List scan jobs")
async def list_scan_jobs(
    status: Optional[str] = None,
    limit: int = 20,
    user: AuthUser = Depends(get_current_user),
):
    """List scan jobs."""
    query = supabase.table("scan_jobs").select("*")
    query = query.eq("organization_id", str(user.org_id))
    if status:
        query = query.eq("status", status)
    
    result = query.order("created_at", desc=True).limit(limit).execute()
    return result.data


@router.get("/{job_id}", response_model=ScanJob, summary="Get scan job")
async def get_scan_job(job_id: UUID, user: AuthUser = Depends(get_current_user)):
    """Get scan job details."""
    result = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(job_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    return result.data


@router.post("/{job_id}/retry", response_model=ScanJob, summary="Retry failed scan")
async def retry_scan_job(
    job_id: UUID,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Retry a failed scan by creating a new scan job with the same parameters."""
    old_job = supabase.table("scan_jobs") \
        .select("*") \
        .eq("id", str(job_id)) \
        .single().execute()
    if not old_job.data:
        raise HTTPException(404, "Scan job not found")
    if old_job.data.get("organization_id") != str(user.org_id):
        raise HTTPException(403, "Not your scan")
    if old_job.data["status"] != "failed":
        raise HTTPException(400, "Only failed scans can be retried")

    source = old_job.data["source"]
    campaign_id = old_job.data.get("campaign_id")

    check_channel_allowed(op, source)
    check_scan_quota(op)
    check_concurrent_scans(op)

    from ..tasks import dispatch_task

    new_job = supabase.table("scan_jobs").insert({
        "organization_id": str(user.org_id),
        "campaign_id": campaign_id,
        "source": source,
        "status": "pending",
    }).execute()
    new_id = new_job.data[0]["id"]

    distributors = supabase.table("distributors") \
        .select("*") \
        .eq("organization_id", str(user.org_id)) \
        .eq("status", "active").execute()
    dist_list = distributors.data

    campaign_id_str = campaign_id if campaign_id else None
    dispatched = False

    if source == "google_ads":
        names = [d.get("google_ads_advertiser_id") or d["name"] for d in dist_list]
        mapping = {(d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"] for d in dist_list}
        dispatched = await dispatch_task("run_google_ads_scan_task", [names, new_id, mapping, campaign_id_str], new_id, "google_ads")
    elif source == "instagram":
        urls = [d["instagram_url"] for d in dist_list if d.get("instagram_url")]
        mapping = {}
        for d in dist_list:
            ig_url = d.get("instagram_url")
            if ig_url:
                username = apify_instagram_service._extract_username(ig_url)
                if username:
                    mapping[username.lower()] = d["id"]
                mapping[d["name"].lower()] = d["id"]
        dispatched = await dispatch_task("run_instagram_scan_task", [urls, new_id, mapping, campaign_id_str], new_id, "instagram")
    elif source == "facebook":
        urls = [d["facebook_url"] for d in dist_list if d.get("facebook_url")]
        mapping = {d["name"].lower(): d["id"] for d in dist_list}
        dispatched = await dispatch_task("run_facebook_scan_task", [urls, new_id, mapping, campaign_id_str, "facebook"], new_id, "facebook")
    elif source == "website":
        urls = [d["website_url"] for d in dist_list if d.get("website_url")]
        mapping = {
            d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
            for d in dist_list if d.get("website_url")
        }
        dispatched = await dispatch_task("run_website_scan_task", [urls, new_id, mapping, campaign_id_str], new_id, "website")

    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to start scan task. Please try again.")

    log.info("Retried scan %s → new scan %s (source=%s)", job_id, new_id, source)
    return new_job.data[0]


@router.delete("/{job_id}", summary="Delete scan job")
async def delete_scan_job(job_id: UUID, user: AuthUser = Depends(get_current_user)):
    """
    Delete a scan job and all its associated data.
    
    This will cascade delete:
    - discovered_images (via ON DELETE CASCADE)
    - matches linked to those discovered images (via ON DELETE CASCADE)
    """
    job = supabase.table("scan_jobs")\
        .select("id")\
        .eq("id", str(job_id))\
        .eq("organization_id", str(user.org_id))\
        .maybe_single()\
        .execute()
    if not job.data:
        raise HTTPException(status_code=404, detail="Scan job not found")

    discovered = supabase.table("discovered_images")\
        .select("id")\
        .eq("scan_job_id", str(job_id))\
        .execute()
    
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        supabase.table("matches")\
            .delete()\
            .in_("discovered_image_id", discovered_ids)\
            .execute()
    
    supabase.table("scan_jobs")\
        .delete()\
        .eq("id", str(job_id))\
        .execute()
    
    return {"status": "deleted", "job_id": str(job_id)}


@router.delete("", summary="Delete all scans")
async def delete_all_scans(user: AuthUser = Depends(get_current_user)):
    """
    Delete all scan jobs and associated data for the current org.
    Only available when ENABLE_DANGEROUS_ENDPOINTS=true.
    """
    from ..config import get_settings
    if not get_settings().enable_dangerous_endpoints:
        raise HTTPException(status_code=403, detail="Bulk delete is disabled in this environment")

    org_jobs = supabase.table("scan_jobs")\
        .select("id")\
        .eq("organization_id", str(user.org_id))\
        .execute()
    job_ids = [j["id"] for j in (org_jobs.data or [])]
    if not job_ids:
        return {"status": "deleted", "count": 0}

    discovered = supabase.table("discovered_images")\
        .select("id")\
        .in_("scan_job_id", job_ids)\
        .execute()
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        supabase.table("matches")\
            .delete()\
            .in_("discovered_image_id", discovered_ids)\
            .execute()

    supabase.table("scan_jobs")\
        .delete()\
        .eq("organization_id", str(user.org_id))\
        .execute()

    return {"status": "deleted", "count": len(job_ids)}


@router.post("/{job_id}/analyze", summary="Analyze discovered images")
async def analyze_discovered_images(
    job_id: UUID,
    campaign_id: Optional[UUID] = None,
    user: AuthUser = Depends(get_current_user),
):
    """
    Analyze discovered images from a completed scan.
    Runs as a background task.
    """
    from ..tasks import dispatch_task

    job = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(job_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not job.data:
        raise HTTPException(status_code=404, detail="Scan job not found")
    
    if job.data["status"] != "completed":
        raise HTTPException(status_code=400, detail="Scan job not completed yet")
    
    images = supabase.table("discovered_images")\
        .select("id", count="exact")\
        .eq("scan_job_id", str(job_id))\
        .eq("is_processed", False)\
        .execute()
    
    image_count = images.count or 0
    if image_count == 0:
        return {"message": "No unprocessed images found", "count": 0}
    
    dispatched = await dispatch_task(
        "run_analyze_scan_task",
        [str(job_id), str(campaign_id) if campaign_id else None],
        str(job_id),
        "analyze_scan",
    )
    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to queue analysis task")

    return {
        "message": "Analysis queued",
        "image_count": image_count,
    }


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

    for idx, image in enumerate(discovered_images):
        log.info("[%d/%d] Processing image %s — URL: %s, source: %s, channel: %s",
                 idx + 1, len(discovered_images), image["id"],
                 image["image_url"][:100], image.get("source_type", "unknown"),
                 image.get("channel", "unknown"))

        await _analyze_single_image(
            image, campaign_assets, brand_rules,
            organization_id, scan_job_id,
            asset_hashes, asset_embeddings, pipeline_stats,
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
        log.info("Updating scan job %s with matches_count=%d (new=%d, confirmed=%d)",
                 job_id, total_matches,
                 pipeline_stats["matched_new"], pipeline_stats["matched_confirmed"])
        supabase.table("scan_jobs").update({
            "matches_count": total_matches,
            "pipeline_stats": pipeline_stats,
        }).eq("id", str(job_id)).execute()


@router.post("/batch", summary="Batch scan all channels")
@limiter.limit("2/minute")
async def batch_scan(
    request: Request,
    user: AuthUser = Depends(get_current_user),
    op: OrgPlan = Depends(get_org_plan),
):
    """Scan all dealers across all allowed channels. Pro and Business plans only."""
    if op.plan not in ("professional", "business", "enterprise"):
        raise HTTPException(
            403,
            "Batch scanning is available on Pro and Business plans. "
            "Upgrade to unlock this feature.",
        )

    check_scan_quota(op)

    from ..tasks import dispatch_task

    distributors = supabase.table("distributors") \
        .select("*") \
        .eq("organization_id", str(user.org_id)) \
        .eq("status", "active").execute()
    dist_list = distributors.data or []
    if not dist_list:
        raise HTTPException(400, "No active dealers found. Add dealers first.")

    campaigns_resp = supabase.table("campaigns") \
        .select("id") \
        .eq("organization_id", str(user.org_id)) \
        .eq("status", "active") \
        .limit(1).execute()
    campaign_id_str = campaigns_resp.data[0]["id"] if campaigns_resp.data else None

    allowed_channels = op.limits.get("allowed_channels", [])
    created_jobs = []

    for channel in allowed_channels:
        active = supabase.table("scan_jobs") \
            .select("id", count="exact") \
            .eq("organization_id", str(user.org_id)) \
            .in_("status", ["pending", "running", "analyzing"]).execute()
        max_concurrent = op.limits.get("max_concurrent_scans", 1)
        if (active.count or 0) >= max_concurrent:
            break

        job = supabase.table("scan_jobs").insert({
            "organization_id": str(user.org_id),
            "campaign_id": campaign_id_str,
            "source": channel,
            "status": "pending",
        }).execute()
        job_id = job.data[0]["id"]

        if channel == "google_ads":
            names = [d.get("google_ads_advertiser_id") or d["name"] for d in dist_list]
            mapping = {(d.get("google_ads_advertiser_id") or d["name"]).lower(): d["id"] for d in dist_list}
            await dispatch_task("run_google_ads_scan_task", [names, job_id, mapping, campaign_id_str], job_id, "google_ads")
        elif channel == "instagram":
            urls = [d["instagram_url"] for d in dist_list if d.get("instagram_url")]
            mapping = {}
            for d in dist_list:
                ig_url = d.get("instagram_url")
                if ig_url:
                    username = apify_instagram_service._extract_username(ig_url)
                    if username:
                        mapping[username.lower()] = d["id"]
                    mapping[d["name"].lower()] = d["id"]
            if urls:
                await dispatch_task("run_instagram_scan_task", [urls, job_id, mapping, campaign_id_str], job_id, "instagram")
        elif channel == "facebook":
            urls = [d["facebook_url"] for d in dist_list if d.get("facebook_url")]
            mapping = {d["name"].lower(): d["id"] for d in dist_list}
            if urls:
                await dispatch_task("run_facebook_scan_task", [urls, job_id, mapping, campaign_id_str, "facebook"], job_id, "facebook")
        elif channel == "website":
            urls = [d["website_url"] for d in dist_list if d.get("website_url")]
            mapping = {
                d["website_url"].replace("https://", "").replace("http://", "").split("/")[0]: d["id"]
                for d in dist_list if d.get("website_url")
            }
            if urls:
                await dispatch_task("run_website_scan_task", [urls, job_id, mapping, campaign_id_str], job_id, "website")

        created_jobs.append({"id": job_id, "source": channel})

    log.info("Batch scan started for org %s: %d jobs across %s",
             user.org_id, len(created_jobs), [j["source"] for j in created_jobs])

    return {
        "message": f"Batch scan started — {len(created_jobs)} scan(s) queued",
        "jobs": created_jobs,
    }


@router.post("/quick-scan", summary="Quick scan")
async def quick_scan(
    source: ScanSource,
    user: AuthUser = Depends(get_current_user),
):
    """
    Quick scan - starts a scan and immediately begins analysis.
    """
    job = await start_scan(
        ScanJobCreate(
            organization_id=user.org_id,
            source=source
        ),
        user
    )
    
    return {
        "message": "Quick scan started",
        "job_id": job["id"],
        "source": source.value
    }


@router.post("/reprocess-unprocessed", summary="Reprocess unprocessed images")
async def reprocess_unprocessed_images(
    campaign_id: UUID,
    limit: int = 100,
    user: AuthUser = Depends(get_current_user),
):
    """
    Reprocess images that were never analyzed.
    Runs as a background task.
    """
    from ..tasks import dispatch_task

    campaign = supabase.table("campaigns")\
        .select("organization_id")\
        .eq("id", str(campaign_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    org_scan_jobs = supabase.table("scan_jobs")\
        .select("id")\
        .eq("organization_id", str(user.org_id))\
        .execute()
    org_job_ids = [j["id"] for j in (org_scan_jobs.data or [])]

    if not org_job_ids:
        return {"message": "No scan jobs found for your organization", "count": 0}

    unprocessed = supabase.table("discovered_images")\
        .select("id", count="exact")\
        .in_("scan_job_id", org_job_ids)\
        .eq("is_processed", False)\
        .limit(limit)\
        .execute()
    
    if not (unprocessed.count or 0):
        return {"message": "No unprocessed images found", "count": 0}
    
    assets = supabase.table("assets")\
        .select("id", count="exact")\
        .eq("campaign_id", str(campaign_id))\
        .execute()
    
    if not (assets.count or 0):
        return {"message": "No campaign assets to match against", "count": 0}
    
    dispatched = await dispatch_task(
        "run_reprocess_images_task",
        [str(campaign_id), limit],
        str(campaign_id),
        "reprocess_images",
    )
    if not dispatched:
        raise HTTPException(status_code=503, detail="Failed to queue reprocessing task")

    return {
        "message": "Reprocessing queued",
        "image_count": unprocessed.count,
        "asset_count": assets.count,
    }


@router.get("/debug/{scan_id}", summary="Debug scan details")
async def debug_scan(scan_id: UUID, user: AuthUser = Depends(get_current_user)):
    """
    Debug endpoint to inspect scan details and identify issues.
    Only available when ENABLE_DANGEROUS_ENDPOINTS=true.
    """
    from ..config import get_settings
    if not get_settings().enable_dangerous_endpoints:
        raise HTTPException(status_code=403, detail="Debug endpoint is disabled in this environment")

    job = supabase.table("scan_jobs")\
        .select("*")\
        .eq("id", str(scan_id))\
        .eq("organization_id", str(user.org_id))\
        .single()\
        .execute()
    
    if not job.data:
        return {"error": "Scan job not found"}
    
    # Get discovered images
    discovered = supabase.table("discovered_images")\
        .select("*")\
        .eq("scan_job_id", str(scan_id))\
        .execute()
    
    # Get campaign assets if campaign_id exists
    assets = []
    if job.data.get("campaign_id"):
        assets_result = supabase.table("assets")\
            .select("*")\
            .eq("campaign_id", job.data["campaign_id"])\
            .execute()
        assets = assets_result.data
    
    # Get matches for this scan's discovered images
    matches = []
    if discovered.data:
        discovered_ids = [d["id"] for d in discovered.data]
        matches_result = supabase.table("matches")\
            .select("*")\
            .in_("discovered_image_id", discovered_ids)\
            .execute()
        matches = matches_result.data
    
    # Build debug report
    return {
        "scan_job": {
            "id": job.data["id"],
            "status": job.data["status"],
            "source": job.data["source"],
            "campaign_id": job.data.get("campaign_id"),
            "total_items": job.data.get("total_items", 0),
            "processed_items": job.data.get("processed_items", 0),
            "matches_count": job.data.get("matches_count", 0),
            "error_message": job.data.get("error_message"),
        },
        "discovered_images": {
            "count": len(discovered.data) if discovered.data else 0,
            "processed": len([d for d in discovered.data if d.get("is_processed")]) if discovered.data else 0,
            "unprocessed": len([d for d in discovered.data if not d.get("is_processed")]) if discovered.data else 0,
            "images": [
                {
                    "id": d["id"],
                    "source_type": d.get("source_type"),
                    "channel": d.get("channel"),
                    "is_processed": d.get("is_processed"),
                    "image_url": d["image_url"][:100] + "..." if len(d["image_url"]) > 100 else d["image_url"],
                    "distributor_id": d.get("distributor_id"),
                }
                for d in (discovered.data or [])[:10]  # Limit to first 10
            ]
        },
        "campaign_assets": {
            "count": len(assets),
            "assets": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "file_url": a["file_url"][:100] + "..." if len(a["file_url"]) > 100 else a["file_url"],
                }
                for a in assets[:10]  # Limit to first 10
            ],
            "warning": "No campaign assets found - cannot match!" if len(assets) == 0 and job.data.get("campaign_id") else None
        },
        "matches": {
            "count": len(matches),
            "matches": [
                {
                    "id": m["id"],
                    "asset_id": m["asset_id"],
                    "confidence_score": m.get("confidence_score"),
                    "match_type": m.get("match_type"),
                    "compliance_status": m.get("compliance_status"),
                }
                for m in matches[:10]  # Limit to first 10
            ]
        },
        "diagnosis": {
            "has_campaign": job.data.get("campaign_id") is not None,
            "has_discovered_images": len(discovered.data) > 0 if discovered.data else False,
            "has_campaign_assets": len(assets) > 0,
            "has_matches": len(matches) > 0,
            "all_images_processed": all(d.get("is_processed") for d in discovered.data) if discovered.data else True,
            "issues": _get_scan_issues(job.data, discovered.data, assets, matches)
        }
    }


def _get_scan_issues(job, discovered, assets, matches):
    """Identify potential issues with the scan."""
    issues = []
    
    if not job.get("campaign_id"):
        issues.append("No campaign linked to scan - cannot match against assets")
    
    if not discovered:
        issues.append("No images were discovered during the scan")
    elif len(discovered) == 0:
        issues.append("Scan completed but no images found")
    
    if job.get("campaign_id") and len(assets) == 0:
        issues.append("Campaign has no assets uploaded - upload assets before scanning")
    
    if discovered and len(discovered) > 0 and len(matches) == 0:
        unprocessed = [d for d in discovered if not d.get("is_processed")]
        if len(unprocessed) > 0:
            issues.append(f"{len(unprocessed)} images haven't been processed yet")
        else:
            issues.append("All images processed but no matches found - assets may not match discovered images or thresholds too high")
    
    # Check for asset URL accessibility issues
    for asset in assets:
        url = asset.get("file_url", "")
        if "supabase" in url.lower() and "/storage/v1/" in url:
            if "public" not in url.lower():
                issues.append(f"Asset '{asset.get('name')}' may not be publicly accessible (private Supabase storage)")
    
    if job.get("status") == "failed":
        issues.append(f"Scan failed: {job.get('error_message', 'Unknown error')}")
    
    return issues if issues else ["No issues detected"]
