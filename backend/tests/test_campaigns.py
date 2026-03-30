"""Tests for campaign CRUD operations."""
import time
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest

from tests.conftest import USER_A_ID, USER_B_ID, ORG_A_ID, ORG_B_ID

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long"

FAKE_CAMPAIGN_ID = str(uuid4())
FAKE_NOW = "2025-01-15T12:00:00+00:00"


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


def _campaign_row(campaign_id: str = FAKE_CAMPAIGN_ID, org_id: UUID = ORG_A_ID) -> dict:
    return {
        "id": campaign_id,
        "organization_id": str(org_id),
        "name": "Summer Promo",
        "description": "Test campaign",
        "status": "active",
        "start_date": None,
        "end_date": None,
        "created_at": FAKE_NOW,
        "updated_at": FAKE_NOW,
        "asset_count": 0,
    }


def _count_result(n: int = 0, data=None):
    return MagicMock(data=data or [], count=n)


def _table_side_effect(mock_supabase, org_id: UUID, *, campaign_data=None, assets_data=None, org_plan=None, role="owner"):
    """Build a table() side_effect that routes by table name."""
    if org_plan is None:
        org_plan = {"plan": "professional", "plan_status": "active", "trial_expires_at": None}

    rows = []
    if campaign_data is not None:
        rows = campaign_data if isinstance(campaign_data, list) else [campaign_data]

    def side_effect(name):
        mock_table = MagicMock()
        if name == "user_profiles":
            mock_table.select.return_value.eq.return_value.single.return_value \
                .execute.return_value = MagicMock(
                data={"organization_id": str(org_id), "role": role}
            )
        elif name == "organizations":
            mock_table.select.return_value.eq.return_value.single.return_value \
                .execute.return_value = MagicMock(data=org_plan)
        elif name == "campaigns":
            data_result = MagicMock(data=rows, count=len(rows))
            empty_result = _count_result()
            mock_table.select.return_value.eq.return_value.eq.return_value \
                .execute.return_value = data_result
            mock_table.select.return_value.eq.return_value.eq.return_value \
                .order.return_value.execute.return_value = data_result
            mock_table.select.return_value.eq.return_value \
                .order.return_value.execute.return_value = data_result
            mock_table.insert.return_value.execute.return_value = MagicMock(data=rows)
            mock_table.delete.return_value.eq.return_value.eq.return_value \
                .execute.return_value = MagicMock(data=[])
        elif name == "assets":
            mock_table.select.return_value.in_.return_value.execute.return_value = MagicMock(
                data=assets_data or []
            )
            mock_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=assets_data or [], count=len(assets_data or [])
            )
        return mock_table

    return side_effect


# ------------------------------------------------------------------
# Create campaign
# ------------------------------------------------------------------

class TestCreateCampaign:
    def test_create_campaign_success(self, client, mock_supabase):
        row = _campaign_row()
        mock_supabase.table.side_effect = _table_side_effect(
            mock_supabase, ORG_A_ID, campaign_data=row,
        )

        resp = client.post(
            "/api/v1/campaigns",
            headers=_headers(USER_A_ID),
            json={"name": "Summer Promo", "description": "Test campaign"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Summer Promo"

    def test_create_campaign_missing_name(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)

        resp = client.post(
            "/api/v1/campaigns",
            headers=_headers(USER_A_ID),
            json={"description": "no name"},
        )
        assert resp.status_code == 422


# ------------------------------------------------------------------
# Get campaign
# ------------------------------------------------------------------

class TestGetCampaign:
    def test_get_campaign_scoped(self, client, mock_supabase):
        row = _campaign_row()
        mock_supabase.table.side_effect = _table_side_effect(
            mock_supabase, ORG_A_ID, campaign_data=row,
        )

        resp = client.get(
            f"/api/v1/campaigns/{FAKE_CAMPAIGN_ID}",
            headers=_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == FAKE_CAMPAIGN_ID

    def test_get_nonexistent_returns_404(self, client, mock_supabase):
        mock_supabase.table.side_effect = _table_side_effect(
            mock_supabase, ORG_A_ID, campaign_data=None,
        )

        resp = client.get(
            f"/api/v1/campaigns/{uuid4()}",
            headers=_headers(USER_A_ID),
        )
        assert resp.status_code == 404


# ------------------------------------------------------------------
# Delete campaign
# ------------------------------------------------------------------

class TestDeleteCampaign:
    def test_delete_own_campaign(self, client, mock_supabase):
        row = _campaign_row()
        mock_supabase.table.side_effect = _table_side_effect(
            mock_supabase, ORG_A_ID, campaign_data=row,
        )

        resp = client.delete(
            f"/api/v1/campaigns/{FAKE_CAMPAIGN_ID}",
            headers=_headers(USER_A_ID),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"


# ------------------------------------------------------------------
# List campaigns with status filter
# ------------------------------------------------------------------

class TestListCampaigns:
    def test_list_includes_status_filter(self, client, mock_supabase):
        row = _campaign_row()

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "user_profiles":
                mock_table.select.return_value.eq.return_value.single.return_value \
                    .execute.return_value = MagicMock(
                    data={"organization_id": str(ORG_A_ID), "role": "owner"}
                )
            elif name == "campaigns":
                chain = mock_table.select.return_value
                chain.eq.return_value.eq.return_value.order.return_value \
                    .execute.return_value = MagicMock(data=[row])
                chain.eq.return_value.order.return_value \
                    .execute.return_value = MagicMock(data=[row])
            elif name == "assets":
                mock_table.select.return_value.in_.return_value \
                    .execute.return_value = MagicMock(data=[])
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        resp = client.get(
            "/api/v1/campaigns?status=active",
            headers=_headers(USER_A_ID),
        )
        assert resp.status_code == 200

        eq_calls = mock_supabase.table.return_value.select.return_value.eq.call_args_list
        status_filters = [c for c in eq_calls if c[0][0] == "status"]
        if status_filters:
            assert status_filters[0][0][1] == "active"


# ------------------------------------------------------------------
# Rate limiting
# ------------------------------------------------------------------

class TestRateLimit:
    def test_create_campaign_rate_limited(self, client, mock_supabase):
        row = _campaign_row()
        mock_supabase.table.side_effect = _table_side_effect(
            mock_supabase, ORG_A_ID, campaign_data=row,
        )

        statuses = []
        for _ in range(15):
            resp = client.post(
                "/api/v1/campaigns",
                headers=_headers(USER_A_ID),
                json={"name": "Spam Campaign"},
            )
            statuses.append(resp.status_code)

        assert 429 in statuses, "Expected at least one 429 after 10+ rapid requests"
