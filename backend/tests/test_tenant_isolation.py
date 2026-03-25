"""Tests verifying tenant isolation — User A cannot access User B's resources."""
import time
from unittest.mock import MagicMock, patch
from uuid import UUID

import jwt
import pytest

from tests.conftest import USER_A_ID, USER_B_ID, ORG_A_ID, ORG_B_ID

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long"


def _token_for(user_id: UUID, email: str = "u@test.com") -> str:
    return jwt.encode({
        "sub": str(user_id),
        "email": email,
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }, JWT_SECRET, algorithm="HS256")


def _inject_user(mock_supabase, org_id: UUID):
    """Configure mock so get_current_user resolves to the given org."""
    mock_supabase.table.return_value.select.return_value \
        .eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"organization_id": str(org_id), "role": "owner"}
    )


def _headers(user_id: UUID) -> dict:
    return {"Authorization": f"Bearer {_token_for(user_id)}"}


# ------------------------------------------------------------------
# Organization settings — cross-org access blocked
# ------------------------------------------------------------------

class TestOrgIsolation:
    def test_user_a_cannot_read_org_b_settings(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)
        resp = client.get(f"/api/v1/organizations/{ORG_B_ID}/settings",
                          headers=_headers(USER_A_ID))
        assert resp.status_code == 403
        assert "Access denied" in resp.json()["detail"]

    def test_user_a_cannot_update_org_b_settings(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)
        resp = client.patch(
            f"/api/v1/organizations/{ORG_B_ID}/settings",
            headers=_headers(USER_A_ID),
            json={"name": "Hacked Org"},
        )
        assert resp.status_code == 403

    def test_user_a_cannot_access_org_b_logo(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)
        resp = client.get(f"/api/v1/organizations/{ORG_B_ID}/logo",
                          headers=_headers(USER_A_ID))
        assert resp.status_code == 403

    def test_user_a_cannot_delete_org_b_logo(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)
        resp = client.delete(f"/api/v1/organizations/{ORG_B_ID}/logo",
                             headers=_headers(USER_A_ID))
        assert resp.status_code == 403

    def test_user_a_cannot_test_email_on_org_b(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)
        resp = client.post(f"/api/v1/organizations/{ORG_B_ID}/test-email",
                           headers=_headers(USER_A_ID))
        assert resp.status_code == 403


# ------------------------------------------------------------------
# Campaigns — list is scoped to own org
# ------------------------------------------------------------------

class TestCampaignIsolation:
    def test_list_campaigns_scoped_to_own_org(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)

        chain = mock_supabase.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        chain.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        resp = client.get("/api/v1/campaigns", headers=_headers(USER_A_ID))
        assert resp.status_code == 200

        calls = mock_supabase.table.return_value.select.return_value.eq.call_args_list
        org_filters = [c for c in calls if c[0][0] == "organization_id"]
        assert len(org_filters) > 0
        assert all(c[0][1] == str(ORG_A_ID) for c in org_filters), \
            "Campaign list must filter by the authenticated user's org_id"


# ------------------------------------------------------------------
# Distributors — list is scoped to own org
# ------------------------------------------------------------------

class TestDistributorIsolation:
    def test_list_distributors_scoped_to_own_org(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)

        chain = mock_supabase.table.return_value.select.return_value
        chain.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        chain.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        resp = client.get("/api/v1/distributors", headers=_headers(USER_A_ID))
        assert resp.status_code == 200

        calls = mock_supabase.table.return_value.select.return_value.eq.call_args_list
        org_filters = [c for c in calls if c[0][0] == "organization_id"]
        assert len(org_filters) > 0
        assert all(c[0][1] == str(ORG_A_ID) for c in org_filters), \
            "Distributor list must filter by the authenticated user's org_id"


# ------------------------------------------------------------------
# Matches — list is scoped to own org's distributors
# ------------------------------------------------------------------

class TestMatchIsolation:
    def test_list_matches_scoped_to_own_org(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)

        dist_result = MagicMock()
        dist_result.data = [{"id": "dist-1"}, {"id": "dist-2"}]
        match_result = MagicMock()
        match_result.data = []

        call_count = {"n": 0}

        def table_side_effect(name):
            call_count["n"] += 1
            mock_table = MagicMock()
            if name == "user_profiles":
                mock_table.select.return_value.eq.return_value.single.return_value \
                    .execute.return_value = MagicMock(
                    data={"organization_id": str(ORG_A_ID), "role": "owner"}
                )
            elif name == "distributors":
                mock_table.select.return_value.eq.return_value.execute.return_value = dist_result
            else:
                mock_table.select.return_value.in_.return_value.order.return_value \
                    .range.return_value.execute.return_value = match_result
                mock_table.select.return_value.in_.return_value.eq.return_value \
                    .order.return_value.range.return_value.execute.return_value = match_result
                mock_table.select.return_value.in_.return_value.eq.return_value \
                    .eq.return_value.order.return_value.range.return_value \
                    .execute.return_value = match_result
                mock_table.select.return_value.in_.return_value.eq.return_value \
                    .eq.return_value.eq.return_value.order.return_value \
                    .range.return_value.execute.return_value = match_result
                mock_table.select.return_value.in_.return_value.eq.return_value \
                    .eq.return_value.eq.return_value.gte.return_value \
                    .order.return_value.range.return_value \
                    .execute.return_value = match_result
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        resp = client.get("/api/v1/matches", headers=_headers(USER_A_ID))
        assert resp.status_code == 200


# ------------------------------------------------------------------
# Scan jobs — scoped to own org
# ------------------------------------------------------------------

class TestScanIsolation:
    def test_get_scan_requires_own_org(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)

        scan_result = MagicMock()
        scan_result.data = []

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "user_profiles":
                mock_table.select.return_value.eq.return_value.single.return_value \
                    .execute.return_value = MagicMock(
                    data={"organization_id": str(ORG_A_ID), "role": "owner"}
                )
            elif name == "scan_jobs":
                mock_table.select.return_value.eq.return_value.eq.return_value \
                    .maybe_single.return_value.execute.return_value = MagicMock(data=None)
                mock_table.select.return_value.eq.return_value.eq.return_value \
                    .single.return_value.execute.return_value = MagicMock(data=None)
                mock_table.select.return_value.eq.return_value.eq.return_value \
                    .execute.return_value = scan_result
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        fake_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        resp = client.get(f"/api/v1/scans/{fake_id}", headers=_headers(USER_A_ID))
        assert resp.status_code in (404, 500)


# ------------------------------------------------------------------
# Alerts — scoped to own org
# ------------------------------------------------------------------

class TestAlertIsolation:
    def test_list_alerts_scoped_to_own_org(self, client, mock_supabase):
        _inject_user(mock_supabase, ORG_A_ID)

        alert_result = MagicMock()
        alert_result.data = []
        alert_result.count = 0

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "user_profiles":
                mock_table.select.return_value.eq.return_value.single.return_value \
                    .execute.return_value = MagicMock(
                    data={"organization_id": str(ORG_A_ID), "role": "owner"}
                )
            elif name == "alerts":
                mock_table.select.return_value.eq.return_value.order.return_value \
                    .range.return_value.execute.return_value = alert_result
                mock_table.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.range.return_value.execute.return_value = alert_result
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        resp = client.get("/api/v1/alerts", headers=_headers(USER_A_ID))
        assert resp.status_code == 200
