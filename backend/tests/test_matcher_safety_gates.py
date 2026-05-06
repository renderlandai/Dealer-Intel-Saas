"""Regression tests for the 2026-05-06 matcher safety gates.

These exercise the four safety nets that were missing or too loose
when the operator caught the system publishing 80% STRONG MATCHES on
navigation-bar crops:

    1. ``cv_matching.find_asset_on_page`` template threshold tightened
       from 0.40 -> 0.70 and feature ``min_good_matches`` from 8 -> 18.
       A black "SUPPORT  ABOUT" navigation strip rendered at the top
       of an unrelated page must not produce a CV bounding box against
       a busy product creative.

    2. ``ai_service._passes_hash_prefilter`` honours a strict mode for
       CV-localized crops. The same hash that passes the loose default
       (28) gate must fail the strict (16) gate.

    3. ``ai_service._passes_clip_prefilter`` honours a strict mode for
       CV-localized crops. Same idea — the strict threshold (0.55) is
       lifted above the default (0.40).

    4. ``ai_service.process_discovered_image`` rejects a match when
       compliance returns ``asset_visible: False`` even after a
       (hallucinated) high visual score gets through every other gate.
       This is the single most important post-mortem learning: ALL
       previous layers can be bypassed by a confident-but-wrong Opus
       call, and asset_visible was the safety net that caught those.

    5. ``ai_service.verify_borderline_match`` uses the new compressed
       gate-score curve so that 4-of-5 gates lands at 65 (PARTIAL),
       not 80 (STRONG). 5-of-5 gates lands at 80 (STRONG), not 100
       (EXACT). And 3 gates returns ``is_match=False``.

    6. ``ai_service.ensemble_match`` applies the hash-veto when the
       visual scorer claims a strong match but perceptual hashing
       disagrees by a wide margin.
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from PIL import Image

from app.services import cv_matching, ai_service
from app.models import ImageFilterResult, ComplianceCheckResult


# ---------------------------------------------------------------------------
# Image helpers — synthesise the operator's actual failure case in code so
# the test can run without any Supabase / Anthropic credentials.
# ---------------------------------------------------------------------------

def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _approved_creative() -> bytes:
    """A "campaign creative" — busy, multi-color, with text and shapes.

    Generated procedurally so the test is deterministic but visually
    distinct from a low-entropy nav bar.
    """
    rng = np.random.default_rng(42)
    arr = rng.integers(40, 220, size=(400, 800, 3), dtype=np.uint8)
    # Stamp a couple of brand-colored bands to add structure.
    arr[60:120, 50:750] = (210, 30, 30)
    arr[260:320, 50:750] = (250, 200, 30)
    return _png_bytes(Image.fromarray(arr))


def _nav_bar_crop() -> bytes:
    """The user's actual failure case — a small dark navigation strip."""
    arr = np.full((50, 320, 3), fill_value=18, dtype=np.uint8)
    # Two brighter rectangles where SUPPORT / ABOUT text would be.
    arr[10:40, 30:130] = 180
    arr[10:40, 170:270] = 180
    return _png_bytes(Image.fromarray(arr))


def _full_page_with_navbar() -> bytes:
    """A "full page" screenshot whose only asset-shaped region is a nav bar."""
    arr = np.full((2400, 1600, 3), fill_value=240, dtype=np.uint8)
    # Dark navigation strip at the top — exactly what fooled the matcher.
    arr[40:120, 200:1400] = 18
    arr[60:100, 280:480] = 180
    arr[60:100, 700:900] = 180
    return _png_bytes(Image.fromarray(arr))


# ---------------------------------------------------------------------------
# 1) cv_matching tightening
# ---------------------------------------------------------------------------

