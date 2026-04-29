"""Phase 6 — render-strategy ladder unit tests.

These tests exercise the ladder *orchestration* without touching
Playwright or ScreenshotOne. We monkey-patch the two underlying calls
(``extraction_service._extract_from_viewport`` and
``screenshot_service.capture_and_upload``) with cheap async stubs and
verify the runner walks the right rungs in the right order, stops on
``OUTCOME_IMAGES``, and returns the most-informative result on full
exhaustion.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import uuid4

import pytest


def _run(coro):
    """Drive a coroutine to completion (project doesn't pull in
    pytest-asyncio)."""
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def _ctx(url: str = "https://example.com/page"):
    from app.services.render_strategies import RenderContext
    return RenderContext(url=url, scan_job_id=uuid4())


def _result(outcome: str, count: int = 0, evidence_url=None, reason=None, http_status=None):
    from app.services.extraction_service import ExtractionResult
    return ExtractionResult(
        count=count,
        evidence_url=evidence_url,
        outcome=outcome,
        block_reason=reason,
        http_status=http_status,
    )


# ---------------------------------------------------------------------------
# Strategy mapping
# ---------------------------------------------------------------------------

class TestStrategyMapping:
    def test_all_strategies_have_a_ladder(self):
        from app.services import render_strategies as rs
        for name in rs.ALL_STRATEGIES:
            assert name in rs.STRATEGY_LADDERS, name
            assert len(rs.STRATEGY_LADDERS[name]) >= 1

    def test_promotion_walks_ladder_and_pins_at_unreachable(self):
        from app.services import render_strategies as rs
        chain = []
        cur = rs.STRATEGY_PLAYWRIGHT_DESKTOP
        for _ in range(20):
            chain.append(cur)
            nxt = rs.next_strategy(cur)
            if nxt == cur:
                break
            cur = nxt
        # Should walk the full PROMOTION_ORDER and stop on `unreachable`.
        assert chain == rs.PROMOTION_ORDER
        assert rs.next_strategy(rs.STRATEGY_UNREACHABLE) == rs.STRATEGY_UNREACHABLE

    def test_unknown_strategy_normalises_to_default(self):
        from app.services import render_strategies as rs
        assert rs.next_strategy("totally-bogus") == rs.STRATEGY_PLAYWRIGHT_DESKTOP


# ---------------------------------------------------------------------------
# Ladder runner behaviour
# ---------------------------------------------------------------------------

class TestRunLadder:
    def test_stops_on_first_images_outcome(self):
        from app.services import render_strategies as rs

        calls = []

        async def fake_viewport(*, url, scan_job_id, distributor_id, mobile,
                                seen_srcs, campaign_assets):
            calls.append(("playwright_mobile" if mobile else "playwright_desktop"))
            # First call (desktop) wins.
            return _result("images", count=5)

        async def fake_capture_and_upload(*args, **kwargs):
            calls.append("screenshotone")
            return None

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.screenshot_service.capture_and_upload",
            side_effect=fake_capture_and_upload,
        ):
            res = _run(rs.run_ladder(_ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_DESKTOP))

        assert res.succeeded_attempt == "playwright_desktop"
        assert res.final.outcome == "images"
        assert res.final.count == 5
        # Desktop won — mobile and ScreenshotOne should never run.
        assert calls == ["playwright_desktop"]

    def test_short_circuits_on_first_screenshotone_capture(self):
        """After Playwright fails on a Cat-style WAF, the datacenter SS1
        call captures evidence — the ladder MUST NOT then waste an extra
        residential call (which is what was burning $$ before)."""
        from app.services import render_strategies as rs

        calls = []

        async def fake_viewport(*, url, scan_job_id, distributor_id, mobile,
                                seen_srcs, campaign_assets):
            label = "playwright_mobile" if mobile else "playwright_desktop"
            calls.append(label)
            return _result("blocked", reason="HTTP 403", http_status=403)

        seen_overrides = []

        async def fake_capture_and_upload(target_url, scan_job_id, **overrides):
            seen_overrides.append(overrides)
            return f"https://storage/{len(seen_overrides)}.png"

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.screenshot_service.capture_and_upload",
            side_effect=fake_capture_and_upload,
        ):
            res = _run(rs.run_ladder(_ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_DESKTOP))

        assert calls == ["playwright_desktop", "playwright_mobile"]
        # ONLY the datacenter SS1 call ran — residential short-circuited.
        assert len(seen_overrides) == 1
        assert "proxy_type" not in seen_overrides[0]
        # Final result carries the captured screenshot.
        assert res.final.evidence_url == "https://storage/1.png"
        assert res.final.outcome == "blocked"
        # No tier produced OUTCOME_IMAGES so succeeded_attempt is None.
        assert res.succeeded_attempt is None

    def test_residential_uses_proxy_type_param_when_datacenter_fails(self):
        """If the datacenter SS1 returns no evidence, we must escalate to
        residential using the correct ScreenshotOne param name (proxy_type,
        not proxy — the latter caused 400s on every call)."""
        from app.services import render_strategies as rs

        seen_overrides = []
        call_count = [0]

        async def fake_viewport(**kwargs):
            return _result("blocked")

        async def fake_capture_and_upload(target_url, scan_job_id, **overrides):
            seen_overrides.append(overrides)
            call_count[0] += 1
            # Datacenter (1st call) fails — no URL. Residential (2nd call) wins.
            return None if call_count[0] == 1 else "https://storage/res.png"

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.screenshot_service.capture_and_upload",
            side_effect=fake_capture_and_upload,
        ):
            res = _run(rs.run_ladder(_ctx(), strategy=rs.STRATEGY_SCREENSHOTONE_ONLY))

        assert len(seen_overrides) == 2
        assert "proxy_type" not in seen_overrides[0]            # datacenter
        assert seen_overrides[1].get("proxy_type") == "residential"
        assert seen_overrides[1].get("delay") == 8
        assert res.final.evidence_url == "https://storage/res.png"

    def test_screenshotone_only_strategy_skips_playwright(self):
        from app.services import render_strategies as rs

        playwright_called = False

        async def fake_viewport(**kwargs):
            nonlocal playwright_called
            playwright_called = True
            return _result("images", count=99)  # would win if reached

        async def fake_capture_and_upload(*args, **kwargs):
            return "https://storage/x.png"

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.screenshot_service.capture_and_upload",
            side_effect=fake_capture_and_upload,
        ):
            res = _run(rs.run_ladder(
                _ctx(), strategy=rs.STRATEGY_SCREENSHOTONE_ONLY,
            ))

        assert playwright_called is False
        # Datacenter SS1 succeeded — short-circuit kicks in, residential skipped.
        assert [a.attempt for a in res.attempts] == ["screenshotone_datacenter"]
        assert res.final.evidence_url == "https://storage/x.png"

    def test_mobile_first_strategy_orders_attempts_correctly(self):
        from app.services import render_strategies as rs

        order = []

        async def fake_viewport(*, mobile, **kwargs):
            order.append("mobile" if mobile else "desktop")
            return _result("blocked")

        async def fake_capture_and_upload(*args, **kwargs):
            return "https://storage/y.png"

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.screenshot_service.capture_and_upload",
            side_effect=fake_capture_and_upload,
        ):
            _run(rs.run_ladder(
                _ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_MOBILE_FIRST,
            ))

        assert order[:2] == ["mobile", "desktop"]

    def test_unknown_strategy_falls_back_to_default_ladder(self):
        from app.services import render_strategies as rs

        called = []

        async def fake_viewport(**kwargs):
            called.append("playwright")
            return _result("images", count=1)

        async def fake_capture_and_upload(*args, **kwargs):
            return None

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.screenshot_service.capture_and_upload",
            side_effect=fake_capture_and_upload,
        ):
            res = _run(rs.run_ladder(_ctx(), strategy="bogus"))

        assert called == ["playwright"]
        assert res.succeeded_attempt == "playwright_desktop"
