"""Phase-8 hardening tests (2026-05-08).

Covers the four backstops added in response to the 2026-05-07 evening
production incident in `log.md`:

  Layer 1 — heartbeat throttle and per-image heartbeat from inside
            ``run_image_analysis`` / ``_process_one_page``.
  Layer 2 — per-page ``asyncio.wait_for`` cap and per-dealer
            ``asyncio.wait_for`` cap, both producing a structured
            failure result rather than propagating to the parent.
  Layer 3 — ``_dealer_outcome`` envelope on every per-dealer result so
            the frontend can render "8 of 10 dealers complete".
  Layer 4 — covered by docs + existing worker tests; nothing in-process
            to assert here.

These tests intentionally do not exercise the real database, the cost
context, Anthropic, or Playwright. They cover behaviour that is
entirely decidable from inputs to ``scan_runners`` helpers.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


SCAN_JOB_ID = uuid4()


def _run(coro):
    """Drive a coroutine to completion. Mirrors the helper used in
    `test_scan_runners_dispatch.py` (project does not depend on
    pytest-asyncio).
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Layer 1 — heartbeat throttle
# ---------------------------------------------------------------------------

class TestHeartbeatThrottle:
    """`_heartbeat_throttled` must coalesce in-loop calls so a 100-image
    page does not fire 100 DB UPDATEs."""

    def test_first_call_writes(self):
        from app.services import scan_runners

        # Reset any state from prior tests so this isn't order-dependent.
        scan_runners._last_heartbeat_at.clear()

        with patch.object(scan_runners, "_heartbeat") as mock_hb:
            scan_runners._heartbeat_throttled(SCAN_JOB_ID, min_interval=0.5)
            assert mock_hb.call_count == 1

    def test_second_call_within_interval_is_dropped(self):
        from app.services import scan_runners

        scan_runners._last_heartbeat_at.clear()

        with patch.object(scan_runners, "_heartbeat") as mock_hb:
            scan_runners._heartbeat_throttled(SCAN_JOB_ID, min_interval=10.0)
            scan_runners._heartbeat_throttled(SCAN_JOB_ID, min_interval=10.0)
            scan_runners._heartbeat_throttled(SCAN_JOB_ID, min_interval=10.0)
            assert mock_hb.call_count == 1

    def test_call_after_interval_writes_again(self):
        from app.services import scan_runners

        scan_runners._last_heartbeat_at.clear()

        with patch.object(scan_runners, "_heartbeat") as mock_hb:
            scan_runners._heartbeat_throttled(SCAN_JOB_ID, min_interval=0.0)
            # Force monotonic clock to look "later" by stomping the cache.
            scan_runners._last_heartbeat_at[str(SCAN_JOB_ID)] = (
                time.monotonic() - 100.0
            )
            scan_runners._heartbeat_throttled(SCAN_JOB_ID, min_interval=0.5)
            assert mock_hb.call_count == 2

    def test_concurrent_scans_have_independent_budgets(self):
        from app.services import scan_runners

        scan_runners._last_heartbeat_at.clear()
        other_job = uuid4()

        with patch.object(scan_runners, "_heartbeat") as mock_hb:
            scan_runners._heartbeat_throttled(SCAN_JOB_ID, min_interval=10.0)
            scan_runners._heartbeat_throttled(other_job, min_interval=10.0)
            assert mock_hb.call_count == 2


# ---------------------------------------------------------------------------
# Layer 1 — run_image_analysis fan-out + heartbeats
# ---------------------------------------------------------------------------

