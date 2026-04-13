"""Cached organization lookups shared across routers.

These queries are hit on nearly every API request and always return the same
data for a given org within a short window. Caching them eliminates redundant
Supabase round-trips (~200-400ms each).
"""
from typing import Dict, List, Optional
from cachetools import TTLCache

from .database import supabase

_dist_cache: TTLCache = TTLCache(maxsize=500, ttl=30)
_campaign_cache: TTLCache = TTLCache(maxsize=500, ttl=30)
_asset_cache: TTLCache = TTLCache(maxsize=500, ttl=30)


def get_org_distributor_ids(org_id: str) -> List[str]:
    """Return all distributor IDs belonging to an organization (cached 30s)."""
    if org_id in _dist_cache:
        return _dist_cache[org_id]
    result = supabase.table("distributors") \
        .select("id") \
        .eq("organization_id", org_id) \
        .execute()
    ids = [d["id"] for d in (result.data or [])]
    _dist_cache[org_id] = ids
    return ids


def get_org_campaign_ids(org_id: str) -> List[str]:
    """Return all campaign IDs belonging to an organization (cached 30s)."""
    if org_id in _campaign_cache:
        return _campaign_cache[org_id]
    result = supabase.table("campaigns") \
        .select("id") \
        .eq("organization_id", org_id) \
        .execute()
    ids = [c["id"] for c in (result.data or [])]
    _campaign_cache[org_id] = ids
    return ids


def get_org_asset_ids(org_id: str) -> List[str]:
    """Return all asset IDs belonging to an organization's campaigns (cached 30s)."""
    if org_id in _asset_cache:
        return _asset_cache[org_id]
    campaign_ids = get_org_campaign_ids(org_id)
    if not campaign_ids:
        _asset_cache[org_id] = []
        return []
    result = supabase.table("assets") \
        .select("id") \
        .in_("campaign_id", campaign_ids) \
        .execute()
    ids = [a["id"] for a in (result.data or [])]
    _asset_cache[org_id] = ids
    return ids


def invalidate_org(org_id: Optional[str] = None) -> None:
    """Clear cached data for an org (or all orgs)."""
    if org_id:
        _dist_cache.pop(org_id, None)
        _campaign_cache.pop(org_id, None)
        _asset_cache.pop(org_id, None)
    else:
        _dist_cache.clear()
        _campaign_cache.clear()
        _asset_cache.clear()