def test_find_asset_on_page_rejects_navbar_against_creative():
    """A dark nav-bar crop must NOT be reported as 'found' against a busy
    multi-color campaign creative. This is the operator's exact bad path.
    """
    matches = cv_matching.find_asset_on_page(
        screenshot_bytes=_full_page_with_navbar(),
        asset_bytes=_approved_creative(),
    )
    assert matches == [], (
        "CV matcher returned a bounding box where there is no real match. "
        "Threshold is too permissive — see cv_matching.template_match."
    )


def test_find_asset_on_page_default_thresholds_are_strict():
    """Belt-and-braces — even if a future refactor accidentally loosens
    `find_asset_on_page`'s defaults, this test pins the contract."""
    import inspect
    sig = inspect.signature(cv_matching.find_asset_on_page)
    assert sig.parameters["template_threshold"].default >= 0.70
    assert sig.parameters["feature_min_matches"].default >= 18

    sig_t = inspect.signature(cv_matching.template_match)
    assert sig_t.parameters["threshold"].default >= 0.70

    sig_f = inspect.signature(cv_matching.feature_match)
    assert sig_f.parameters["min_good_matches"].default >= 18


# ---------------------------------------------------------------------------
# 2) Strict prefilters for CV-localized crops
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hash_prefilter_strict_mode_rejects_loose_match():
    """A discovered-image hash that differs by ~22 bits passes the loose
    (28) gate but must fail the strict (16) gate used for CV crops."""
    asset_hashes = {
        "phash": _FakeHash(0),
        "dhash": _FakeHash(0),
        "whash": _FakeHash(0),
        "average_hash": _FakeHash(0),
    }
    discovered_hashes = {
        "phash": _FakeHash(22),
        "dhash": _FakeHash(22),
        "whash": _FakeHash(22),
        "average_hash": _FakeHash(22),
    }

    with patch.object(
        ai_service, "compute_image_hashes",
        AsyncMock(return_value=discovered_hashes),
    ):
        loose = await ai_service._passes_hash_prefilter(
            b"img", [asset_hashes], strict=False,
        )
        strict = await ai_service._passes_hash_prefilter(
            b"img", [asset_hashes], strict=True,
        )
    assert loose is True
    assert strict is False


@pytest.mark.asyncio
async def test_clip_prefilter_strict_mode_rejects_loose_similarity():
    fake_emb = object()
    with patch.object(
        ai_service.embedding_service,
        "compute_embedding_async",
        AsyncMock(return_value=fake_emb),
    ), patch.object(
        ai_service.embedding_service,
        "best_asset_similarity",
        return_value=0.45,  # passes 0.40, fails 0.55
    ):
        loose = await ai_service._passes_clip_prefilter(
            b"img", [object()], strict=False,
        )
        strict = await ai_service._passes_clip_prefilter(
            b"img", [object()], strict=True,
        )
    assert loose is True
    assert strict is False


