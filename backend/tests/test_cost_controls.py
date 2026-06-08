"""Tests for the 2026-06-08 cost controls.

Covers the three changes shipped after the $275 runaway website scan:

    1. SAFE — ``compare_images`` now requests prompt caching on the asset
       prefix (result-preserving; only billing changes).

    2. SAFE — per-scan cost circuit-breaker. Once a scan's tracked vendor
       spend crosses ``settings.scan_cost_cap_usd`` the per-image pipeline
       short-circuits instead of making more Opus calls.

    3. EXPERIMENTAL (default OFF) — ``match_image_against_assets`` compares
       one discovered image against ALL assets in a single cached Opus call,
       and ``process_discovered_image`` routes to it only when
       ``settings.enable_multi_asset_matching`` is True.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services import ai_service, cost_tracker, scan_runners
from app.models import ImageFilterResult, ComplianceCheckResult


# ---------------------------------------------------------------------------
# 1) Cost tracker cap mechanics
# ---------------------------------------------------------------------------

def test_tracker_cap_disabled_never_trips():
    t = cost_tracker.ScanCostTracker("job", cost_cap_usd=0)
    # $50 of Opus input but the cap is disabled (0) — must not trip.
    t.record_anthropic("claude-opus-4-6", input_tokens=10_000_000, output_tokens=0)
    assert t.cap_exceeded is False


def test_tracker_cap_trips_and_latches():
    t = cost_tracker.ScanCostTracker("job", cost_cap_usd=1.0)
    assert t.cap_exceeded is False
    # 1M Opus input tokens @ $5/MTok = $5.00 > $1.00 cap.
    t.record_anthropic("claude-opus-4-6", input_tokens=1_000_000, output_tokens=0)
    assert t.total_usd >= 1.0
    assert t.cap_exceeded is True
    # Latches: still tripped on subsequent checks.
    assert t.cap_exceeded is True


def test_context_helpers_reflect_active_tracker():
    # No tracker bound to the context yet.
    assert cost_tracker.cap_exceeded() is False
    assert cost_tracker.current_total_usd() == 0.0

    with cost_tracker.scan_cost_context("job", cost_cap_usd=0.01) as t:
        assert cost_tracker.cap_exceeded() is False
        t.record_anthropic("claude-opus-4-6", input_tokens=1_000_000, output_tokens=0)
        assert cost_tracker.current_total_usd() >= 5.0
        assert cost_tracker.cap_exceeded() is True

    # Unbound again after the context exits.
    assert cost_tracker.cap_exceeded() is False


# ---------------------------------------------------------------------------
# 2) Circuit-breaker short-circuits the per-image pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_single_image_short_circuits_when_capped():
    stats: dict = {}
    image = {
        "id": "img-1",
        "image_url": "https://example.test/y.png",
        "source_type": "extracted_image",
        "channel": "website",
        "metadata": {},
    }
    with cost_tracker.scan_cost_context("job", cost_cap_usd=0.01) as t:
        t.record_anthropic("claude-opus-4-6", input_tokens=1_000_000, output_tokens=0)
        assert cost_tracker.cap_exceeded() is True
        with patch.object(ai_service, "process_discovered_image", AsyncMock()) as pdi:
            res = await scan_runners._analyze_single_image(
                image, [], {}, None, "job", {}, {}, stats,
            )

    assert res is None
    assert stats.get("cost_capped") == 1
    pdi.assert_not_called()


# ---------------------------------------------------------------------------
# 3) SAFE — compare_images requests prompt caching (result-preserving)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compare_images_requests_prompt_caching():
    captured: dict = {}

    async def fake_call(prompt, images, model=None, cache_prefix_images=0, **kw):
        captured["cache_prefix_images"] = cache_prefix_images
        captured["n_images"] = len(images)
        return '{"similarity_score": 80, "is_match": true, "match_type": "strong", "modifications": []}'

    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"raw")), \
         patch.object(ai_service, "optimize_image_for_api", lambda b, t: b"opt"), \
         patch.object(ai_service, "call_anthropic_with_retry", AsyncMock(side_effect=fake_call)):
        out = await ai_service.compare_images("asset.png", "disc.png")

    # The leading asset image must be marked as the cacheable prefix.
    assert captured["cache_prefix_images"] == 1
    assert captured["n_images"] == 2
    # Output is unchanged — caching only affects billing.
    assert out["similarity_score"] == 80


# ---------------------------------------------------------------------------
# 4) EXPERIMENTAL — multi-asset single-call matcher
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_match_image_against_assets_builds_best_match_and_caches_all_assets():
    assets = [
        {"id": "a1", "file_url": "u1", "name": "A1"},
        {"id": "a2", "file_url": "u2", "name": "A2"},
        {"id": "a3", "file_url": "u3", "name": "A3"},
    ]
    captured: dict = {}

    async def fake_call(prompt, images, model=None, cache_prefix_images=0, **kw):
        captured["cache_prefix_images"] = cache_prefix_images
        captured["n_images"] = len(images)
        return (
            '{"best_match_index": 2, "similarity_score": 88, "is_match": true, '
            '"modifications": ["resized"], "analysis": "ok"}'
        )

    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"raw")), \
         patch.object(ai_service, "optimize_image_for_api", lambda b, t: b"opt"), \
         patch.object(ai_service, "call_anthropic_with_retry", AsyncMock(side_effect=fake_call)):
        best_match, score = await ai_service.match_image_against_assets(assets, "disc.png")

    assert score == 88
    # best_match_index 2 (1-based) -> the second asset.
    assert best_match["asset"]["id"] == "a2"
    assert best_match["comparison"]["match_type"] == "strong"
    # ALL assets form the cached prefix; the discovered image is the suffix.
    assert captured["cache_prefix_images"] == 3
    assert captured["n_images"] == 4


@pytest.mark.asyncio
async def test_match_image_against_assets_index_zero_is_no_match():
    assets = [{"id": "a1", "file_url": "u1"}, {"id": "a2", "file_url": "u2"}]

    async def fake_call(prompt, images, model=None, cache_prefix_images=0, **kw):
        return '{"best_match_index": 0, "similarity_score": 0, "is_match": false}'

    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"raw")), \
         patch.object(ai_service, "optimize_image_for_api", lambda b, t: b"opt"), \
         patch.object(ai_service, "call_anthropic_with_retry", AsyncMock(side_effect=fake_call)):
        best_match, score = await ai_service.match_image_against_assets(assets, "disc.png")

    assert best_match is None
    assert score == 0


# ---------------------------------------------------------------------------
# 5) Flag routing in process_discovered_image
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_discovered_image_uses_multi_asset_when_flag_on():
    assets = [
        {"id": "a1", "file_url": "u1", "name": "A1"},
        {"id": "a2", "file_url": "u2", "name": "A2"},
    ]
    fake_best = (
        {
            "asset": assets[1],
            "comparison": {
                "similarity_score": 92,
                "is_match": True,
                "match_type": "exact",
                "method_scores": {"visual": 92, "detection": 0, "hash": 0},
                "modifications": [],
                "analysis": "",
            },
        },
        92,
    )
    fake_filter = ImageFilterResult(is_relevant=True, confidence=0.99, reason="ok")
    compliance = ComplianceCheckResult(
        is_compliant=True, issues=[], brand_elements={},
        asset_visible=True, zombie_ad=False, zombie_days=None,
        analysis_summary="",
    )

    with patch.object(ai_service.settings, "enable_multi_asset_matching", True), \
         patch.object(ai_service, "download_image", AsyncMock(return_value=b"img")), \
         patch.object(ai_service, "filter_image", AsyncMock(return_value=fake_filter)), \
         patch.object(ai_service, "match_image_against_assets", AsyncMock(return_value=fake_best)) as mm, \
         patch.object(ai_service, "ensemble_match", AsyncMock()) as em, \
         patch.object(ai_service, "should_verify_match", AsyncMock(return_value=False)), \
         patch.object(ai_service, "calibrate_confidence", AsyncMock(side_effect=lambda s, *a, **k: s)), \
         patch.object(ai_service, "analyze_compliance", AsyncMock(return_value=compliance)), \
         patch.object(ai_service, "get_adaptive_threshold", AsyncMock(return_value=(60, {"confidence": "high"}))):
        result, stage = await ai_service.process_discovered_image(
            "img-1", "https://example.test/d.png", assets, brand_rules={},
            source_type="extracted_image", channel="website",
            asset_hashes_cache=None, asset_embeddings_cache=None,
        )

    assert stage == "matched"
    assert result["asset_id"] == "a2"
    mm.assert_awaited_once()
    em.assert_not_called()


@pytest.mark.asyncio
async def test_process_discovered_image_uses_ensemble_when_flag_off():
    """Default OFF: the legacy per-asset ensemble path is used, even with
    multiple assets, and the experimental matcher is never called."""
    assets = [{"id": "a1", "file_url": "u1"}, {"id": "a2", "file_url": "u2"}]
    fake_ensemble = {
        "similarity_score": 0, "is_match": False, "match_type": "none",
        "method_scores": {}, "modifications": [], "analysis": "",
    }
    fake_filter = ImageFilterResult(is_relevant=True, confidence=0.9, reason="ok")

    with patch.object(ai_service.settings, "enable_multi_asset_matching", False), \
         patch.object(ai_service, "download_image", AsyncMock(return_value=b"img")), \
         patch.object(ai_service, "filter_image", AsyncMock(return_value=fake_filter)), \
         patch.object(ai_service, "match_image_against_assets", AsyncMock()) as mm, \
         patch.object(ai_service, "ensemble_match", AsyncMock(return_value=fake_ensemble)) as em, \
         patch.object(ai_service, "get_adaptive_threshold", AsyncMock(return_value=(60, {"confidence": "high"}))):
        result, stage = await ai_service.process_discovered_image(
            "img-2", "https://example.test/d.png", assets, brand_rules={},
            source_type="extracted_image", channel="website",
            asset_hashes_cache=None, asset_embeddings_cache=None,
        )

    assert stage == "below_threshold"
    assert result is None
    em.assert_awaited()
    mm.assert_not_called()
