"""Phase 4.8 — verify the per-source runner wrappers correctly delegate
to the shared `_run_source_scan` driver.

These tests intentionally do NOT exercise the real database, the cost
context, or `_send_scan_notifications`. They cover only the *dispatch*
contract:

1. Each wrapper calls `_run_source_scan` with the right `source` label
   and passes through `scan_job_id` / `campaign_id`.
2. The `discover` callable each wrapper supplies, when invoked, calls
   the correct underlying service (SerpApi vs Playwright, Apify vs
   Playwright, Apify Instagram) based on settings.

A separate small block also exercises `_run_source_scan` itself to
prove the success / failure / no-campaign branches behave the way the
old per-source runners did before Phase 4.8.

Async coroutines are driven via plain `asyncio.run(...)` because the
project does not depend on `pytest-asyncio`.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


SCAN_JOB_ID = uuid4()
CAMPAIGN_ID = uuid4()
DISTRIBUTOR_MAPPING = {"example.com": uuid4()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _captured_run_source_scan():
    """Return an AsyncMock that records (source, scan_job_id, campaign_id, discover)."""
    captured = {}

    async def fake(*, source, scan_job_id, campaign_id, discover):
        captured["source"] = source
        captured["scan_job_id"] = scan_job_id
        captured["campaign_id"] = campaign_id
        captured["discover"] = discover

    mock = AsyncMock(side_effect=fake)
    return mock, captured


def _run(coro):
    """Drive a coroutine to completion. Replaces pytest-asyncio."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Wrapper dispatch contract (each runner -> _run_source_scan)
# ---------------------------------------------------------------------------

class TestGoogleAdsWrapperDispatch:
    def test_passes_google_ads_source_label(self):
        from app.services import scan_runners

        fake, captured = _captured_run_source_scan()
        with patch.object(scan_runners, "_run_source_scan", new=fake):
            _run(scan_runners.run_google_ads_scan(
                ["acme"], SCAN_JOB_ID, DISTRIBUTOR_MAPPING, campaign_id=CAMPAIGN_ID,
            ))

        assert captured["source"] == "google_ads"
        assert captured["scan_job_id"] == SCAN_JOB_ID
        assert captured["campaign_id"] == CAMPAIGN_ID
        assert callable(captured["discover"])

    def test_discover_uses_serpapi_when_key_present(self):
        from app.services import scan_runners

        fake, captured = _captured_run_source_scan()
        fake_serpapi = AsyncMock(return_value=42)
        fake_extraction = AsyncMock(return_value=99)

        with patch.object(scan_runners, "_run_source_scan", new=fake), \
             patch.object(scan_runners.serpapi_service, "scan_google_ads", new=fake_serpapi), \
             patch.object(scan_runners.extraction_service, "scan_google_ads", new=fake_extraction), \
             patch("app.config.get_settings",
                   return_value=SimpleNamespace(serpapi_api_key="set", apify_api_key=None)):
            _run(scan_runners.run_google_ads_scan(
                ["acme"], SCAN_JOB_ID, DISTRIBUTOR_MAPPING, campaign_id=CAMPAIGN_ID,
            ))
            count = _run(captured["discover"]([{"id": "asset-1"}]))

        assert count == 42
        fake_serpapi.assert_awaited_once()
        fake_extraction.assert_not_called()

    def test_discover_falls_back_to_playwright_without_serpapi_key(self):
        from app.services import scan_runners

        fake, captured = _captured_run_source_scan()
        fake_serpapi = AsyncMock(return_value=42)
        fake_extraction = AsyncMock(return_value=7)

        with patch.object(scan_runners, "_run_source_scan", new=fake), \
             patch.object(scan_runners.serpapi_service, "scan_google_ads", new=fake_serpapi), \
             patch.object(scan_runners.extraction_service, "scan_google_ads", new=fake_extraction), \
             patch("app.config.get_settings",
                   return_value=SimpleNamespace(serpapi_api_key=None, apify_api_key=None)):
            _run(scan_runners.run_google_ads_scan(
                ["acme"], SCAN_JOB_ID, DISTRIBUTOR_MAPPING, campaign_id=CAMPAIGN_ID,
            ))
            count = _run(captured["discover"]([{"id": "asset-1"}]))

        assert count == 7
        fake_serpapi.assert_not_called()
        fake_extraction.assert_awaited_once()


