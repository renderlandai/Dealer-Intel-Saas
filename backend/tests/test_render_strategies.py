"""Phase 6.5 — render-strategy ladder unit tests.

These tests exercise the ladder *orchestration* without touching
Playwright or Bright Data Web Unlocker. We monkey-patch the two
underlying calls (``extraction_service._extract_from_viewport`` and
``unlocker_service.unlock_and_extract``) with cheap async stubs and
verify the runner walks the right rungs in the right order, stops on
``OUTCOME_IMAGES``, and returns the most-informative result on full
exhaustion.

The ladders themselves were renamed in Phase 6.5 (ScreenshotOne →
Bright Data); the orchestration contract is unchanged.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import uuid4

import pytest


def _run(coro):
    """Drive a coroutine to completion (project doesn't pull in
    pytest-asyncio)."""
    return asyncio.run(coro)


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

    def test_every_ladder_has_at_least_two_rungs_or_unlocker_only(self):
        """Structural invariant from the 2026-04-30 incident: a single
        broken provider must never collapse a host's whole ladder.
        ``unlocker_only`` and ``unreachable`` are documented exceptions
        (their single rung is the explicit point of the strategy)."""
        from app.services import render_strategies as rs
        single_rung_allowed = {
            rs.STRATEGY_UNLOCKER_ONLY,
            rs.STRATEGY_UNREACHABLE,
        }
        for name, ladder in rs.STRATEGY_LADDERS.items():
            if name in single_rung_allowed:
                continue
            assert len(ladder) >= 2, f"{name} ladder has only one rung"

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

    def test_no_screenshotone_strategy_remains(self):
        """Phase 6.5: every SS1 strategy was migrated. A regression that
        re-introduces one would silently break every host promoted to
        the dead strategy."""
        from app.services import render_strategies as rs
        for name in rs.ALL_STRATEGIES:
            assert "screenshotone" not in name


# ---------------------------------------------------------------------------
# Ladder runner behaviour
# ---------------------------------------------------------------------------

class TestRunLadder:
    def test_stops_on_first_images_outcome(self):
        from app.services import render_strategies as rs

        calls = []

        async def fake_viewport(*, url, scan_job_id, distributor_id, mobile,
                                seen_srcs, campaign_assets):
            calls.append("playwright_mobile" if mobile else "playwright_desktop")
            return _result("images", count=5)

        async def fake_unlock(*args, **kwargs):
            calls.append("brightdata_unlocker")
            return _result("images", count=99)

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.unlocker_service.unlock_and_extract",
            side_effect=fake_unlock,
        ):
            res = _run(rs.run_ladder(_ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_DESKTOP))

        assert res.succeeded_attempt == "playwright_desktop"
        assert res.final.outcome == "images"
        assert res.final.count == 5
        # Desktop won — mobile and unlocker should never run.
        assert calls == ["playwright_desktop"]

    def test_falls_through_to_unlocker_when_playwright_blocks(self):
        """The Cat-style WAF case: Playwright desktop and mobile both
        return blocked, the unlocker rung succeeds with real images.
        The whole point of Phase 6.5."""
        from app.services import render_strategies as rs

        calls = []

        async def fake_viewport(*, url, scan_job_id, distributor_id, mobile,
                                seen_srcs, campaign_assets):
            label = "playwright_mobile" if mobile else "playwright_desktop"
            calls.append(label)
            return _result("blocked", reason="HTTP 403", http_status=403)

        async def fake_unlock(**kwargs):
            calls.append("brightdata_unlocker")
            return _result("images", count=12)

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.unlocker_service.unlock_and_extract",
            side_effect=fake_unlock,
        ):
            res = _run(rs.run_ladder(_ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_DESKTOP))

        assert calls == [
            "playwright_desktop", "playwright_mobile", "brightdata_unlocker",
        ]
        assert res.succeeded_attempt == "brightdata_unlocker"
        assert res.final.outcome == "images"
        assert res.final.count == 12

    def test_unlocker_only_strategy_skips_playwright(self):
        from app.services import render_strategies as rs

        playwright_called = False

        async def fake_viewport(**kwargs):
            nonlocal playwright_called
            playwright_called = True
            return _result("images", count=99)

        async def fake_unlock(**kwargs):
            return _result("images", count=4)

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.unlocker_service.unlock_and_extract",
            side_effect=fake_unlock,
        ):
            res = _run(rs.run_ladder(
                _ctx(), strategy=rs.STRATEGY_UNLOCKER_ONLY,
            ))

        assert playwright_called is False
        assert [a.attempt for a in res.attempts] == ["brightdata_unlocker"]
        assert res.succeeded_attempt == "brightdata_unlocker"
        assert res.final.count == 4

    def test_mobile_first_strategy_orders_attempts_correctly(self):
        from app.services import render_strategies as rs

        order = []

        async def fake_viewport(*, mobile, **kwargs):
            order.append("mobile" if mobile else "desktop")
            return _result("blocked")

        async def fake_unlock(**kwargs):
            order.append("unlocker")
            return _result("images", count=1)

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.unlocker_service.unlock_and_extract",
            side_effect=fake_unlock,
        ):
            _run(rs.run_ladder(
                _ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_MOBILE_FIRST,
            ))

        assert order == ["mobile", "desktop", "unlocker"]

    def test_unknown_strategy_falls_back_to_default_ladder(self):
        from app.services import render_strategies as rs

        called = []

        async def fake_viewport(**kwargs):
            called.append("playwright")
            return _result("images", count=1)

        async def fake_unlock(**kwargs):
            return _result("images", count=99)

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.unlocker_service.unlock_and_extract",
            side_effect=fake_unlock,
        ):
            res = _run(rs.run_ladder(_ctx(), strategy="bogus"))

        assert called == ["playwright"]
        assert res.succeeded_attempt == "playwright_desktop"

    def test_records_block_reason_when_all_rungs_fail(self):
        """All rungs return BLOCKED with no images — the final result
        should carry the most informative attempt's metadata so the
        operator can see *why* the ladder gave up."""
        from app.services import render_strategies as rs

        async def fake_viewport(**kwargs):
            return _result("blocked", reason="ERR_ABORTED", http_status=403)

        async def fake_unlock(**kwargs):
            return _result(
                "blocked",
                reason="brightdata_http_429",
                http_status=429,
            )

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.unlocker_service.unlock_and_extract",
            side_effect=fake_unlock,
        ):
            res = _run(rs.run_ladder(
                _ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_THEN_UNLOCKER,
            ))

        assert res.succeeded_attempt is None
        assert res.final.outcome == "blocked"
        assert len(res.attempts) == 2
        assert res.attempts[0].attempt == "playwright_desktop"
        assert res.attempts[1].attempt == "brightdata_unlocker"

    def test_attempt_crash_is_captured_and_does_not_abort_ladder(self):
        """An exception in one rung should not break the ladder — it
        records a CRASHED outcome and moves to the next rung."""
        from app.services import render_strategies as rs

        async def fake_viewport(**kwargs):
            raise RuntimeError("playwright exploded")

        async def fake_unlock(**kwargs):
            return _result("images", count=3)

        with patch(
            "app.services.extraction_service._extract_from_viewport",
            side_effect=fake_viewport,
        ), patch(
            "app.services.unlocker_service.unlock_and_extract",
            side_effect=fake_unlock,
        ):
            res = _run(rs.run_ladder(
                _ctx(), strategy=rs.STRATEGY_PLAYWRIGHT_THEN_UNLOCKER,
            ))

        assert res.succeeded_attempt == "brightdata_unlocker"
        assert res.attempts[0].outcome == "crashed"
        assert "playwright exploded" in (res.attempts[0].block_reason or "")
