"""Phase 6.5.10 — match-quality regression fix tests.

Pins each of the six independent guarantees that 6.5.10 introduces. The
guarantees are independent on purpose so a future change that
regresses one of them fails exactly one test (not the whole suite),
which makes triage in CI fast.

Covered:
1. ``cv_matching.template_match`` default threshold tightened to 0.55.
2. ``ai_service.verify_borderline_match`` uses weighted continuous
   scoring capped at the original comparison score, and requires
   ``gates_passed >= 4``.
3. ``ai_service._passes_hash_prefilter`` requires both phash AND dhash
   to agree (max-of-two), not the mean of four.
4. ``ai_service._is_valid_image`` rejects sub-80px images.
5. ``ai_service.process_discovered_image`` drops the match when
   ``compliance.asset_visible`` is False.
6. ``host_policy_service.record_host_outcomes`` auto-demotes a
   BD-pinned host that succeeds on a Playwright rung.
"""
from __future__ import annotations

import asyncio
import io
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image


def _run(coro):
    return asyncio.run(coro)


def _png_bytes(width: int = 200, height: int = 200, color: tuple = (200, 100, 50)) -> bytes:
    """Build a real PNG of the requested size so PIL.verify() accepts it."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. cv_matching threshold
# ---------------------------------------------------------------------------


class TestCvMatchingThreshold:
    def test_template_match_default_is_055(self):
        """The default template-match threshold MUST be 0.55. 0.40 was
        the regressed value that admitted gradient-overlap noise on
        50-scale max-pooled sweeps."""
        from app.services.cv_matching import template_match
        import inspect
        sig = inspect.signature(template_match)
        assert sig.parameters["threshold"].default == 0.55

    def test_find_asset_on_page_default_threshold_is_055(self):
        """Same contract on the wrapper that the extraction service calls."""
        from app.services.cv_matching import find_asset_on_page
        import inspect
        sig = inspect.signature(find_asset_on_page)
        assert sig.parameters["template_threshold"].default == 0.55


# ---------------------------------------------------------------------------
# 2. verify_borderline_match scoring
# ---------------------------------------------------------------------------


class TestVerifyBorderlineMatchScoring:
    """The verify step must use continuous weighted scoring, must
    require ≥4 of 5 gates, and must never inflate the score above
    what compare_images saw (cap at initial_score)."""

    def _patch_io(self, claude_response: Dict[str, Any]):
        from app.services import ai_service

        async def _fake_download(_url: str) -> bytes:
            return _png_bytes()

        async def _fake_call_anthropic(*_args, **_kwargs) -> str:
            import json
            return json.dumps(claude_response)

        return [
            patch.object(ai_service, "download_image", side_effect=_fake_download),
            patch.object(ai_service, "optimize_image_for_api",
                         side_effect=lambda b, _kind: b),
            patch.object(ai_service, "call_anthropic_with_retry",
                         side_effect=_fake_call_anthropic),
            patch.object(ai_service, "extract_json_from_response",
                         side_effect=lambda _r: claude_response),
        ]

    def test_three_gates_no_longer_passes(self):
        """The old rule was `gates_passed >= 3`. 6.5.10 tightened to
        `>= 4` so brand+product+ANY ONE other no longer admits the
        match — a navigation-tile ghost crop that shared the dealer
        logo + a vaguely-similar product silhouette no longer slips
        through."""
        from app.services import ai_service

        response = {
            "is_match": True,
            "gates_passed": 3,
            "gate_brand": True,
            "gate_product": True,
            "gate_message": True,
            "gate_offer": False,
            "gate_design": False,
            "verdict": "borderline",
        }
        patches = self._patch_io(response)
        for p in patches:
            p.start()
        try:
            result = _run(ai_service.verify_borderline_match(
                "asset.png", "discovered.png", initial_score=70))
        finally:
            for p in patches:
                p.stop()
        assert result["is_match"] is False, "3 of 5 gates must NOT pass under 6.5.10"

    def test_four_gates_with_brand_and_product_passes(self):
        from app.services import ai_service

        response = {
            "is_match": True,
            "gates_passed": 4,
            "gate_brand": True,
            "gate_product": True,
            "gate_message": True,
            "gate_offer": True,
            "gate_design": False,
            "verdict": "match",
        }
        patches = self._patch_io(response)
        for p in patches:
            p.start()
        try:
            result = _run(ai_service.verify_borderline_match(
                "asset.png", "discovered.png", initial_score=72))
        finally:
            for p in patches:
                p.stop()
        assert result["is_match"] is True

    def test_verified_score_capped_at_initial_score(self):
        """Verify must never inflate. If compare_images said 65 and
        all 5 gates pass (weighted = 100), the recorded score is
        min(65, 100) = 65."""
        from app.services import ai_service

        response = {
            "is_match": True,
            "gates_passed": 5,
            "gate_brand": True,
            "gate_product": True,
            "gate_message": True,
            "gate_offer": True,
            "gate_design": True,
        }
        patches = self._patch_io(response)
        for p in patches:
            p.start()
        try:
            result = _run(ai_service.verify_borderline_match(
                "asset.png", "discovered.png", initial_score=65))
        finally:
            for p in patches:
                p.stop()
        assert result["verified_score"] == 65, (
            "verify must never inflate score above the comparison reading"
        )
        assert result["weighted_gate_score"] == 100

    def test_verified_score_continuous_not_discrete(self):
        """Old `gates_passed * 20` produced only {60, 80, 100}. New
        weighted scoring must be able to produce values outside that
        set."""
        from app.services import ai_service

        # 4 gates pass but design (weight 20) is the failed one →
        # weighted = 25 + 25 + 15 + 15 = 80 (a bucket value, but…)
        # 4 gates with the design gate passing instead of message →
        # weighted = 25 + 25 + 20 + 15 = 85 (NOT a bucket value).
        response = {
            "is_match": True,
            "gates_passed": 4,
            "gate_brand": True,
            "gate_product": True,
            "gate_message": False,
            "gate_offer": True,
            "gate_design": True,
        }
        patches = self._patch_io(response)
        for p in patches:
            p.start()
        try:
            result = _run(ai_service.verify_borderline_match(
                "asset.png", "discovered.png", initial_score=99))
        finally:
            for p in patches:
                p.stop()
        # 25+25+20+15 = 85 — not a multiple of 20, proves continuous.
        assert result["weighted_gate_score"] == 85
        assert result["verified_score"] == 85


# ---------------------------------------------------------------------------
# 3. Hash prefilter — both reliable hashes must agree
# ---------------------------------------------------------------------------


class TestHashPrefilterStrictRule:
    """The new rule is `max(phash_diff, dhash_diff) <= threshold`,
    against any single asset. A whash-only or average-hash-only
    coincidence MUST NOT admit the image."""

    def _hash(self, **kwargs):
        """Build a fake hash-set object that supports `-` returning
        the configured Hamming distance regardless of operand."""
        class _H:
            def __init__(self, dist):
                self.dist = dist
            def __sub__(self, other):
                return self.dist
        return {k: _H(v) for k, v in kwargs.items()}

    def test_admits_when_phash_and_dhash_both_close(self):
        from app.services import ai_service

        with patch.object(ai_service, "compute_image_hashes",
                          new=AsyncMock(return_value=self._hash(
                              phash=10, dhash=10, whash=50, average_hash=50))):
            asset_cache = [self._hash(phash=0, dhash=0, whash=0, average_hash=0)]
            result = _run(ai_service._passes_hash_prefilter(b"x", asset_cache))
        assert result is True

    def test_rejects_when_only_whash_is_close(self):
        """Pre-6.5.10 the mean of [50, 50, 5, 5] = 27.5 ≤ 28
        admitted. The strict rule (max(50, 50) = 50 > 28) rejects."""
        from app.services import ai_service

        with patch.object(ai_service, "compute_image_hashes",
                          new=AsyncMock(return_value=self._hash(
                              phash=50, dhash=50, whash=5, average_hash=5))):
            asset_cache = [self._hash(phash=0, dhash=0, whash=0, average_hash=0)]
            result = _run(ai_service._passes_hash_prefilter(b"x", asset_cache))
        assert result is False

    def test_rejects_when_only_one_reliable_hash_agrees(self):
        """phash close, dhash far → max is far → reject. A naive
        min-of-two would have admitted this."""
        from app.services import ai_service

        with patch.object(ai_service, "compute_image_hashes",
                          new=AsyncMock(return_value=self._hash(
                              phash=5, dhash=50, whash=5, average_hash=5))):
            asset_cache = [self._hash(phash=0, dhash=0, whash=0, average_hash=0)]
            result = _run(ai_service._passes_hash_prefilter(b"x", asset_cache))
        assert result is False


# ---------------------------------------------------------------------------
# 4. _is_valid_image min-dimension
# ---------------------------------------------------------------------------


class TestIsValidImageMinDimension:
    def test_rejects_1x1_tracker(self):
        from app.services.ai_service import _is_valid_image
        tracker = _png_bytes(1, 1, (0, 0, 0))
        assert _is_valid_image(tracker) is False

    def test_rejects_64px_favicon(self):
        from app.services.ai_service import _is_valid_image
        favicon = _png_bytes(64, 64)
        assert _is_valid_image(favicon) is False

    def test_accepts_80px_minimum(self):
        from app.services.ai_service import _is_valid_image
        assert _is_valid_image(_png_bytes(80, 80)) is True

    def test_accepts_real_creative(self):
        from app.services.ai_service import _is_valid_image
        assert _is_valid_image(_png_bytes(800, 600)) is True

    def test_rejects_tall_thin_strip(self):
        """One dimension below 80 still means rejected, regardless of
        the other — sprite strips, divider lines, etc."""
        from app.services.ai_service import _is_valid_image
        assert _is_valid_image(_png_bytes(800, 32)) is False

    def test_invalid_payload_still_rejected(self):
        from app.services.ai_service import _is_valid_image
        assert _is_valid_image(b"not an image") is False


# ---------------------------------------------------------------------------
# 5. asset_visible gate in process_discovered_image
# ---------------------------------------------------------------------------


class TestComplianceAssetVisibleGate:
    def test_compliance_check_result_has_asset_visible_default_true(self):
        """Backward compat for old callers that didn't pass the field."""
        from app.models import ComplianceCheckResult
        result = ComplianceCheckResult(
            is_compliant=True,
            issues=[],
            brand_elements={},
            analysis_summary="",
        )
        assert result.asset_visible is True

    def test_compliance_check_result_accepts_asset_visible_false(self):
        from app.models import ComplianceCheckResult
        result = ComplianceCheckResult(
            is_compliant=True,
            issues=[],
            brand_elements={},
            analysis_summary="",
            asset_visible=False,
        )
        assert result.asset_visible is False

    def test_analyze_compliance_reads_asset_visible_from_response(self):
        """The Claude prompt has always returned `asset_visible`. We
        finally read it."""
        from app.services import ai_service

        async def _fake_download(_url):
            return _png_bytes()

        async def _fake_call(*_a, **_kw):
            return "{}"

        claude_response = {
            "is_compliant": True,
            "issues": [],
            "brand_elements": {},
            "zombie_ad": False,
            "analysis_summary": "creative not actually present in this image",
            "asset_visible": False,
        }

        with patch.object(ai_service, "download_image", side_effect=_fake_download), \
             patch.object(ai_service, "optimize_image_for_api",
                          side_effect=lambda b, _kind: b), \
             patch.object(ai_service, "call_anthropic_with_retry", side_effect=_fake_call), \
             patch.object(ai_service, "extract_json_from_response",
                          side_effect=lambda _r: claude_response):
            result = _run(ai_service.analyze_compliance(
                "discovered.png", "asset.png", brand_rules={}))
        assert result.asset_visible is False
        assert result.is_compliant is True  # field is independent

    def test_process_discovered_image_returns_compliance_asset_not_visible(self):
        """Even if compare_images and verify both said "match",
        compliance saying `asset_visible=false` MUST drop the match."""
        from app.services import ai_service
        from app.models import ComplianceCheckResult

        # Build the minimal scaffold so we reach the compliance gate.
        # We mock everything from the matcher's perspective so the
        # only real logic exercised is the gate itself.
        async def _fake_filter(*_a, **_kw):
            class _F:
                is_relevant = True
                confidence = 99
            return _F()

        async def _fake_match(*_a, **_kw):
            return {
                "similarity_score": 90,
                "modifications": [],
                "method_scores": {},
            }

        async def _fake_compliance(*_a, **_kw):
            return ComplianceCheckResult(
                is_compliant=True,
                issues=[],
                brand_elements={},
                zombie_ad=False,
                analysis_summary="not present",
                asset_visible=False,
            )

        async def _fake_download(_url):
            return _png_bytes()

        async def _fake_adaptive(*_a, **_kw):
            return 70, {"confidence": "high"}

        with patch.object(ai_service, "filter_image", side_effect=_fake_filter), \
             patch.object(ai_service, "ensemble_match", side_effect=_fake_match), \
             patch.object(ai_service, "download_image", side_effect=_fake_download), \
             patch.object(ai_service, "should_verify_match",
                          new=AsyncMock(return_value=False)), \
             patch.object(ai_service, "calibrate_confidence",
                          new=AsyncMock(return_value=80)), \
             patch.object(ai_service, "analyze_compliance", side_effect=_fake_compliance), \
             patch.object(ai_service, "get_adaptive_threshold",
                          side_effect=_fake_adaptive), \
             patch.object(ai_service, "_passes_hash_prefilter",
                          new=AsyncMock(return_value=True)), \
             patch.object(ai_service, "_passes_clip_prefilter",
                          new=AsyncMock(return_value=True)):
            result, status, _diag = _run(ai_service.process_discovered_image(
                discovered_image_id="img-1",
                image_url="discovered.png",
                campaign_assets=[{"id": "asset-1", "file_url": "asset.png"}],
                brand_rules={},
                source_type="website_banner",
                channel="website",
                asset_hashes_cache=[],
                asset_embeddings_cache=[],
            ))

        assert result is None, "asset_visible=False MUST drop the match"
        assert status == "compliance_asset_not_visible"


