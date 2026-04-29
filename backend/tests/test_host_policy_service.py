"""Phase 6 — host_policy_service unit tests.

Covers the three things the runner relies on:

* WAF-vendor sniffing from response headers
* Aggregation of pipeline_stats.blocked_details into per-host counters
* Auto-promotion logic across consecutive failed scans

The Supabase calls are stubbed out wholesale via patching the module's
``supabase`` import; we never hit a real database.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# WAF detection
# ---------------------------------------------------------------------------

class TestDetectWaf:
    def test_returns_none_for_plain_response(self):
        from app.services.host_policy_service import detect_waf
        assert detect_waf({"server": "nginx/1.21", "x-powered-by": "Express"}) is None

    def test_detects_akamai(self):
        from app.services.host_policy_service import detect_waf
        assert detect_waf({"server": "AkamaiGHost"}) == "akamai"
        assert detect_waf({"x-akamai-transformed": "9 0 0"}) == "akamai"

    def test_detects_cloudflare(self):
        from app.services.host_policy_service import detect_waf
        assert detect_waf({"cf-ray": "abc123-DFW"}) == "cloudflare"
        assert detect_waf({"server": "cloudflare"}) == "cloudflare"

    def test_detects_cloudfront(self):
        from app.services.host_policy_service import detect_waf
        assert detect_waf({"x-amz-cf-id": "abc123"}) == "cloudfront"

    def test_detects_imperva_via_set_cookie(self):
        from app.services.host_policy_service import detect_waf
        assert detect_waf({
            "set-cookie": "incap_ses_123_456=abc; path=/",
        }) == "imperva"

    def test_case_insensitive_header_lookup(self):
        from app.services.host_policy_service import detect_waf
        # Headers normalised to lowercase regardless of input casing.
        assert detect_waf({"CF-Ray": "x"}) == "cloudflare"
        assert detect_waf({"Server": "AKAMAIGHOST"}) == "akamai"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestAggregateFromPipelineStats:
    def test_empty_stats_returns_empty_dict(self):
        from app.services.host_policy_service import aggregate_from_pipeline_stats
        assert aggregate_from_pipeline_stats({}) == {}
        assert aggregate_from_pipeline_stats({"blocked_details": []}) == {}

    def test_groups_pages_by_hostname(self):
        from app.services.host_policy_service import aggregate_from_pipeline_stats
        stats = {
            "blocked_details": [
                {
                    "base_url": "https://rent.cat.com/dealerA",
                    "pages": [
                        {"page_url": "https://rent.cat.com/dealerA/page1",
                         "outcome": "blocked", "reason": "HTTP 403", "http_status": 403},
                        {"page_url": "https://rent.cat.com/dealerA/page2",
                         "outcome": "timeout", "reason": None},
                    ],
                },
                {
                    "base_url": "https://rent.cat.com/dealerB",
                    "pages": [
                        {"page_url": "https://rent.cat.com/dealerB/home",
                         "outcome": "blocked", "reason": "HTTP 403", "http_status": 403},
                    ],
                },
                {
                    "base_url": "https://yancey.example.com",
                    "pages": [
                        {"page_url": "https://yancey.example.com/lp",
                         "outcome": "timeout"},
                    ],
                },
            ]
        }
        agg = aggregate_from_pipeline_stats(stats)
        assert set(agg.keys()) == {"rent.cat.com", "yancey.example.com"}
        assert agg["rent.cat.com"].blocked == 2
        assert agg["rent.cat.com"].timeout == 1
        assert agg["rent.cat.com"].last_block_reason == "HTTP 403"
        assert agg["rent.cat.com"].last_http_status == 403
        assert agg["yancey.example.com"].timeout == 1
        assert agg["yancey.example.com"].blocked == 0

    def test_merge_host_successes_creates_entries_for_clean_hosts(self):
        from app.services.host_policy_service import (
            aggregate_from_pipeline_stats, merge_host_successes,
        )
        agg = aggregate_from_pipeline_stats({})
        merge_host_successes(agg, {"clean.example.com": 7})
        assert "clean.example.com" in agg
        assert agg["clean.example.com"].images == 7
        assert agg["clean.example.com"].any_succeeded is True
        assert agg["clean.example.com"].all_failed is False


# ---------------------------------------------------------------------------
# Auto-promotion logic
# ---------------------------------------------------------------------------

def _patched_supabase_with_existing_row(row: Dict[str, Any]):
    """Build a MagicMock chain that returns ``row`` for the get-policy
    call and accepts the subsequent upsert call without complaint."""
    mock = MagicMock()

    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=[row])

    upsert_chain = MagicMock()
    upsert_chain.execute.return_value = MagicMock(data=[row])

    table_mock = MagicMock()
    table_mock.select.return_value = select_chain
    table_mock.upsert.return_value = upsert_chain

    mock.table.return_value = table_mock
    return mock, table_mock


class TestRecordHostOutcomes:
    def _row(self, **overrides) -> Dict[str, Any]:
        base = {
            "hostname": "rent.cat.com",
            "strategy": "playwright_desktop",
            "waf_vendor": "akamai",
            "confidence": 0,
            "last_outcome": None,
            "manual_override": False,
            "success_count_30d": 0,
            "blocked_count_30d": 0,
            "timeout_count_30d": 0,
        }
        base.update(overrides)
        return base

    def _agg(self, hostname="rent.cat.com", **overrides):
        from app.services.host_policy_service import HostOutcomeAggregate
        return HostOutcomeAggregate(hostname=hostname, **overrides)

    def test_first_failure_increments_confidence_only(self):
        mock, table_mock = _patched_supabase_with_existing_row(self._row(confidence=0))
        with patch("app.services.host_policy_service.supabase", mock):
            from app.services.host_policy_service import record_host_outcomes
            promotions = record_host_outcomes({
                "rent.cat.com": self._agg(blocked=3, last_block_reason="HTTP 403"),
            })
        assert promotions == []
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "playwright_desktop"
        assert upserted["confidence"] == 1
        assert upserted["last_outcome"] == "blocked"

    def test_second_consecutive_failure_promotes_one_rung(self):
        # Existing row already has confidence=1 from the prior scan.
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(confidence=1, last_outcome="blocked"),
        )
        with patch("app.services.host_policy_service.supabase", mock):
            from app.services.host_policy_service import record_host_outcomes
            promotions = record_host_outcomes({
                "rent.cat.com": self._agg(blocked=3, last_block_reason="HTTP 403"),
            })
        assert promotions == [
            ("rent.cat.com", "playwright_desktop", "playwright_mobile_first"),
        ]
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "playwright_mobile_first"
        assert upserted["confidence"] == 0      # reset after promotion
        assert "last_promoted_at" in upserted

    def test_success_resets_confidence_and_does_not_demote(self):
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(strategy="screenshotone_only", confidence=4, last_outcome="blocked"),
        )
        with patch("app.services.host_policy_service.supabase", mock):
            from app.services.host_policy_service import record_host_outcomes
            promotions = record_host_outcomes({
                "rent.cat.com": self._agg(images=5),
            })
        assert promotions == []
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "screenshotone_only"   # not demoted
        assert upserted["confidence"] == 0
        assert upserted["last_outcome"] == "images"

    def test_manual_override_disables_auto_promotion(self):
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(confidence=5, manual_override=True),
        )
        with patch("app.services.host_policy_service.supabase", mock):
            from app.services.host_policy_service import record_host_outcomes
            promotions = record_host_outcomes({
                "rent.cat.com": self._agg(blocked=10),
            })
        assert promotions == []
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "playwright_desktop"  # unchanged

    def test_unreachable_strategy_is_sticky(self):
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(strategy="unreachable", confidence=5),
        )
        with patch("app.services.host_policy_service.supabase", mock):
            from app.services.host_policy_service import record_host_outcomes
            promotions = record_host_outcomes({
                "rent.cat.com": self._agg(blocked=10),
            })
        assert promotions == []
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "unreachable"


# ---------------------------------------------------------------------------
# Preflight probe — no real network; httpx.AsyncClient is patched.
# ---------------------------------------------------------------------------

def _fake_async_client(response_status: int, headers: Dict[str, str], raise_on_head: bool = False):
    """Return a context-manager class whose .head/.get returns a fake response."""

    class FakeResponse:
        def __init__(self, status, hdrs):
            self.status_code = status
            self.headers = hdrs

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None
        async def head(self, url, **kwargs):
            if raise_on_head:
                import httpx
                raise httpx.ConnectError("simulated")
            return FakeResponse(response_status, headers)
        async def get(self, url, **kwargs):
            return FakeResponse(response_status, headers)

    return FakeClient


class TestPreflightProbe:
    def test_clean_200_suggests_playwright_desktop(self):
        with patch(
            "app.services.host_policy_service.httpx.AsyncClient",
            _fake_async_client(200, {"server": "nginx"}),
        ):
            from app.services.host_policy_service import preflight_probe
            res = _run(preflight_probe("https://acme-equipment.com"))
        assert res.status == 200
        assert res.waf_vendor is None
        assert res.suggested_strategy == "playwright_desktop"

    def test_403_with_akamai_header_suggests_screenshotone_only(self):
        with patch(
            "app.services.host_policy_service.httpx.AsyncClient",
            _fake_async_client(403, {"server": "AkamaiGHost"}),
        ):
            from app.services.host_policy_service import preflight_probe
            res = _run(preflight_probe("https://rent.cat.com/dealer"))
        assert res.status == 403
        assert res.waf_vendor == "akamai"
        assert res.suggested_strategy == "screenshotone_only"

    def test_429_suggests_playwright_then_screenshotone(self):
        with patch(
            "app.services.host_policy_service.httpx.AsyncClient",
            _fake_async_client(429, {"server": "nginx"}),
        ):
            from app.services.host_policy_service import preflight_probe
            res = _run(preflight_probe("https://throttled.example.com"))
        assert res.suggested_strategy == "playwright_then_screenshotone"

    def test_connection_error_falls_through_to_safe_default(self):
        with patch(
            "app.services.host_policy_service.httpx.AsyncClient",
            _fake_async_client(0, {}, raise_on_head=True),
        ):
            from app.services.host_policy_service import preflight_probe
            # Both head() and get() raise here -> outer except path.
            class AlwaysRaiseClient:
                def __init__(self, *args, **kwargs):
                    pass
                async def __aenter__(self):
                    return self
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return None
                async def head(self, url, **kwargs):
                    import httpx
                    raise httpx.ConnectError("fail")
                async def get(self, url, **kwargs):
                    import httpx
                    raise httpx.ConnectError("fail")

            with patch(
                "app.services.host_policy_service.httpx.AsyncClient",
                AlwaysRaiseClient,
            ):
                res = _run(preflight_probe("https://flaky.example.com"))
        assert res.status is None
        assert res.suggested_strategy == "playwright_then_screenshotone"
        assert res.error is not None