# ---------------------------------------------------------------------------
# 3) asset_visible final gate — the post-mortem's #1 finding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_discovered_image_rejects_when_asset_not_visible():
    """A high-confidence match whose compliance check says
    ``asset_visible: False`` must be rejected with stage
    ``asset_invisible_rejected``. This is the safety net that catches
    every other gate's hallucination."""
    asset = {"id": "asset-1", "file_url": "https://example.test/asset.png", "name": "test-asset"}
    campaign_assets = [asset]

    fake_filter = ImageFilterResult(is_relevant=True, confidence=0.99, reason="ok")
    fake_ensemble = {
        "similarity_score": 92,
        "is_match": True,
        "match_type": "strong",
        "method_scores": {"visual": 92, "detection": 0, "hash": 88},
        "modifications": [],
        "analysis": "fake",
    }
    invisible_compliance = ComplianceCheckResult(
        is_compliant=False,
        issues=[],
        brand_elements={},
        asset_visible=False,  # <-- the veto
        zombie_ad=False,
        zombie_days=None,
        analysis_summary="creative not visible — discovered image is webpage chrome",
    )

    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"img")), \
         patch.object(ai_service, "filter_image", AsyncMock(return_value=fake_filter)), \
         patch.object(ai_service, "ensemble_match", AsyncMock(return_value=fake_ensemble)), \
         patch.object(ai_service, "should_verify_match", AsyncMock(return_value=False)), \
         patch.object(ai_service, "calibrate_confidence", AsyncMock(side_effect=lambda s, *a, **k: s)), \
         patch.object(ai_service, "analyze_compliance", AsyncMock(return_value=invisible_compliance)), \
         patch.object(ai_service, "get_adaptive_threshold", AsyncMock(return_value=(60, {"confidence": "high"}))):
        # Pass None for both prefilter caches so the inner _passes_*
        # paths are skipped — they require imagehash machinery we
        # don't need to exercise here. The path under test starts at
        # the Haiku filter and runs to the asset_visible gate.
        result, stage = await ai_service.process_discovered_image(
            "img-1", "https://example.test/discovered.png",
            campaign_assets, brand_rules={},
            source_type="extracted_image", channel="website",
            asset_hashes_cache=None, asset_embeddings_cache=None,
        )

    assert result is None
    assert stage == "asset_invisible_rejected"


@pytest.mark.asyncio
async def test_process_discovered_image_publishes_when_asset_visible_unknown():
    """If the compliance call doesn't return an explicit ``asset_visible``
    value (None), we MUST NOT veto — None means "model didn't populate
    the field" and we should fall through to the existing publishing
    path. This protects against API/model regressions silently dropping
    every match."""
    asset = {"id": "asset-2", "file_url": "https://example.test/asset.png", "name": "x"}
    fake_filter = ImageFilterResult(is_relevant=True, confidence=0.99, reason="ok")
    fake_ensemble = {
        "similarity_score": 90,
        "is_match": True,
        "match_type": "strong",
        "method_scores": {"visual": 90, "detection": 0, "hash": 85},
        "modifications": [],
        "analysis": "",
    }
    unknown_compliance = ComplianceCheckResult(
        is_compliant=True, issues=[], brand_elements={},
        asset_visible=None,  # <-- unknown, NOT a veto
        zombie_ad=False, zombie_days=None,
        analysis_summary="",
    )

    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"img")), \
         patch.object(ai_service, "filter_image", AsyncMock(return_value=fake_filter)), \
         patch.object(ai_service, "ensemble_match", AsyncMock(return_value=fake_ensemble)), \
         patch.object(ai_service, "should_verify_match", AsyncMock(return_value=False)), \
         patch.object(ai_service, "calibrate_confidence", AsyncMock(side_effect=lambda s, *a, **k: s)), \
         patch.object(ai_service, "analyze_compliance", AsyncMock(return_value=unknown_compliance)), \
         patch.object(ai_service, "get_adaptive_threshold", AsyncMock(return_value=(60, {"confidence": "high"}))):
        result, stage = await ai_service.process_discovered_image(
            "img-2", "https://example.test/discovered.png",
            [asset], brand_rules={},
            source_type="extracted_image", channel="website",
            asset_hashes_cache=None, asset_embeddings_cache=None,
        )
    assert stage == "matched"
    assert result is not None
    assert result["asset_id"] == "asset-2"


# ---------------------------------------------------------------------------
# 4) Verifier gate-score compression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_borderline_match_three_gates_no_longer_publishes():
    """Three-of-five gates was a STRONG MATCH at 60 under the old
    `gates_passed * 20` curve and the verifier reported `is_match=true`
    on the first three gates. Today three gates must NOT be a match."""
    fake_resp = '{"gate_brand": true, "gate_product": true, "gate_message": true, "gate_offer": false, "gate_design": false, "gates_passed": 3, "is_match": true, "verdict": "x"}'
    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"img")), \
         patch.object(ai_service, "optimize_image_for_api", lambda b, t: b"opt"), \
         patch.object(ai_service, "call_anthropic_with_retry", AsyncMock(return_value=fake_resp)):
        out = await ai_service.verify_borderline_match(
            "asset.png", "discovered.png", initial_score=70,
        )
    assert out["is_match"] is False
    # 3 gates -> 50 (PARTIAL-band; below regular threshold)
    assert out["verified_score"] == 50


