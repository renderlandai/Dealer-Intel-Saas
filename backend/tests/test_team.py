"""Tests for team management — members, invites, removal."""
import time
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest

from tests.conftest import USER_A_ID, USER_B_ID, ORG_A_ID, ORG_B_ID

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long"

FAKE_NOW = "2025-01-15T12:00:00+00:00"
FAKE_INVITE_ID = str(uuid4())


def _token_for(user_id: UUID, email: str = "u@test.com") -> str:
    return jwt.encode({
        "sub": str(user_id),
        "email": email,
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }, JWT_SECRET, algorithm="HS256")


def _inject_user(mock_supabase, org_id: UUID, role: str = "owner"):
    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"organization_id": str(org_id), "role": role}
    )


def _headers(user_id: UUID) -> dict:
    return {"Authorization": f"Bearer {_token_for(user_id)}"}


def _table_side_effect(org_id: UUID, *, role="owner", members=None, org_plan=None):
    if org_plan is None:
        org_plan = {"plan": "professional", "plan_status": "active", "trial_expires_at": None}
    if members is None:
        members = []

    member_count = len(members)

    def side_effect(name):
        mock_table = MagicMock()
        if name == "user_profiles":
            mock_table.select.return_value.eq.return_value.single.return_value \
                .execute.return_value = MagicMock(
                data={"organization_id": str(org_id), "role": role}
            )
            mock_table.select.return_value.eq.return_value.order.return_value \
                .execute.return_value = MagicMock(data=members)
            mock_table.select.return_value.eq.return_value \
                .execute.return_value = MagicMock(data=members, count=member_count)
            mock_table.select.return_value.in_.return_value \
                .execute.return_value = MagicMock(data=members)
            mock_table.select.return_value.eq.return_value \
                .eq.return_value.maybe_single.return_value \
                .execute.return_value = MagicMock(data=None)
        elif name == "organizations":
            mock_table.select.return_value.eq.return_value.single.return_value \
                .execute.return_value = MagicMock(data=org_plan)
        elif name == "pending_invites":
            mock_table.select.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.return_value = MagicMock(data=[])
            mock_table.select.return_value.eq.return_value \
                .gte.return_value.order.return_value \
                .execute.return_value = MagicMock(data=[])
            mock_table.select.return_value.eq.return_value \
                .gte.return_value.execute.return_value = MagicMock(data=[], count=0)
            mock_table.select.return_value.eq.return_value \
                .execute.return_value = MagicMock(data=[], count=0)
            mock_table.insert.return_value.execute.return_value = MagicMock(
                data=[{
                    "id": FAKE_INVITE_ID,
                    "email": "new@test.com",
                    "role": "member",
                    "expires_at": "2025-02-15T12:00:00+00:00",
                    "created_at": FAKE_NOW,
                }]
            )
        return mock_table

    return side_effect


# ------------------------------------------------------------------
# List members
# ------------------------------------------------------------------

class TestListMembers:
    def test_list_members(self, client, mock_supabase):
        members = [
            {"user_id": str(USER_A_ID), "role": "owner", "created_at": FAKE_NOW},
        ]
        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, role="owner", members=members,
        )
        mock_supabase.auth.admin.get_user_by_id.return_value = MagicMock(
            user=MagicMock(email="a@test.com")
        )

        resp = client.get("/api/v1/team/members", headers=_headers(USER_A_ID))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ------------------------------------------------------------------
# Invite
# ------------------------------------------------------------------

class TestInvite:
    def test_invite_requires_admin(self, client, mock_supabase):
        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, role="member",
        )

        resp = client.post(
            "/api/v1/team/invites",
            headers=_headers(USER_A_ID),
            json={"email": "new@test.com", "role": "member"},
        )
        assert resp.status_code == 403

    def test_invite_success(self, client, mock_supabase):
        members = [
            {"user_id": str(USER_A_ID), "role": "owner", "created_at": FAKE_NOW},
        ]
        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, role="owner", members=members,
        )
        mock_supabase.auth.admin.get_user_by_id.side_effect = Exception("no auth in test")

        resp = client.post(
            "/api/v1/team/invites",
            headers=_headers(USER_A_ID),
            json={"email": "new@test.com", "role": "member"},
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "new@test.com"


# ------------------------------------------------------------------
# Remove member
# ------------------------------------------------------------------

class TestRemove:
    def test_cannot_remove_self(self, client, mock_supabase):
        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, role="owner",
        )

        resp = client.delete(
            f"/api/v1/team/members/{USER_A_ID}",
            headers=_headers(USER_A_ID),
        )
        assert resp.status_code == 400
        assert "yourself" in resp.json()["detail"].lower()
