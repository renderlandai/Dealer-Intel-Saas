"""Page hit cache — tracks which pages produced matches for scan optimization.

On repeat scans, hot pages are scanned first. If all campaign assets are
matched from cached pages alone (early stop), full page discovery is skipped
entirely, saving sitemap/crawl HTTP calls, Playwright loads, and AI API costs.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from uuid import UUID

from ..database import supabase

log = logging.getLogger("dealer_intel.page_cache")


def get_cached_pages(
    org_id: str,
    distributor_id: str,
    campaign_id: Optional[str] = None,
) -> List[str]:
    """Return cached page URLs that previously produced matches, ordered by hit count."""
    q = supabase.table("page_hit_cache") \
        .select("page_url, hit_count") \
        .eq("organization_id", org_id) \
        .eq("distributor_id", distributor_id) \
        .order("hit_count", desc=True)

    if campaign_id:
        q = q.eq("campaign_id", campaign_id)

    try:
        result = q.execute()
        urls = [row["page_url"] for row in (result.data or [])]
        if urls:
            log.info("Page cache: %d hot page(s) for distributor %s", len(urls), distributor_id)
        return urls
    except Exception as e:
        log.warning("Page cache lookup failed: %s", e)
        return []


def record_page_hits(
    org_id: str,
    distributor_id: str,
    campaign_id: Optional[str],
    page_matches: Dict[str, Set[str]],
) -> None:
    """Record which pages produced matches after a scan completes.

    Args:
        page_matches: mapping of page_url -> set of matched asset_ids
    """
    if not page_matches:
        return

    now = datetime.now(timezone.utc).isoformat()

    for page_url, asset_ids in page_matches.items():
        try:
            existing = supabase.table("page_hit_cache") \
                .select("id, hit_count, asset_ids_matched") \
                .eq("organization_id", org_id) \
                .eq("distributor_id", distributor_id) \
                .eq("page_url", page_url) \
                .maybe_single().execute()

            if campaign_id:
                existing = supabase.table("page_hit_cache") \
                    .select("id, hit_count, asset_ids_matched") \
                    .eq("organization_id", org_id) \
                    .eq("distributor_id", distributor_id) \
                    .eq("campaign_id", campaign_id) \
                    .eq("page_url", page_url) \
                    .maybe_single().execute()

            if existing and existing.data:
                prev_assets = set(existing.data.get("asset_ids_matched") or [])
                merged = list(prev_assets | asset_ids)
                supabase.table("page_hit_cache") \
                    .update({
                        "hit_count": existing.data["hit_count"] + 1,
                        "last_hit_at": now,
                        "asset_ids_matched": merged,
                    }) \
                    .eq("id", existing.data["id"]).execute()
            else:
                supabase.table("page_hit_cache").insert({
                    "organization_id": org_id,
                    "distributor_id": distributor_id,
                    "campaign_id": campaign_id,
                    "page_url": page_url,
                    "hit_count": 1,
                    "last_hit_at": now,
                    "asset_ids_matched": list(asset_ids),
                }).execute()

        except Exception as e:
            log.warning("Failed to record page hit for %s: %s", page_url, e)

    log.info("Page cache updated: %d page(s) with matches for distributor %s",
             len(page_matches), distributor_id)


def prune_stale_entries(org_id: str, distributor_id: str, active_urls: List[str]) -> None:
    """Remove cache entries for pages that no longer exist in discovery."""
    if not active_urls:
        return

    try:
        cached = supabase.table("page_hit_cache") \
            .select("id, page_url") \
            .eq("organization_id", org_id) \
            .eq("distributor_id", distributor_id) \
            .execute()

        active_set = set(active_urls)
        stale_ids = [
            row["id"] for row in (cached.data or [])
            if row["page_url"] not in active_set
        ]

        if stale_ids:
            supabase.table("page_hit_cache") \
                .delete() \
                .in_("id", stale_ids) \
                .execute()
            log.info("Pruned %d stale cache entries for distributor %s", len(stale_ids), distributor_id)
    except Exception as e:
        log.warning("Cache pruning failed: %s", e)
