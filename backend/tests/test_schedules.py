"""Tests for scan schedule CRUD operations."""
import time
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest

from tests.conftest import USER_A_ID, USER_B_ID, ORG_A_ID, ORG_B_ID

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long"

FAKE_CAMPAIGN_ID = str(uuid4())
FAKE_SCHEDULE_ID = str(uuid4())
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


def _schedule_row(schedule_id: str = FAKE_SCHEDULE_ID, org_id: UUID = ORG_A_ID) -> dict:
    return {
        "id": schedule_id,
        "organization_id": str(org_id),
        "campaign_id": FAKE_CAMPAIGN_ID,
        "source": "google_ads",
        "frequency": "weekly",
        "run_at_time": "09:00",
        "run_on_day": 1,
        "is_active": True,
        "last_run_at": None,
        "next_run_at": FAKE_NOW,
        "created_at": FAKE_NOW,
        "updated_at": FAKE_NOW,
    }


def _table_side_effect(org_id: UUID, *, schedule_data=None, campaign_owned=True, org_plan=None, role="owner"):
    if org_plan is None:
        org_plan = {"plan": "professional", "plan_status": "active", "trial_expires_at": None}

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
            campaign_result = MagicMock(data={"organization_id": str(org_id)} if campaign_owned else None)
            mock_table.select.return_value.eq.return_value.eq.return_value \
                .single.return_value.execute.return_value = campaign_result
        elif name == "scan_schedules":
            if schedule_data is not None:
                rows = schedule_data if isinstance(schedule_data, list) else [schedule_data]
                mock_table.select.return_value.eq.return_value.order.return_value \
                    .execute.return_value = MagicMock(data=rows)
                mock_table.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.execute.return_value = MagicMock(data=rows)
                mock_table.select.return_value.eq.return_value.eq.return_value \
                    .execute.return_value = MagicMock(data=rows, count=0)
                mock_table.insert.return_value.execute.return_value = MagicMock(data=rows)
                mock_table.delete.return_value.eq.return_value.eq.return_value \
                    .execute.return_value = MagicMock(data=rows)
            else:
                mock_table.select.return_value.eq.return_value.order.return_value \
                    .execute.return_value = MagicMock(data=[])
                mock_table.select.return_value.eq.return_value.eq.return_value \
                    .execute.return_value = MagicMock(data=[], count=0)
                mock_table.delete.return_value.eq.return_value.eq.return_value \
                    .execute.return_value = MagicMock(data=[])
        return mock_table

    return side_effect


# ------------------------------------------------------------------
# Create schedule
# ------------------------------------------------------------------

class TestCreateSchedule:
    @patch("app.services.scheduler_service.compute_next_run")
    @patch("app.services.scheduler_service.upsert_job")
    def test_create_success(self, mock_upsert, mock_next_run, client, mock_supabase):
        from datetime import datetime, timezone
        mock_next_run.return_value = datetime(2025, 1, 20, 9, 0, tzinfo=timezone.utc)

        row = _schedule_row()
        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, schedule_data=row, campaign_owned=True,
        )

        resp = client.post(
            "/api/v1/schedules",
            headers=_headers(USER_A_ID),
            json={
                "campaign_id": FAKE_CAMPAIGN_ID,
                "source": "google_ads",
                "frequency": "weekly",
                "run_at_time": "09:00",
                "run_on_day": 1,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["source"] == "google_ads"
        mock_upsert.assert_called_once()

    @patch("app.services.scheduler_service.compute_next_run")
    @patch("app.services.scheduler_service.upsert_job")
    def test_create_validates_campaign_ownership(self, mock_upsert, mock_next_run, client, mock_supabase):
        from datetime import datetime, timezone
        mock_next_run.return_value = datetime(2025, 1, 20, 9, 0, tzinfo=timezone.utc)

        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, schedule_data=None, campaign_owned=False,
        )

        resp = client.post(
            "/api/v1/schedules",
            headers=_headers(USER_A_ID),
            json={
                "campaign_id": str(uuid4()),
                "source": "google_ads",
                "frequency": "weekly",
            },
        )
        assert resp.status_code in (404, 403)


# ------------------------------------------------------------------
# List schedules
# ------------------------------------------------------------------

class TestListSchedules:
    def test_list_scoped_to_org(self, client, mock_supabase):
        row = _schedule_row()
        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, schedule_data=[row],
        )

        resp = client.get("/api/v1/schedules", headers=_headers(USER_A_ID))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ------------------------------------------------------------------
# Delete schedule
# ------------------------------------------------------------------

class TestDeleteSchedule:
    @patch("app.services.scheduler_service.remove_job")
    def test_delete_own(self, mock_remove, client, mock_supabase):
        row = _schedule_row()
        mock_supabase.table.side_effect = _table_side_effect(
            ORG_A_ID, schedule_data=row,
        )

        resp = client.delete(
            f"/api/v1/schedules/{FAKE_SCHEDULE_ID}",
            headers=_headers(USER_A_ID),
        )
        assert resp.status_code == 204
        mock_remove.assert_called_once_with(FAKE_SCHEDULE_ID)