class TestFacebookWrapperDispatch:
    def test_passes_facebook_source_label(self):
        from app.services import scan_runners

        fake, captured = _captured_run_source_scan()
        with patch.object(scan_runners, "_run_source_scan", new=fake):
            _run(scan_runners.run_facebook_scan(
                ["fb.com/acme"], SCAN_JOB_ID, DISTRIBUTOR_MAPPING,
                campaign_id=CAMPAIGN_ID,
            ))

        # Source label is always "facebook" even when channel differs —
        # `_send_scan_notifications` keys off `scan_source`.
        assert captured["source"] == "facebook"

    def test_discover_uses_apify_when_key_present_and_propagates_channel(self):
        from app.services import scan_runners

        fake, captured = _captured_run_source_scan()
        fake_apify = AsyncMock(return_value=11)
        fake_extraction = AsyncMock(return_value=99)

        with patch.object(scan_runners, "_run_source_scan", new=fake), \
             patch.object(scan_runners.apify_meta_service, "scan_meta_ads", new=fake_apify), \
             patch.object(scan_runners.extraction_service, "scan_facebook_ads", new=fake_extraction), \
             patch("app.config.get_settings",
                   return_value=SimpleNamespace(serpapi_api_key=None, apify_api_key="set")):
            _run(scan_runners.run_facebook_scan(
                ["fb.com/acme"], SCAN_JOB_ID, DISTRIBUTOR_MAPPING,
                campaign_id=CAMPAIGN_ID, channel="instagram_via_meta",
            ))
            count = _run(captured["discover"]([]))

        assert count == 11
        fake_apify.assert_awaited_once()
        kwargs = fake_apify.await_args.kwargs
        assert kwargs.get("channel") == "instagram_via_meta"
        fake_extraction.assert_not_called()

    def test_discover_falls_back_to_playwright_without_apify_key(self):
        from app.services import scan_runners

        fake, captured = _captured_run_source_scan()
        fake_apify = AsyncMock(return_value=11)
        fake_extraction = AsyncMock(return_value=4)

        with patch.object(scan_runners, "_run_source_scan", new=fake), \
             patch.object(scan_runners.apify_meta_service, "scan_meta_ads", new=fake_apify), \
             patch.object(scan_runners.extraction_service, "scan_facebook_ads", new=fake_extraction), \
             patch("app.config.get_settings",
                   return_value=SimpleNamespace(serpapi_api_key=None, apify_api_key=None)):
            _run(scan_runners.run_facebook_scan(
                ["fb.com/acme"], SCAN_JOB_ID, DISTRIBUTOR_MAPPING,
                campaign_id=CAMPAIGN_ID,
            ))
            count = _run(captured["discover"]([]))

        assert count == 4
        fake_apify.assert_not_called()
        fake_extraction.assert_awaited_once()


class TestInstagramWrapperDispatch:
    def test_passes_instagram_source_label_and_invokes_apify(self):
        from app.services import scan_runners

        fake, captured = _captured_run_source_scan()
        fake_apify = AsyncMock(return_value=23)

        with patch.object(scan_runners, "_run_source_scan", new=fake), \
             patch.object(scan_runners.apify_instagram_service,
                          "scan_instagram_organic", new=fake_apify):
            _run(scan_runners.run_instagram_scan(
                ["instagram.com/acme"], SCAN_JOB_ID, DISTRIBUTOR_MAPPING,
                campaign_id=CAMPAIGN_ID,
            ))
            count = _run(captured["discover"]([{"id": "a"}]))

        assert captured["source"] == "instagram"
        assert count == 23
        fake_apify.assert_awaited_once()


# ---------------------------------------------------------------------------
# Shared driver `_run_source_scan` — success, failure, no-campaign branches
# ---------------------------------------------------------------------------

