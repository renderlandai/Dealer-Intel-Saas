"""JWT authentication dependency for FastAPI routes."""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

import httpx
import jwt
from cachetools import TTLCache
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .database import supabase

log = logging.getLogger("dealer_intel.auth")

_bearer = HTTPBearer(auto_error=False)
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


class AuthUser:
    """Authenticated user context injected into route handlers."""
    __slots__ = ("user_id", "org_id", "role", "email")

    def __init__(self, user_id: UUID, org_id: UUID, role: str, email: str = ""):
        self.user_id = user_id
        self.org_id = org_id
        self.role = role
        self.email = email


_profile_cache: TTLCache = TTLCache(maxsize=10_000, ttl=300)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthUser:
    """Verify the Supabase JWT and resolve the user's organization."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    token = creds.credentials
    payload = None

    # Try JWKS (ECC / asymmetric) verification first
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except Exception as jwks_err:
        log.debug("JWKS verification failed, trying HS256 fallback: %s", jwks_err)

    # Fallback to legacy HS256 secret
    if payload is None and settings.supabase_jwt_secret:
        try:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        except jwt.InvalidTokenError as exc:
            log.warning("Invalid JWT (HS256 fallback): %s", exc)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")

    try:
        user_id = UUID(sub)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    email = payload.get("email", "")

    if user_id in _profile_cache:
        cached = _profile_cache[user_id]
        return AuthUser(user_id=user_id, org_id=cached["org_id"], role=cached["role"], email=email)

    try:
        result = (
            supabase.table("user_profiles")
            .select("organization_id, role")
            .eq("user_id", str(user_id))
            .single()
            .execute()
        )
        profile = result.data
    except Exception:
        profile = None

    if not profile:
        try:
            org_id = await _auto_provision_user(user_id, email)
            role = "owner"
        except Exception as prov_err:
            log.warning("Auto-provision failed (likely race): %s — retrying lookup", prov_err)
            retry = (
                supabase.table("user_profiles")
                .select("organization_id, role")
                .eq("user_id", str(user_id))
                .maybe_single()
                .execute()
            )
            if not retry.data:
                raise HTTPException(status_code=500, detail="Failed to provision user profile")
            org_id = UUID(retry.data["organization_id"])
            role = retry.data.get("role", "member")
    else:
        org_id = UUID(profile["organization_id"])
        role = profile.get("role", "member")

    _profile_cache[user_id] = {"org_id": org_id, "role": role}

    return AuthUser(user_id=user_id, org_id=org_id, role=role, email=email)


async def _auto_provision_user(user_id: UUID, email: str) -> UUID:
    """First-time login: create an organization with a 14-day free trial."""
    from datetime import datetime, timedelta, timezone

    org_name = email.split("@")[0].title() if email else "My Organization"
    trial_end = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()

    org = supabase.table("organizations").insert({
        "name": org_name,
        "slug": org_name.lower().replace(" ", "-"),
        "plan": "free",
        "plan_status": "trialing",
        "trial_expires_at": trial_end,
    }).execute()
    org_id = UUID(org.data[0]["id"])

    supabase.table("user_profiles").insert({
        "user_id": str(user_id),
        "organization_id": str(org_id),
        "role": "owner",
    }).execute()

    log.info("Auto-provisioned org %s for user %s (%s)", org_id, user_id, email)
    return org_id


def clear_profile_cache(user_id: Optional[UUID] = None) -> None:
    if user_id:
        _profile_cache.pop(user_id, None)
    else:
        _profile_cache.clear()