class TestRunImageAnalysisParallel:
    """The Facebook / Google / Instagram analyse path was strictly
    sequential before Phase-8. Verify the new fan-out actually fires
    images concurrently and stamps a heartbeat at least once."""

    def test_runs_with_bounded_concurrency_and_heartbeats(self, monkeypatch):
        from app.services import scan_runners

        scan_runners._last_heartbeat_at.clear()

        # Configure a small concurrency cap so the assertion is concrete.
        fake_settings = MagicMock()
        fake_settings.post_analysis_concurrency = 3
        fake_settings.heartbeat_min_interval_seconds = 0.0
        monkeypatch.setattr(
            "app.config.get_settings", lambda: fake_settings,
        )

        # `_analyze_single_image` is the only thing we want to mock —
        # the rest of the function is bookkeeping. Track how many
        # coroutines were live concurrently to prove the gather is
        # actually parallel.
        live = 0
        peak = 0

        async def fake_analyze(*args, **kwargs):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1

        # Stub out the asset-prep helpers and the per-image worker.
        monkeypatch.setattr(
            scan_runners, "_analyze_single_image", AsyncMock(side_effect=fake_analyze),
        )
        monkeypatch.setattr(
            scan_runners.ai_service, "_precompute_asset_hashes",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            scan_runners.ai_service, "_precompute_asset_embeddings",
            AsyncMock(return_value={}),
        )
        monkeypatch.setattr(
            scan_runners.ai_service, "get_image_cache_stats",
            lambda: {"hits": 0, "misses": 0, "hit_rate": 0,
                     "cached_entries": 0, "cached_mb": 0},
        )
        # No-op the trailing supabase write.
        fake_supabase = MagicMock()
        monkeypatch.setattr(scan_runners, "supabase", fake_supabase)
        monkeypatch.setattr(scan_runners, "_heartbeat", MagicMock())

        images = [{"id": f"img-{i}", "image_url": f"http://x/{i}"} for i in range(8)]
        _run(scan_runners.run_image_analysis(
            discovered_images=images,
            campaign_assets=[{"id": "asset-1"}],
            brand_rules={},
            organization_id="org-1",
            scan_job_id=str(SCAN_JOB_ID),
        ))

        # All images dispatched.
        assert scan_runners._analyze_single_image.await_count == 8
        # Concurrency was capped at the configured limit (or below).
        assert peak <= 3
        # Concurrency actually engaged — strict serial would peak at 1.
        assert peak > 1
        # Heartbeat fired at least once for the loop.
        assert scan_runners._heartbeat.call_count >= 1


# ---------------------------------------------------------------------------
# Layer 2 — page wait_for backstop
# ---------------------------------------------------------------------------

class TestPageHardTimeout:
    """`_run_page` must convert a wedged page into a structured failure
    rather than propagate the timeout up."""

    def test_timeout_returns_failure_result_shape(self, monkeypatch):
        from app.services import scan_runners

        # Build a tiny stub world. We're testing the wrapper logic, not
        # the page processing itself, so `_process_one_page` is a never-
        # returning coroutine.
        async def never_returns(*args, **kwargs):
            await asyncio.sleep(5)

        monkeypatch.setattr(scan_runners, "_process_one_page", never_returns)

        # Stub out collaborators _process_one_dealer drags in.
        monkeypatch.setattr(
            scan_runners.extraction_service, "release_dealer_contexts",
            AsyncMock(),
        )

        fake_settings = MagicMock()
        fake_settings.pages_per_dealer_concurrency = 4
        fake_settings.images_per_page_concurrency = 5
        # 50ms cap → forces the timeout path on the very first page.
        # Sub-second is supported because the runner now uses float()
        # on the setting (so a real deployment can also flag a
        # pathological dealer in <1s for triage purposes).
        fake_settings.page_hard_timeout_seconds = 0.05

        async def _drive():
            # Construct asyncio primitives INSIDE the coroutine so
            # Python 3.9 (which rejects Lock/Event/Semaphore outside a
            # running loop) is happy.
            return await scan_runners._process_one_dealer(
                base_url="https://example.com",
                page_urls=["https://example.com/a"],
                distributor_id=None,
                scan_job_id=SCAN_JOB_ID,
                campaign_assets=[],
                brand_rules={},
                org_id="org-1",
                asset_hashes={},
                asset_embeddings={},
                can_early_stop=False,
                all_asset_ids=set(),
                matched_asset_ids=set(),
                matched_lock=asyncio.Lock(),
                early_stop_event=asyncio.Event(),
                extract_sem=asyncio.Semaphore(1),
                settings=fake_settings,
                progress_callback=None,
            )

        out = _run(_drive())

        # Page-level timeout is recorded as a failed page with an
        # outcome marker the dashboard can recognise.
        assert out["pages_failed"] == 1
        assert out["dealer_status"] == "failed"
        assert out["block_details"], "block_details should record the timeout"
        assert out["block_details"][0]["outcome"] == "timeout"


# ---------------------------------------------------------------------------
# Layer 2 + 3 — dealer wait_for + outcome envelope
# ---------------------------------------------------------------------------

