"""Regression tests for the worker dispatch grace re-check.

Covers the write-after-claim race fixed in ``app.worker._await_dispatch``:
a scan row is inserted with ``status='pending'`` (immediately claimable) a
beat BEFORE the API persists ``metadata.dispatch``. A fast worker could win
the claim in that window, see no dispatch, and hard-fail a perfectly good
scan. The grace re-read lets the slightly-late persist land.

Tests run the coroutines via ``asyncio.run`` so they don't depend on a
pytest-asyncio configuration, and stub the module-level ``supabase`` client
plus the grace sleep so they execute instantly.
"""
from __future__ import annotations

import asyncio

from app import worker


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Swallows the whole select/eq/single/update chain, returns a result.

    ``result`` may be a plain ``_Resp`` (returned every call) or a zero-arg
    callable (so tests can feed a sequence of differing reads).
    """

    def __init__(self, result):
        self._result = result

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def execute(self):
        return self._result() if callable(self._result) else self._result


class _FakeSupabase:
    def __init__(self, result):
        self._result = result

    def table(self, _name):
        return _FakeQuery(self._result)


def _valid_dispatch_row():
    return {
        "id": "jid",
        "source": "website",
        "metadata": {
            "dispatch": {
                "task_name": "run_website_scan_task",
                "args": [["https://example.com/"], "jid", {}, None],
            }
        },
    }


def test_await_dispatch_returns_when_payload_lands_late(monkeypatch):
    monkeypatch.setattr(worker, "_DISPATCH_GRACE_SLEEP_SECONDS", 0)
    # First re-read still has no dispatch; second read shows it landed.
    seq = iter([_Resp({"id": "jid", "metadata": {}}), _Resp(_valid_dispatch_row())])
    monkeypatch.setattr(worker, "supabase", _FakeSupabase(lambda: next(seq)))

    out = asyncio.run(worker._await_dispatch("jid"))

    assert out is not None
    assert out["task_name"] == "run_website_scan_task"
    assert isinstance(out["args"], list)


def test_await_dispatch_gives_up_when_never_persisted(monkeypatch):
    monkeypatch.setattr(worker, "_DISPATCH_GRACE_SLEEP_SECONDS", 0)
    monkeypatch.setattr(worker, "_DISPATCH_GRACE_ATTEMPTS", 3)
    monkeypatch.setattr(worker, "supabase", _FakeSupabase(_Resp({"id": "jid", "metadata": {}})))

    out = asyncio.run(worker._await_dispatch("jid"))

    assert out is None


def test_process_one_job_recovers_via_grace(monkeypatch):
    """A row claimed before its dispatch landed should still run, not fail."""
    monkeypatch.setattr(worker, "_DISPATCH_GRACE_SLEEP_SECONDS", 0)
    monkeypatch.setattr(worker, "supabase", _FakeSupabase(_Resp(_valid_dispatch_row())))

    called = {}

    async def _fake_exec(job_id, task_name, args):
        called["job_id"] = job_id
        called["task_name"] = task_name
        called["args"] = args

    monkeypatch.setattr(worker, "execute_persisted_task", _fake_exec)
    monkeypatch.setattr(
        worker, "_mark_failed",
        lambda *a, **k: called.__setitem__("failed", True),
    )

    # Claim-time row has NO dispatch yet (the race condition).
    job = {"id": "jid", "source": "website", "metadata": {}}
    asyncio.run(worker._process_one_job(job))

    assert called.get("task_name") == "run_website_scan_task"
    assert "failed" not in called


def test_process_one_job_hard_fails_after_grace(monkeypatch):
    """A row that never gets a dispatch is still hard-failed after the grace."""
    monkeypatch.setattr(worker, "_DISPATCH_GRACE_SLEEP_SECONDS", 0)
    monkeypatch.setattr(worker, "_DISPATCH_GRACE_ATTEMPTS", 2)
    monkeypatch.setattr(worker, "supabase", _FakeSupabase(_Resp({"id": "jid", "metadata": {}})))

    marks = {}
    monkeypatch.setattr(worker, "_mark_failed", lambda jid, msg: marks.update(id=jid, msg=msg))

    async def _fake_exec(*a, **k):
        raise AssertionError("execute_persisted_task must not run without a dispatch")

    monkeypatch.setattr(worker, "execute_persisted_task", _fake_exec)

    job = {"id": "jid", "source": "website", "metadata": {}}
    asyncio.run(worker._process_one_job(job))

    assert marks.get("id") == "jid"
    assert "no dispatch args" in marks.get("msg", "")