@pytest.mark.asyncio
async def test_verify_borderline_match_four_gates_lands_in_partial():
    """4-of-5 gates was 80 (STRONG) under the broken curve. Now 65 (PARTIAL)."""
    fake_resp = '{"gate_brand": true, "gate_product": true, "gate_message": true, "gate_offer": true, "gate_design": false, "gates_passed": 4, "is_match": true, "verdict": "x"}'
    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"img")), \
         patch.object(ai_service, "optimize_image_for_api", lambda b, t: b"opt"), \
         patch.object(ai_service, "call_anthropic_with_retry", AsyncMock(return_value=fake_resp)):
        out = await ai_service.verify_borderline_match(
            "asset.png", "discovered.png", initial_score=70,
        )
    assert out["is_match"] is True
    assert out["verified_score"] == 65, (
        "4 gates should map to PARTIAL (65), not STRONG (80). Regression "
        "of the gate-score curve will mint phantom STRONG MATCHES."
    )


@pytest.mark.asyncio
async def test_verify_borderline_match_five_gates_is_strong_not_exact():
    fake_resp = '{"gate_brand": true, "gate_product": true, "gate_message": true, "gate_offer": true, "gate_design": true, "gates_passed": 5, "is_match": true, "verdict": "x"}'
    with patch.object(ai_service, "download_image", AsyncMock(return_value=b"img")), \
         patch.object(ai_service, "optimize_image_for_api", lambda b, t: b"opt"), \
         patch.object(ai_service, "call_anthropic_with_retry", AsyncMock(return_value=fake_resp)):
        out = await ai_service.verify_borderline_match(
            "asset.png", "discovered.png", initial_score=78,
        )
    assert out["is_match"] is True
    assert out["verified_score"] == 80


# ---------------------------------------------------------------------------
# 5) Ensemble hash-veto
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ensemble_match_hash_veto_caps_hallucinated_visual():
    """When visual=85 but hash=50, the ensemble MUST cap the final score
    near the hash signal rather than averaging the two. This is what
    keeps a hallucinated Opus visual score from publishing as STRONG."""
    visual_result = {
        "similarity_score": 85,
        "is_match": True,
        "match_type": "strong",
        "modifications": [],
    }
    hash_result = {
        "similarity_score": 50,
        "is_exact": False,
        "is_similar": False,
        "is_related": False,
    }
    with patch.object(ai_service, "compare_images", AsyncMock(return_value=visual_result)), \
         patch.object(ai_service, "compare_with_hash", AsyncMock(return_value=hash_result)):
        out = await ai_service.ensemble_match(
            "asset.png", "discovered.png", is_screenshot=False,
        )
    # hash_score 50 + 10 = 60 cap. (Without the veto we'd have landed
    # near 77 — the regular_image_match_threshold of 60 would have let
    # the publish through, exactly the operator's failure case.)
    assert out["similarity_score"] <= 60, (
        f"Hash-veto failed: final score {out['similarity_score']} exceeded "
        "hash + 10 = 60. Visual hallucination is no longer being capped."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeHash:
    """Mimics imagehash's hash class for arithmetic in tests.

    ``ImageHash.__sub__`` returns the Hamming distance between the two
    binary arrays. Our prefilter only uses subtraction, so we just
    return a configured int — enough for the threshold maths to behave
    exactly as it would on real hashes."""
    def __init__(self, distance_to_zero: int):
        self._d = distance_to_zero

    def __sub__(self, other):  # noqa: D401
        return abs(self._d - getattr(other, "_d", 0))