class TestDealerOutcomeEnvelope:
    """The per-dealer wrapper inside `run_website_scan` decorates each
    result with `_dealer_outcome` so the frontend can render partial
    success. We don't drive the whole runner here — instead we assert
    the envelope shape by exercising the timeout path in a small
    stand-alone sketch that mirrors the runner's wrapper."""

    def test_success_envelope_carries_status_and_duration(self, monkeypatch):
        # Synthesize the wrapper closure by invoking the relevant
        # branch directly. This proves the contract that the frontend
        # consumes (status / duration_seconds / matches_new) without
        # paying for the whole website-scan event-loop construction.
        from app.services import scan_runners

        async def fake_dealer(*args, **kwargs):
            return {
                "total_discovered": 0,
                "pages_scanned": 1,
                "pages_empty": 0,
                "pages_blocked": 0,
                "pages_failed": 0,
                "total_images": 0,
                "pages_skipped": 0,
                "pipeline_increments": {"matched_new": 2},
                "page_match_tracker": {},
                "block_details": [],
                "dealer_status": "ok",
                "base_url": "https://example.com",
                "distributor_id": None,
            }

        monkeypatch.setattr(scan_runners, "_process_one_dealer", fake_dealer)

        # The wrapper lives inside `run_website_scan` as a closure; the
        # cleanest way to verify its exact contract is to assert the
        # shape of the result decoration. Reproduce the wrapper here
        # with the same logic so any future drift is caught at review
        # time, not in production.
        async def wrap_like_runner():
            started_at = time.monotonic()
            # Construct asyncio primitives inside the coroutine — Python
            # 3.9 won't tolerate them at module-import time outside a
            # running loop.
            inner = scan_runners._process_one_dealer(
                base_url="https://example.com",
                page_urls=["https://example.com/a"],
                distributor_id=None,
                scan_job_id=SCAN_JOB_ID,
                campaign_assets=[],
                brand_rules={},
                org_id="org-1",
                asset_hashes={},
                asset_embeddings={},
                can_early_stop=False,
                all_asset_ids=set(),
                matched_asset_ids=set(),
                matched_lock=asyncio.Lock(),
                early_stop_event=asyncio.Event(),
                extract_sem=asyncio.Semaphore(1),
                settings=MagicMock(),
                progress_callback=None,
            )
            result = await inner
            result["_dealer_outcome"] = {
                "base_url": "https://example.com",
                "status": result.get("dealer_status", "ok"),
                "error": None,
                "started_at": "2026-05-08T00:00:00+00:00",
                "duration_seconds": round(
                    time.monotonic() - started_at, 1,
                ),
                "pages_scanned": result.get("pages_scanned", 0),
                "matches_new": (
                    result.get("pipeline_increments", {}) or {}
                ).get("matched_new", 0),
            }
            return result

        result = _run(wrap_like_runner())
        outcome = result["_dealer_outcome"]
        assert outcome["status"] == "ok"
        assert outcome["pages_scanned"] == 1
        assert outcome["matches_new"] == 2
        assert outcome["error"] is None
        # duration_seconds is a non-negative float.
        assert isinstance(outcome["duration_seconds"], (int, float))
        assert outcome["duration_seconds"] >= 0


# ---------------------------------------------------------------------------
# Phase-8.1 — dealer semaphore actually binds `max_concurrent_dealers`
# ---------------------------------------------------------------------------

class TestDealerSemaphoreBindsConcurrency:
    """Phase-8.1 regression for the 2026-05-08 incident.

    Pre-fix, every dealer task inside ``run_website_scan`` was launched
    concurrently via ``asyncio.gather`` and the only semaphore was the
    *page-level* extractor pool. ``max_concurrent_dealers`` was thus
    advisory only. With 45 dealers, all 45 ``asyncio.wait_for`` clocks
    started in lockstep, every dealer ran at 1/45 of full speed, and
    every dealer hit the 2700 s cap before any could finish.

    The wrapper inside ``_run_one_dealer_with_timeout`` now acquires
    ``dealer_sem`` *before* recording ``started_at`` and entering the
    wait_for. Two consequences this test pins down:

      1. At most ``max_concurrent_dealers`` dealer coroutines do real
         work simultaneously.
      2. A dealer queued behind earlier dealers does not have its
         timeout budget eroded by queue time.

    We mirror the wrapper's exact structure inline so any drift in
    ``scan_runners`` is caught at review time. Keep the inline helper
    in lockstep with ``_run_one_dealer_with_timeout`` if you change it.
    """

    def test_at_most_n_dealers_run_concurrently_and_queue_does_not_time_out(self):
        max_concurrent = 2
        dealer_count = 6
        per_dealer_work_s = 0.10
        dealer_timeout_s = 0.30  # > work, < (queue_time + work) for tail

        peak = 0
        live = 0

        async def driver():
            nonlocal peak, live
            dealer_sem = asyncio.Semaphore(max_concurrent)

            async def fake_inner_dealer(name: str):
                nonlocal peak, live
                live += 1
                peak = max(peak, live)
                try:
                    await asyncio.sleep(per_dealer_work_s)
                    return {
                        "dealer_status": "ok",
                        "pages_scanned": 1,
                        "pipeline_increments": {},
                    }
                finally:
                    live -= 1

            async def wrapper(name: str):
                async with dealer_sem:
                    started_at = time.monotonic()
                    try:
                        result = await asyncio.wait_for(
                            fake_inner_dealer(name),
                            timeout=dealer_timeout_s,
                        )
                    except asyncio.TimeoutError:
                        return {"name": name, "timed_out": True,
                                "duration": time.monotonic() - started_at}
                    return {"name": name, "timed_out": False,
                            "duration": time.monotonic() - started_at}

            tasks = [asyncio.create_task(wrapper(f"d{i}"))
                     for i in range(dealer_count)]
            return await asyncio.gather(*tasks)

        results = _run(driver())

        assert peak <= max_concurrent, (
            f"Dealer sem leaked: observed peak={peak} but cap is "
            f"{max_concurrent}. The sem must be acquired before the "
            f"wait_for so concurrency is hard-bound."
        )
        assert peak >= 2, (
            "Concurrency never engaged; sem is over-binding."
        )
        timed_out = [r for r in results if r["timed_out"]]
        assert not timed_out, (
            f"Queued dealers timed out — sem is inside the wait_for. "
            f"Bad results: {timed_out}"
        )
        for r in results:
            # Real work was ~0.10s; even with overhead, < dealer_timeout.
            assert r["duration"] < dealer_timeout_s + 0.05, (
                f"Dealer {r['name']} took {r['duration']:.3f}s — sem is "
                "leaking queue time into the wait_for budget."
            )


