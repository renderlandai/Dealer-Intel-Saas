"""Tests for JWT authentication, auto-provisioning, and profile cache."""
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import UUID

import jwt
import pytest

from tests.conftest import USER_A_ID, ORG_A_ID

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long"


def _make_token(sub: str = str(USER_A_ID), email: str = "a@test.com",
                exp_delta: int = 3600, secret: str = JWT_SECRET) -> str:
    payload = {
        "sub": sub,
        "email": email,
        "aud": "authenticated",
        "exp": int(time.time()) + exp_delta,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------
# Missing token
# ------------------------------------------------------------------

class TestMissingToken:
    def test_no_auth_header_returns_401(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"] or "Not authenticated" in resp.json()["detail"]


# ------------------------------------------------------------------
# Expired token
# ------------------------------------------------------------------

class TestExpiredToken:
    def test_expired_jwt_returns_401(self, client):
        token = _make_token(exp_delta=-3600)
        resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp.status_code == 401


# ------------------------------------------------------------------
# Invalid token
# ------------------------------------------------------------------

class TestInvalidToken:
    def test_garbage_token_returns_401(self, client):
        resp = client.get("/api/v1/auth/me", headers=_auth_header("not.a.jwt"))
        assert resp.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        token = _make_token(secret="wrong-secret-that-is-long-enough-32")
        resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp.status_code == 401


# ------------------------------------------------------------------
# Valid token — existing user
# ------------------------------------------------------------------

class TestValidToken:
    def test_existing_user_returns_profile(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"organization_id": str(ORG_A_ID), "role": "owner"}
        )

        token = _make_token()
        resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == str(USER_A_ID)
        assert body["organization_id"] == str(ORG_A_ID)
        assert body["role"] == "owner"


# ------------------------------------------------------------------
# Auto-provisioning — new user
# ------------------------------------------------------------------

class TestAutoProvisioning:
    def test_new_user_gets_provisioned(self, client, mock_supabase):
        new_org_id = "33333333-3333-3333-3333-333333333333"
        profile_select = MagicMock()
        profile_select.data = None
        profile_select.execute = MagicMock(side_effect=Exception("no rows"))

        org_insert = MagicMock()
        org_insert.data = [{"id": new_org_id}]

        profile_insert = MagicMock()
        profile_insert.data = [{"user_id": str(USER_A_ID), "organization_id": new_org_id}]

        call_count = {"n": 0}

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "user_profiles":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    mock_table.select.return_value.eq.return_value.single.return_value.execute.side_effect = Exception("no rows")
                else:
                    mock_table.insert.return_value.execute.return_value = profile_insert
            elif name == "organizations":
                mock_table.insert.return_value.execute.return_value = org_insert
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        token = _make_token()
        resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["organization_id"] == new_org_id
        assert body["role"] == "owner"


# ------------------------------------------------------------------
# Profile cache — TTL behavior
# ------------------------------------------------------------------

class TestProfileCache:
    def test_second_request_uses_cache(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"organization_id": str(ORG_A_ID), "role": "admin"}
        )

        token = _make_token()
        resp1 = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp1.status_code == 200

        mock_supabase.reset_mock()

        resp2 = client.get("/api/v1/auth/me", headers=_auth_header(token))
        assert resp2.status_code == 200
        assert resp2.json()["role"] == "admin"
        mock_supabase.table.assert_not_called()

    def test_cache_is_ttl_bounded(self):
        from app.auth import _profile_cache
        assert hasattr(_profile_cache, "ttl")
        assert _profile_cache.ttl == 300
        assert _profile_cache.maxsize == 10_000

    def test_clear_cache_removes_user(self):
        from app.auth import _profile_cache, clear_profile_cache
        _profile_cache[USER_A_ID] = {"org_id": ORG_A_ID, "role": "owner"}
        assert USER_A_ID in _profile_cache
        clear_profile_cache(USER_A_ID)
        assert USER_A_ID not in _profile_cache

    def test_clear_cache_all(self):
        from app.auth import _profile_cache, clear_profile_cache
        from uuid import uuid4
        _profile_cache[uuid4()] = {"org_id": ORG_A_ID, "role": "member"}
        _profile_cache[uuid4()] = {"org_id": ORG_A_ID, "role": "member"}
        assert len(_profile_cache) >= 2
        clear_profile_cache()
        assert len(_profile_cache) == 0