# ---------------------------------------------------------------------------
# 6. Auto-demote on Playwright-rung success
# ---------------------------------------------------------------------------


def _patched_supabase_with_existing_row(row):
    """Lightweight supabase double — copied shape from
    test_host_policy_service.py so the new tests don't depend on the
    old test's fixtures."""
    counter_row = {
        "success_count_30d": 0,
        "blocked_count_30d": 0,
        "timeout_count_30d": 0,
    }

    select_mock = MagicMock()
    select_mock.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[row])

    counter_select = MagicMock()
    counter_select.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[counter_row])

    table_mock = MagicMock()
    table_mock.select.side_effect = [select_mock, counter_select, select_mock, counter_select]
    table_mock.upsert.return_value.execute.return_value = MagicMock()

    mock = MagicMock()
    mock.table.return_value = table_mock
    return mock, table_mock


class TestAutoDemoteOnPlaywrightSuccess:
    @staticmethod
    def _row(strategy="unlocker_only", confidence=0, manual_override=False):
        return {
            "hostname": "rent.cat.com",
            "strategy": strategy,
            "confidence": confidence,
            "last_outcome": "images",
            "manual_override": manual_override,
            "waf_vendor": None,
        }

    @staticmethod
    def _agg(images=0, **kwargs):
        from app.services.host_policy_service import HostOutcomeAggregate
        return HostOutcomeAggregate(hostname="rent.cat.com", images=images, **kwargs)

    def test_demotes_one_rung_when_playwright_succeeded(self):
        """unlocker_only → playwright_then_unlocker, not all the way
        to playwright_desktop. The 'one rung at a time' rule prevents
        oscillation on intermittently-blocked hosts."""
        from app.services.host_policy_service import record_host_outcomes
        mock, _ = _patched_supabase_with_existing_row(
            self._row(strategy="unlocker_only"))
        with patch("app.services.host_policy_service.supabase", mock):
            transitions = record_host_outcomes(
                {"rent.cat.com": self._agg(images=3)},
                playwright_success_by_host={"rent.cat.com": 2},
            )
        assert transitions == [
            ("rent.cat.com", "unlocker_only", "playwright_then_unlocker", "demoted"),
        ]

    def test_does_not_demote_when_only_bd_succeeded(self):
        """The whole point of the 6.5.10 plumbing: BD-rung success
        does NOT trigger demote. The host stays where it is."""
        from app.services.host_policy_service import record_host_outcomes
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(strategy="unlocker_only"))
        with patch("app.services.host_policy_service.supabase", mock):
            transitions = record_host_outcomes(
                {"rent.cat.com": self._agg(images=3)},
                playwright_success_by_host={},  # BD-only success
            )
        assert transitions == []
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "unlocker_only"

    def test_does_not_demote_when_manual_override(self):
        """Operator overrides win. A row pinned with manual_override
        never auto-demotes, even when Playwright succeeds."""
        from app.services.host_policy_service import record_host_outcomes
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(strategy="unlocker_only", manual_override=True))
        with patch("app.services.host_policy_service.supabase", mock):
            transitions = record_host_outcomes(
                {"rent.cat.com": self._agg(images=3)},
                playwright_success_by_host={"rent.cat.com": 5},
            )
        assert transitions == []
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "unlocker_only"

    def test_does_not_demote_when_already_at_bottom(self):
        """playwright_desktop is the bottom rung. Demote on a host
        already there is a no-op."""
        from app.services.host_policy_service import record_host_outcomes
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(strategy="playwright_desktop"))
        with patch("app.services.host_policy_service.supabase", mock):
            transitions = record_host_outcomes(
                {"rent.cat.com": self._agg(images=3)},
                playwright_success_by_host={"rent.cat.com": 5},
            )
        assert transitions == []

    def test_demote_resets_confidence(self):
        """A demote, like a promote, resets the failure-confidence
        counter so a single later flake doesn't immediately
        re-promote. Note: PROMOTION_ORDER is
        [playwright_desktop, playwright_mobile_first, playwright_then_unlocker, unlocker_only],
        so demote from `playwright_then_unlocker` lands on
        `playwright_mobile_first` — one rung at a time."""
        from app.services.host_policy_service import record_host_outcomes
        mock, table_mock = _patched_supabase_with_existing_row(
            self._row(strategy="playwright_then_unlocker", confidence=1))
        with patch("app.services.host_policy_service.supabase", mock):
            record_host_outcomes(
                {"rent.cat.com": self._agg(images=4)},
                playwright_success_by_host={"rent.cat.com": 2},
            )
        upserted = table_mock.upsert.call_args[0][0]
        assert upserted["strategy"] == "playwright_mobile_first"
        assert upserted["confidence"] == 0