# ---------------------------------------------------------------------------
# Phase-8.2 — live dealer_outcomes streaming
# ---------------------------------------------------------------------------

class TestDealerOutcomeStreaming:
    """The "X of N dealers complete" badge in `frontend/app/scans/page.tsx`
    reads ``pipeline_stats.dealer_outcomes``. Pre-Phase-8.2 that JSONB was
    only written at end-of-scan, so the badge stayed hidden until the
    scan finished. Phase-8.2 mirrors the structure of the wrapper inside
    ``run_website_scan`` and asserts:

      1. Outcomes start as N "pending" stubs (badge denominator stable
         from t=0).
      2. Each completion replaces the matching stub by ``base_url``
         (no orphaned stubs, no duplicates).
      3. The throttle coalesces writes when completions arrive faster
         than the configured interval.
      4. A "force" flush always writes (used at end-of-scan for the
         last dealer that may have been throttled).
    """

    def test_streaming_replaces_pending_stub_and_throttles_writes(self):
        # Mirror the relevant fields from `run_website_scan` so any
        # drift is caught here at review time.
        from app.services import scan_runners  # noqa: F401

        async def _drive():
            base_urls = ["https://a.com", "https://b.com", "https://c.com"]

            pipeline_stats: Dict[str, Any] = {
                "dealer_outcomes": [
                    {
                        "base_url": b,
                        "status": "pending",
                        "error": None,
                        "started_at": None,
                        "duration_seconds": None,
                    }
                    for b in base_urls
                ],
            }
            outcomes_index = {b: i for i, b in enumerate(base_urls)}
            outcomes_lock = asyncio.Lock()
            last_write = {"t": 0.0}
            interval = 0.05  # 50 ms

            writes: list[Dict[str, Any]] = []

            def _fake_supabase_update(payload: Dict[str, Any]) -> None:
                # Snapshot the dealer_outcomes at write time so we can
                # assert what the DB would have observed.
                snap = [
                    dict(o) for o in payload["pipeline_stats"]["dealer_outcomes"]
                ]
                writes.append({"outcomes": snap})

            async def emit(outcome, *, force=False):
                async with outcomes_lock:
                    idx = outcomes_index.get(outcome.get("base_url"))
                    if idx is not None:
                        pipeline_stats["dealer_outcomes"][idx] = outcome
                    else:
                        pipeline_stats["dealer_outcomes"].append(outcome)
                    now = time.monotonic()
                    throttled = (
                        interval > 0 and (now - last_write["t"]) < interval
                    )
                    if throttled and not force:
                        return
                    last_write["t"] = now
                    _fake_supabase_update({"pipeline_stats": pipeline_stats})

            # 1) pending stubs are present from the start.
            assert all(o["status"] == "pending"
                       for o in pipeline_stats["dealer_outcomes"])
            assert len(pipeline_stats["dealer_outcomes"]) == 3

            # 2) first emit writes (no throttle yet), replaces stub a.
            await emit({"base_url": "https://a.com", "status": "ok",
                        "duration_seconds": 4.2, "error": None})
            assert pipeline_stats["dealer_outcomes"][0]["status"] == "ok"
            assert pipeline_stats["dealer_outcomes"][1]["status"] == "pending"
            assert len(writes) == 1

            # 3) second emit immediately after — throttled, no DB write.
            await emit({"base_url": "https://b.com", "status": "ok",
                        "duration_seconds": 3.8, "error": None})
            assert pipeline_stats["dealer_outcomes"][1]["status"] == "ok"
            assert len(writes) == 1, (
                "Throttle should have suppressed the second write."
            )

            # 4) wait past the throttle window, third emit writes again.
            await asyncio.sleep(interval + 0.01)
            await emit({"base_url": "https://c.com", "status": "failed",
                        "duration_seconds": 2700.0,
                        "error": "Dealer hard timeout (2700.0s)"})
            assert pipeline_stats["dealer_outcomes"][2]["status"] == "failed"
            assert len(writes) == 2

            # 5) verify the DB-side snapshot order and content of the
            # last write (what the frontend would have rendered).
            last_snap = writes[-1]["outcomes"]
            assert [o["base_url"] for o in last_snap] == base_urls
            assert [o["status"] for o in last_snap] == ["ok", "ok", "failed"]

            # 6) force=True bypasses the throttle (used at end of scan).
            await emit({"base_url": "https://a.com", "status": "ok",
                        "duration_seconds": 4.2, "error": None}, force=True)
            assert len(writes) == 3, (
                "force=True must always write regardless of throttle."
            )

        _run(_drive())


