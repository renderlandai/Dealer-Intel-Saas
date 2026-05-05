"""Phase 6.5.7 — POST /scans/{id}/cancel endpoint tests.

The cancel endpoint exists because the heartbeat-stale cleanup window
is 30 minutes (post-2026-05-05 fix), and even 30 minutes of an
operator staring at a stuck "RUNNING" badge is too long when they
*know* the worker is dead. Cancelling flips the row to `failed` with
a clear `error_message` so the existing scan-list UX (red banner +
Retry button) lights up immediately.

Contract pinned by these tests:

* `pending`, `running`, `analyzing` are cancellable → 200 + status
  flipped to `failed` + `error_message == SCAN_CANCEL_MESSAGE`.
* `completed` and `failed` are NOT cancellable → 400.
* Scan from a different organization → 404 (org-scoped lookup).
* The exact `SCAN_CANCEL_MESSAGE` constant is preserved in the
  response so the frontend can match against it without parsing
  free-form text.
"""
from __future__ import annotations

import time
from typing import Any, Dict
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import jwt
import pytest

from tests.conftest import USER_A_ID, ORG_A_ID, ORG_B_ID

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long"

SCAN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _token() -> str:
    return jwt.encode({
        "sub": str(USER_A_ID),
        "email": "a@test.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }, JWT_SECRET, algorithm="HS256")


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def _scan_row(status: str, scan_org_id=ORG_A_ID, scan_id: str = SCAN_ID) -> dict:
    """Shape that mirrors the actual scan_jobs row the endpoint reads.

    Includes every field the `ScanJob` Pydantic response model requires
    so the response serialization passes — historically several fields
    (campaign_id, total_items, processed_items, apify_run_id) were
    Optional but not Default-None in the model, so they need to appear
    explicitly in any test row.
    """
    return {
        "id": scan_id,
        "organization_id": str(scan_org_id),
        "campaign_id": None,
        "status": status,
        "source": "website",
        "started_at": "2026-05-05T17:22:00+00:00",
        "completed_at": None,
        "total_items": 0,
        "processed_items": 0,
        "matches_count": 0,
        "error_message": None,
        "apify_run_id": None,
        "pipeline_stats": None,
        "cost_usd": 0,
        "cost_breakdown": None,
        "created_at": "2026-05-05T17:22:00+00:00",
    }


def _wire_scan_lookup_and_update(
    mock_supabase,
    *,
    user_org_id=ORG_A_ID,
    scan_lookup_data,
    update_response_data=None,
):
    """Stub the supabase chain used by `cancel_scan_job`.

    The endpoint issues:
      1. user_profiles select → org for current user (auth).
      2. scan_jobs select(*).eq(id).eq(org).maybe_single() → the scan.
      3. scan_jobs update({...}).eq(id) → the cancel write.

    The caller can read recorded write payloads off the returned
    capture dict — `mock_supabase.table.side_effect` returns a fresh
    MagicMock per call so a global `.update.call_args_list` assertion
    is not reliable.
    """
    capture: Dict[str, Any] = {"updates": [], "scan_jobs_table": None}

    def table_side_effect(name):
        t = MagicMock()
        if name == "user_profiles":
            t.select.return_value.eq.return_value.single.return_value \
                .execute.return_value = MagicMock(
                data={"organization_id": str(user_org_id), "role": "owner"}
            )
        elif name == "scan_jobs":
            # Lookup chain: select("*").eq("id", X).eq("organization_id", Y).maybe_single().execute()
            lookup_result = MagicMock(data=scan_lookup_data)
            t.select.return_value.eq.return_value.eq.return_value \
                .maybe_single.return_value.execute.return_value = lookup_result
            # Update chain: update({...}).eq("id", X).execute() — capture
            # the payload via a side_effect so the test can inspect what
            # the endpoint wrote.
            update_result = MagicMock(
                data=update_response_data if update_response_data is not None else []
            )
            def _record_update(payload):
                capture["updates"].append(payload)
                inner = MagicMock()
                inner.eq.return_value.execute.return_value = update_result
                return inner
            t.update.side_effect = _record_update
            capture["scan_jobs_table"] = t
        return t

    mock_supabase.table.side_effect = table_side_effect
    return capture


# ---------------------------------------------------------------------------
# Happy path — cancellable statuses
# ---------------------------------------------------------------------------


class TestCancelActiveScan:
    @pytest.mark.parametrize("status", ["pending", "running", "analyzing"])
    def test_cancellable_status_returns_200_and_marks_failed(self, status, client, mock_supabase):
        from app.routers.scanning import SCAN_CANCEL_MESSAGE

        scan_before = _scan_row(status=status)
        scan_after = dict(scan_before)
        scan_after.update({
            "status": "failed",
            "error_message": SCAN_CANCEL_MESSAGE,
            "completed_at": "2026-05-05T18:55:00+00:00",
        })

        capture = _wire_scan_lookup_and_update(
            mock_supabase,
            scan_lookup_data=scan_before,
            update_response_data=[scan_after],
        )

        resp = client.post(f"/api/v1/scans/{SCAN_ID}/cancel", headers=_headers())
        assert resp.status_code == 200, resp.text

        body = resp.json()
        assert body["status"] == "failed"
        assert body["error_message"] == SCAN_CANCEL_MESSAGE

        # Verify the update payload matches the contract — status flip,
        # cancel message, and a completed_at stamp so the row carries
        # an end-time the same way a naturally-failed scan would.
        assert len(capture["updates"]) == 1
        write_payload = capture["updates"][0]
        assert write_payload["status"] == "failed"
        assert write_payload["error_message"] == SCAN_CANCEL_MESSAGE
        assert "completed_at" in write_payload

    def test_response_body_falls_back_when_update_returns_no_data(self, client, mock_supabase):
        """Defensive: some supabase-py versions don't echo the row on
        update. The endpoint must still return a sensible body so the
        React mutation can update its cache."""
        from app.routers.scanning import SCAN_CANCEL_MESSAGE

        scan_before = _scan_row(status="running")
        capture = _wire_scan_lookup_and_update(
            mock_supabase,
            scan_lookup_data=scan_before,
            update_response_data=[],
        )

        resp = client.post(f"/api/v1/scans/{SCAN_ID}/cancel", headers=_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error_message"] == SCAN_CANCEL_MESSAGE
        assert body["id"] == SCAN_ID


# ---------------------------------------------------------------------------
# Reject paths
# ---------------------------------------------------------------------------


class TestCancelTerminalScan:
    """Cancelling a completed or failed scan is a logical no-op and
    almost always indicates operator confusion. Returning 400 with a
    clear message tells them to use Delete instead."""

    @pytest.mark.parametrize("status", ["completed", "failed"])
    def test_terminal_status_returns_400(self, status, client, mock_supabase):
        scan_before = _scan_row(status=status)
        _wire_scan_lookup_and_update(
            mock_supabase,
            scan_lookup_data=scan_before,
        )

        resp = client.post(f"/api/v1/scans/{SCAN_ID}/cancel", headers=_headers())
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert status in detail.lower() or status in detail
        # The error mentions the alternative path (Delete) so the
        # operator knows what to do.
        assert "delete" in detail.lower()

    def test_terminal_status_does_not_issue_update(self, client, mock_supabase):
        """The 400 branch must short-circuit BEFORE writing — otherwise
        a completed scan could lose its `completed_at` timestamp."""
        scan_before = _scan_row(status="completed")
        capture = _wire_scan_lookup_and_update(
            mock_supabase,
            scan_lookup_data=scan_before,
        )

        resp = client.post(f"/api/v1/scans/{SCAN_ID}/cancel", headers=_headers())
        assert resp.status_code == 400

        # No update payload was captured — the 400 branch short-circuits
        # before the .update() call site, so a completed scan's
        # completed_at and final status survive intact.
        assert capture["updates"] == []


class TestCancelMissingScan:
    def test_unknown_scan_id_returns_404(self, client, mock_supabase):
        # Scan doesn't exist for this org → maybe_single returns None.
        _wire_scan_lookup_and_update(
            mock_supabase,
            scan_lookup_data=None,
        )

        resp = client.post(f"/api/v1/scans/{SCAN_ID}/cancel", headers=_headers())
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestCancelCrossOrg:
    """Cross-tenant access must look identical to "scan does not
    exist" — i.e. 404, not 403, so a leak-via-error doesn't reveal
    that the id belongs to another org."""

    def test_other_org_scan_returns_404(self, client, mock_supabase):
        # The user is in ORG_A; the scan id (if it existed at all)
        # belongs to ORG_B. Because the lookup chain filters by both
        # id AND org, the maybe_single returns None for our caller.
        _wire_scan_lookup_and_update(
            mock_supabase,
            user_org_id=ORG_A_ID,
            scan_lookup_data=None,  # no row matches (id, org_a)
        )

        resp = client.post(f"/api/v1/scans/{SCAN_ID}/cancel", headers=_headers())
        assert resp.status_code == 404


class TestCancelMessageConstant:
    """The frontend matches against `SCAN_CANCEL_MESSAGE` to skip the
    generic 'check your URLs' hint banner. Pinning the constant here
    prevents an accidental message change from breaking that match."""

    def test_constant_value_is_stable(self):
        from app.routers.scanning import SCAN_CANCEL_MESSAGE
        assert SCAN_CANCEL_MESSAGE == "Cancelled by operator"