@pytest.fixture()
def driver_collaborators():
    """Stub the side-effecting collaborators of `_run_source_scan` so we can
    observe its sequencing without touching the network or DB."""
    from app.services import scan_runners

    auto = AsyncMock()
    fetch = AsyncMock(return_value=[{"id": "asset-1"}])
    notify = MagicMock()
    persist = MagicMock()

    cost_ctx = MagicMock()
    cost_ctx.__enter__.return_value = MagicMock(name="tracker")
    cost_ctx.__exit__.return_value = False
    cost_ctx_factory = MagicMock(return_value=cost_ctx)

    fake_supabase = MagicMock()
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    with patch.object(scan_runners, "auto_analyze_scan", new=auto), \
         patch.object(scan_runners, "_fetch_campaign_assets", new=fetch), \
         patch.object(scan_runners, "_send_scan_notifications", new=notify), \
         patch.object(scan_runners, "_persist_cost", new=persist), \
         patch.object(scan_runners, "scan_cost_context", new=cost_ctx_factory), \
         patch.object(scan_runners, "supabase", new=fake_supabase):
        yield SimpleNamespace(
            auto=auto, fetch=fetch, notify=notify, persist=persist,
            cost_ctx_factory=cost_ctx_factory, supabase=fake_supabase,
        )


class TestRunSourceScanDriver:
    def test_success_path_persists_cost_marks_completed_notifies(self, driver_collaborators):
        from app.services.scan_runners import _run_source_scan

        discover = AsyncMock(return_value=5)
        _run(_run_source_scan(
            source="google_ads",
            scan_job_id=SCAN_JOB_ID,
            campaign_id=CAMPAIGN_ID,
            discover=discover,
        ))

        col = driver_collaborators
        discover.assert_awaited_once_with([{"id": "asset-1"}])
        col.auto.assert_awaited_once_with(SCAN_JOB_ID, CAMPAIGN_ID)
        col.persist.assert_called_once()
        col.notify.assert_called_once()
        # Two scan_jobs.update calls: running + completed.
        update_calls = col.supabase.table.return_value.update.call_args_list
        statuses = [c.args[0].get("status") for c in update_calls]
        assert statuses == ["running", "completed"]

    def test_skips_auto_analyze_when_no_campaign(self, driver_collaborators):
        from app.services.scan_runners import _run_source_scan

        discover = AsyncMock(return_value=5)
        _run(_run_source_scan(
            source="instagram",
            scan_job_id=SCAN_JOB_ID,
            campaign_id=None,
            discover=discover,
        ))

        col = driver_collaborators
        col.auto.assert_not_called()
        col.notify.assert_called_once()

    def test_skips_auto_analyze_when_zero_discovered(self, driver_collaborators):
        from app.services.scan_runners import _run_source_scan

        discover = AsyncMock(return_value=0)
        _run(_run_source_scan(
            source="facebook",
            scan_job_id=SCAN_JOB_ID,
            campaign_id=CAMPAIGN_ID,
            discover=discover,
        ))

        col = driver_collaborators
        col.auto.assert_not_called()

    def test_failure_path_marks_failed_and_skips_notifications(self, driver_collaborators):
        from app.services.scan_runners import _run_source_scan

        discover = AsyncMock(side_effect=RuntimeError("apify down"))
        _run(_run_source_scan(
            source="instagram",
            scan_job_id=SCAN_JOB_ID,
            campaign_id=CAMPAIGN_ID,
            discover=discover,
        ))

        col = driver_collaborators
        col.persist.assert_called_once()
        col.notify.assert_not_called()  # never notify on failure
        update_calls = col.supabase.table.return_value.update.call_args_list
        statuses = [c.args[0].get("status") for c in update_calls]
        assert statuses == ["running", "failed"]
        # The error message must propagate onto scan_jobs.
        failed_payload = update_calls[-1].args[0]
        assert failed_payload.get("error_message") == "apify down"

    def test_auto_analyze_failure_does_not_fail_the_scan(self, driver_collaborators):
        from app.services.scan_runners import _run_source_scan

        col = driver_collaborators
        col.auto.side_effect = RuntimeError("analysis broke")

        discover = AsyncMock(return_value=3)
        _run(_run_source_scan(
            source="google_ads",
            scan_job_id=SCAN_JOB_ID,
            campaign_id=CAMPAIGN_ID,
            discover=discover,
        ))

        # Scan still completes — analysis errors are non-fatal.
        update_calls = col.supabase.table.return_value.update.call_args_list
        statuses = [c.args[0].get("status") for c in update_calls]
        assert statuses == ["running", "completed"]
        col.notify.assert_called_once()
