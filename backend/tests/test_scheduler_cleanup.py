"""Phase 6.5.7 — _cleanup_stale_scans unit tests.

Pre-2026-05-05, the heartbeat-stale window was 4 hours. That meant a
worker that OOM-died mid-scan left the row showing as RUNNING in the
operator dashboard for up to 4 hours before the cleanup job swept it.
The 2026-05-05 incident (worker died at 18:30:48 UTC during the
page-9 screenshot upload on a Website scan) was exactly that pattern —
operator stared at a "RUNNING" badge for over an hour before
realising the worker was gone, with another ~2.5 hours to wait for
the cleanup cron at the time.

The fix tightens the heartbeat-stale window to 30 minutes (the
runner heartbeats every page AND every `_HEARTBEAT_EVERY_N` images,
so a healthy scan never has a 30-min gap) while leaving the
no-heartbeat fallback at 4 hours so runners that crashed during prep
before any heartbeat could be stamped don't get killed prematurely.

These tests pin the new behaviour:

* The heartbeat-based bucket uses the 30-min cutoff.
* The no-heartbeat bucket still uses the 4-hour cutoff.
* The pending bucket still uses the 15-min cutoff.
* Each bucket writes a distinct, operator-readable error_message.
* A row that appears in multiple buckets is updated exactly once.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal fake of the supabase-py builder chain used by _cleanup_stale_scans.
#
# The cleanup job builds three reads:
#
#   1. select("id").eq("status","pending").lt("created_at", X).execute()
#   2. select("id").in_("status",[...]).not_.is_(col,"null").lt(col,X).execute()
#   3. select("id").in_("status",[...]).is_(col,"null").lt("created_at",X).execute()
#
# …then issues one update per matched row:
#
#   4. table("scan_jobs").update({...}).eq("id", X).execute()
#
# We capture the build chain on each call and return a stubbed `data`
# response keyed by which "shape" the test wants to populate. The fake
# is deliberately simple: it doesn't try to actually filter, the test
# decides what each select returns.
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(
        self,
        select_responses: Dict[str, List[Dict[str, Any]]],
        recorder: List[Dict[str, Any]],
    ):
        self._select_responses = select_responses
        self._recorder = recorder
        self._op: Optional[str] = None
        self._payload: Optional[Dict[str, Any]] = None
        self._eq: Dict[str, Any] = {}
        self._in: Dict[str, Any] = {}
        self._lt: Dict[str, Any] = {}
        self._is: Dict[str, Any] = {}
        self._is_null = False
        self._has_not_null = False

    # -- builders ----------------------------------------------------
    def select(self, *_a, **_kw):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, k, v):
        self._eq[k] = v
        return self

    def in_(self, k, v):
        self._in[k] = list(v)
        return self

    def lt(self, k, v):
        self._lt[k] = v
        return self

    def is_(self, k, v):
        self._is[k] = v
        if v == "null":
            self._is_null = True
        return self

    @property
    def not_(self):
        # supabase-py exposes `.not_` as a passthrough that flips the
        # next is_() into IS NOT NULL. We mirror that minimally.
        self._has_not_null = True
        outer = self

        class _Not:
            def is_(self_inner, k, v):
                outer._is[k] = v
                return outer
        return _Not()

    # -- terminal -----------------------------------------------------
    def execute(self):
        # Classify the read so the test can stub a response for each
        # bucket. The classification mirrors what _cleanup_stale_scans
        # actually builds:
        kind: str
        if self._op == "update":
            kind = f"update:{self._eq.get('id', '?')}"
            self._recorder.append({
                "kind": "update",
                "id": self._eq.get("id"),
                "payload": self._payload,
            })
            return MagicMock(data=[{"id": self._eq.get("id")}])

        if self._eq.get("status") == "pending":
            kind = "pending"
        elif self._has_not_null and "last_heartbeat_at" in self._is:
            kind = "stale_heartbeat"
        elif self._is_null and "last_heartbeat_at" in self._is:
            kind = "no_heartbeat"
        else:
            kind = "unknown"

        self._recorder.append({
            "kind": "select",
            "bucket": kind,
            "eq": dict(self._eq),
            "in": dict(self._in),
            "lt": dict(self._lt),
            "is": dict(self._is),
        })
        return MagicMock(data=list(self._select_responses.get(kind, [])))


class _FakeTable:
    def __init__(self, responses, recorder):
        self._responses = responses
        self._recorder = recorder

    def select(self, *a, **kw):
        return _FakeQuery(self._responses, self._recorder).select(*a, **kw)

    def update(self, payload):
        return _FakeQuery(self._responses, self._recorder).update(payload)


class _FakeSupabase:
    def __init__(self, responses=None):
        self._responses = responses or {}
        self.calls: List[Dict[str, Any]] = []

    def table(self, name):
        assert name == "scan_jobs", f"unexpected table {name!r}"
        return _FakeTable(self._responses, self.calls)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _now_iso(offset: timedelta = timedelta(0)) -> str:
    return (datetime.now(timezone.utc) + offset).isoformat()


class TestCleanupStaleScansCutoffs:
    """The three cutoffs are independent — each must use its own
    timedelta and resolve to a distinct error_message."""

    def test_heartbeat_stale_uses_30_minute_cutoff(self):
        from app.services import scheduler_service

        # Scan that was bumped 35 minutes ago — the new 30-min cutoff
        # should sweep it. The pre-fix 4-hour cutoff would have left it.
        fake = _FakeSupabase(responses={
            "stale_heartbeat": [{"id": "scan-stuck-after-30min"}],
        })

        with patch.object(scheduler_service, "supabase", fake):
            asyncio.run(scheduler_service._cleanup_stale_scans())

        # Verify the heartbeat select used a cutoff approximately 30 min
        # in the past — within a generous 60s wall-clock buffer for test
        # execution latency.
        select_calls = [c for c in fake.calls if c["kind"] == "select"]
        heartbeat_call = next(c for c in select_calls if c["bucket"] == "stale_heartbeat")
        cutoff_iso = heartbeat_call["lt"]["last_heartbeat_at"]
        cutoff_dt = datetime.fromisoformat(cutoff_iso)
        expected = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert abs((cutoff_dt - expected).total_seconds()) < 60, \
            f"heartbeat cutoff was {cutoff_dt} (expected ~{expected})"

        # And the row got marked failed with the right operator-readable
        # message — distinct from the pending and no-heartbeat messages
        # so the dashboard can tell at a glance which path fired.
        update_calls = [c for c in fake.calls if c["kind"] == "update"]
        assert len(update_calls) == 1
        assert update_calls[0]["id"] == "scan-stuck-after-30min"
        msg = update_calls[0]["payload"]["error_message"]
        assert "heartbeat" in msg.lower()
        assert "30 min" in msg.lower()
        assert update_calls[0]["payload"]["status"] == "failed"

    def test_pending_stale_uses_15_minute_cutoff(self):
        from app.services import scheduler_service

        fake = _FakeSupabase(responses={
            "pending": [{"id": "scan-never-claimed"}],
        })
        with patch.object(scheduler_service, "supabase", fake):
            asyncio.run(scheduler_service._cleanup_stale_scans())

        pending_call = next(
            c for c in fake.calls
            if c["kind"] == "select" and c["bucket"] == "pending"
        )
        cutoff_dt = datetime.fromisoformat(pending_call["lt"]["created_at"])
        expected = datetime.now(timezone.utc) - timedelta(minutes=15)
        assert abs((cutoff_dt - expected).total_seconds()) < 60

        update_calls = [c for c in fake.calls if c["kind"] == "update"]
        assert len(update_calls) == 1
        assert update_calls[0]["id"] == "scan-never-claimed"
        msg = update_calls[0]["payload"]["error_message"]
        assert "pending" in msg.lower()
        assert "15 minutes" in msg.lower()

    def test_no_heartbeat_fallback_keeps_4_hour_cutoff(self):
        """The no-heartbeat fallback is for runners that crashed during
        prep before any heartbeat write. 4 hours stays here because the
        runner-heartbeat tightening in scan_runners.py only helps once
        the runner is actually heartbeating — pre-heartbeat death needs
        a generous fallback."""
        from app.services import scheduler_service

        fake = _FakeSupabase(responses={
            "no_heartbeat": [{"id": "scan-died-during-prep"}],
        })
        with patch.object(scheduler_service, "supabase", fake):
            asyncio.run(scheduler_service._cleanup_stale_scans())

        no_hb_call = next(
            c for c in fake.calls
            if c["kind"] == "select" and c["bucket"] == "no_heartbeat"
        )
        cutoff_dt = datetime.fromisoformat(no_hb_call["lt"]["created_at"])
        expected = datetime.now(timezone.utc) - timedelta(hours=4)
        assert abs((cutoff_dt - expected).total_seconds()) < 60

        update_calls = [c for c in fake.calls if c["kind"] == "update"]
        assert len(update_calls) == 1
        msg = update_calls[0]["payload"]["error_message"]
        assert "never wrote a heartbeat" in msg.lower()


class TestCleanupStaleScansDeduplication:
    """A single row can plausibly match multiple buckets if its
    timestamps happen to land in two windows simultaneously. The
    cleanup must update each row at most once — historically a
    duplicate update was harmless but the operator-facing log line
    would fire twice and inflate the cleanup counter."""

    def test_row_in_multiple_buckets_updated_once(self):
        from app.services import scheduler_service

        # Same id reported by both heartbeat-stale AND no-heartbeat
        # buckets (theoretically impossible because the two predicates
        # are mutually exclusive at the SQL level via IS / IS NOT NULL,
        # but defensive: PostgREST occasionally returns duplicates on
        # races with concurrent writers).
        fake = _FakeSupabase(responses={
            "stale_heartbeat": [{"id": "duplicate-row"}],
            "no_heartbeat": [{"id": "duplicate-row"}],
        })
        with patch.object(scheduler_service, "supabase", fake):
            asyncio.run(scheduler_service._cleanup_stale_scans())

        update_calls = [c for c in fake.calls if c["kind"] == "update"]
        assert len(update_calls) == 1, \
            f"row should be updated once, got {len(update_calls)}: {update_calls}"
        assert update_calls[0]["id"] == "duplicate-row"
        # First-seen-wins: the heartbeat-stale message (which fires
        # first in the bucket iteration order) is what we keep.
        msg = update_calls[0]["payload"]["error_message"]
        assert "heartbeat" in msg.lower()


class TestCleanupStaleScansEmptyState:
    """When nothing is stale, no updates are issued and the function
    returns silently. The previous bug (Phase 6.5.5) where
    `.maybe_single()` raised on empty was unrelated to scan_jobs but
    it's worth pinning the empty-state contract for cleanup too."""

    def test_no_stale_rows_emits_no_updates(self):
        from app.services import scheduler_service

        fake = _FakeSupabase(responses={})
        with patch.object(scheduler_service, "supabase", fake):
            asyncio.run(scheduler_service._cleanup_stale_scans())

        update_calls = [c for c in fake.calls if c["kind"] == "update"]
        assert update_calls == []

        # All three select buckets must still have been queried — we
        # don't want a future refactor to silently drop a bucket.
        select_buckets = sorted({
            c["bucket"] for c in fake.calls if c["kind"] == "select"
        })
        assert select_buckets == ["no_heartbeat", "pending", "stale_heartbeat"]


class TestCleanupStaleScansResilience:
    """Cleanup is best-effort — a Supabase blip during the cleanup
    cycle must not kill the scheduler. The function logs and returns
    without raising. APScheduler would otherwise mark the job
    permanently broken."""

    def test_supabase_exception_swallowed(self):
        from app.services import scheduler_service

        boom = MagicMock()
        boom.table.side_effect = RuntimeError("supabase down")
        with patch.object(scheduler_service, "supabase", boom):
            # Must not raise.
            asyncio.run(scheduler_service._cleanup_stale_scans())