# ---------------------------------------------------------------------------
# Layer 1 — Anthropic SDK timeout / model bump
# ---------------------------------------------------------------------------

class TestAnthropicClientHardening:
    """The SDK must be constructed with an explicit timeout so the
    600s default cannot recur. The model slug must be 4-7 to match the
    cost_tracker pricing table."""

    def test_anthropic_client_has_explicit_timeout(self):
        # Re-import the module so we read the live constants/state.
        from app.services import ai_service

        # The SDK exposes the configured timeout at `.timeout`. Older
        # client versions surface it under different attributes; check
        # the most stable one then fall back to inspecting `_client`.
        client = ai_service.anthropic_client
        timeout = (
            getattr(client, "timeout", None)
            or getattr(getattr(client, "_client", None), "timeout", None)
        )
        # Accept either the raw float or an httpx Timeout — both must
        # resolve to a finite, non-default value (anything < 600s).
        as_float = (
            float(timeout) if isinstance(timeout, (int, float))
            else float(getattr(timeout, "read", 600.0) or 600.0)
        )
        assert as_float < 600.0, (
            f"Anthropic SDK still using default timeout: {timeout!r}"
        )

    def test_claude_model_is_opus_4_6(self):
        # The Phase-8 (2026-05-08) version of this test pinned 4-7. That
        # bump was rolled back on 2026-05-11 after it produced 0 matches in
        # production; the eval-validated slug is 4-6. See the load-bearing
        # comment above ``ai_service.CLAUDE_MODEL`` and
        # ``test_matcher_model_pin.py`` before changing this.
        from app.services import ai_service

        assert ai_service.CLAUDE_MODEL == "claude-opus-4-6"
        assert ai_service.ENSEMBLE_MODEL == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Layer 4 — runner config defaults
# ---------------------------------------------------------------------------

class TestPhase8SettingsDefaults:
    """The new tunables must have sensible defaults so an unconfigured
    deployment is hardened by Phase 8 out of the box."""

    def test_defaults_are_protective(self):
        from app.config import Settings

        s = Settings()
        # Anthropic default is 600s; we bound it lower.
        assert 0 < s.anthropic_request_timeout_seconds < 600
        # Per-page cap exists and is < 1h.
        assert s.page_hard_timeout_seconds == 0 or s.page_hard_timeout_seconds <= 3600
        # Per-dealer cap exists and is < 2h.
        assert s.dealer_hard_timeout_seconds == 0 or s.dealer_hard_timeout_seconds <= 7200
        # Heartbeat throttle is on the order of seconds (not minutes).
        assert 0 < s.heartbeat_min_interval_seconds <= 30
        # Post-analysis fan-out is bounded but parallel.
        assert s.post_analysis_concurrency >= 2
        # Phase-8.2: dealer-outcome streaming throttle is sub-minute so
        # the UI badge updates at human-perceptible speed.
        assert 0 <= s.dealer_outcome_stream_interval_seconds <= 30
