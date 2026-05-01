"""Phase 6.5.4 — AI service diagnostics + BD direct-first probe tests.

Covers the three regression-fixes from the BD-vs-direct accuracy
investigation (log.md 2026-05-01):

1. ``_classify_claude_error`` buckets exception messages so the funnel
   can distinguish rate-limit / timeout / parse failures from "Claude
   said no".
2. ``compare_images`` and ``detect_asset_in_screenshot`` annotate every
   failure with ``error_kind`` so the ensemble caller can propagate it
   up to ``process_discovered_image``.
3. ``process_discovered_image`` returns ``(result, stage, diagnostics)``
   — the third element carries best_score, best_asset_id, threshold,
   and aggregate Claude-error counts, so an operator can post-mortem
   any below-threshold image without re-running the pipeline.
4. ``process_discovered_image`` returns the ``"claude_error"`` stage
   when *every* comparison errored — preserves the funnel signal that
   was previously masked as plain "below_threshold".
5. ``ai_service.download_image`` on a BD-unlocked host now tries a
   short direct httpx fetch FIRST and only falls back to BD on
   failure. This recovers the original master image bytes when the
   asset CDN happens to be open, which Claude scores meaningfully
   higher than BD's re-encoded edge rendition.

No real Anthropic / Bright Data calls — every external dependency
is patched.
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


def _png_bytes(size=(20, 20), color=(255, 0, 0)) -> bytes:
    """Build a tiny valid PNG so PIL's ``verify()`` says yes."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _classify_claude_error
# ---------------------------------------------------------------------------

class TestClassifyClaudeError:
    def test_rate_limit_buckets(self):
        from app.services.ai_service import _classify_claude_error
        assert _classify_claude_error(Exception("HTTP 429 rate_limit_error")) == "rate_limit"
        assert _classify_claude_error(Exception("rate limit exceeded")) == "rate_limit"
        assert _classify_claude_error(Exception("quota exhausted for org")) == "rate_limit"

    def test_timeout_bucket(self):
        from app.services.ai_service import _classify_claude_error
        assert _classify_claude_error(Exception("Read timed out after 30s")) == "timeout"
        assert _classify_claude_error(Exception("anthropic timeout")) == "timeout"

    def test_overloaded_bucket(self):
        from app.services.ai_service import _classify_claude_error
        assert _classify_claude_error(Exception("503 service unavailable")) == "overloaded"
        assert _classify_claude_error(Exception("Anthropic API overloaded")) == "overloaded"

    def test_json_parse_bucket(self):
        from app.services.ai_service import _classify_claude_error
        assert _classify_claude_error(Exception("Could not parse JSON")) == "json_parse"
        assert _classify_claude_error(Exception("json decode error at line 1")) == "json_parse"

    def test_network_bucket(self):
        from app.services.ai_service import _classify_claude_error
        assert _classify_claude_error(Exception("Connection reset by peer")) == "network"

    def test_other_bucket_for_unknown_messages(self):
        from app.services.ai_service import _classify_claude_error
        assert _classify_claude_error(Exception("Something exotic happened")) == "other"


# ---------------------------------------------------------------------------
# compare_images error annotation
# ---------------------------------------------------------------------------

class TestCompareImagesErrorAnnotation:
    def test_anthropic_failure_returns_error_kind(self):
        """A 429 from call_anthropic_with_retry must surface as
        error_kind=rate_limit so the funnel can report it."""
        from app.services import ai_service

        with patch.object(ai_service, "download_image", new=AsyncMock(return_value=_png_bytes())), \
             patch.object(ai_service, "call_anthropic_with_retry",
                          new=AsyncMock(side_effect=Exception("HTTP 429 rate limit"))):
            result = _run(ai_service.compare_images("https://x/a.png", "https://x/b.png"))

        assert result["similarity_score"] == 0
        assert result["is_match"] is False
        assert result["error_kind"] == "rate_limit"
        assert "rate" in result["error"].lower()

    def test_json_parse_failure_returns_error_kind(self):
        """Claude returning unparseable text must surface as
        error_kind=json_parse — distinct from a real "no" verdict."""
        from app.services import ai_service

        with patch.object(ai_service, "download_image", new=AsyncMock(return_value=_png_bytes())), \
             patch.object(ai_service, "call_anthropic_with_retry",
                          new=AsyncMock(return_value="not even close to json {[")):
            result = _run(ai_service.compare_images("https://x/a.png", "https://x/b.png"))

        assert result["similarity_score"] == 0
        assert result["error_kind"] == "json_parse"

    def test_image_optimize_failure_returns_error_kind(self):
        """When the source image isn't decodable, return image_optimize
        — that's a real bug worth seeing in the funnel separately
        from a Claude failure."""
        from app.services import ai_service

        with patch.object(ai_service, "download_image", new=AsyncMock(return_value=b"not an image")):
            result = _run(ai_service.compare_images("https://x/a.png", "https://x/b.png"))

        assert result["similarity_score"] == 0
        assert result["error_kind"] == "image_optimize"

    def test_success_path_sets_error_kind_to_none(self):
        """Healthy comparison: error_kind must be present and None
        so callers can rely on the key existing."""
        from app.services import ai_service

        ok_response = '{"similarity_score": 92, "is_match": true, "match_type": "exact", "modifications": []}'
        with patch.object(ai_service, "download_image", new=AsyncMock(return_value=_png_bytes())), \
             patch.object(ai_service, "call_anthropic_with_retry",
                          new=AsyncMock(return_value=ok_response)):
            result = _run(ai_service.compare_images("https://x/a.png", "https://x/b.png"))

        assert result["similarity_score"] == 92
        assert result["error_kind"] is None


# ---------------------------------------------------------------------------
# ensemble_match propagates error_kind
# ---------------------------------------------------------------------------

class TestEnsembleMatchErrorPropagation:
    def test_visual_rate_limit_surfaces_in_ensemble_result(self):
        """For a non-screenshot ensemble call, a rate-limited
        compare_images() result must surface in the ensemble dict so
        process_discovered_image can bucket it as claude_error."""
        from app.services import ai_service

        async def fake_compare(*_a, **_k):
            return {
                "similarity_score": 0, "is_match": False,
                "match_type": "none", "modifications": [],
                "error": "HTTP 429", "error_kind": "rate_limit",
            }

        async def fake_hash(*_a, **_k):
            return {"similarity_score": 0, "is_exact": False}

        with patch.object(ai_service, "compare_images", new=fake_compare), \
             patch.object(ai_service, "compare_with_hash", new=fake_hash):
            result = _run(ai_service.ensemble_match(
                "https://x/asset.png", "https://x/disc.png",
                is_screenshot=False,
            ))

        assert result["error_kind"] == "rate_limit"
        assert result["similarity_score"] == 0


# ---------------------------------------------------------------------------
# process_discovered_image diagnostics
# ---------------------------------------------------------------------------

class TestProcessDiscoveredImageDiagnostics:
    """The funnel must surface (a) best score, (b) best asset id, and
    (c) Claude-error counts for every non-matched image — that's the
    forensic evidence the operator needs to root-cause a "0 matches"
    scan without re-running it."""

    def _setup_passthrough_filter(self, ai_service):
        """Make the early-exit gates pass so we exercise the ensemble
        loop where the diagnostics actually get populated."""
        # Hash + CLIP pre-filters: always pass.
        patches = [
            patch.object(ai_service, "_passes_hash_prefilter",
                         new=AsyncMock(return_value=True)),
            patch.object(ai_service, "_passes_clip_prefilter",
                         new=AsyncMock(return_value=True)),
            patch.object(ai_service, "filter_image",
                         new=AsyncMock(return_value=MagicMock(
                             is_relevant=True, confidence=0.9))),
            patch.object(ai_service, "get_adaptive_threshold",
                         new=AsyncMock(return_value=(60, {"confidence": "high"}))),
            patch.object(ai_service, "should_verify_match",
                         new=AsyncMock(return_value=False)),
            patch.object(ai_service, "download_image",
                         new=AsyncMock(return_value=_png_bytes())),
        ]
        for p in patches:
            p.start()
        return patches

    def _teardown(self, patches):
        for p in patches:
            p.stop()

    def test_below_threshold_returns_diagnostics_with_best_score(self):
        """When the best ensemble score is real but below threshold,
        diagnostics must carry the score and the asset that produced
        it — the operator needs to know "Claude evaluated this and
        scored it 52" not just "below_threshold."""
        from app.services import ai_service

        patches = self._setup_passthrough_filter(ai_service)
        try:
            async def fake_ensemble(*_a, **_k):
                return {
                    "similarity_score": 52, "is_match": False,
                    "asset_found": False, "match_type": "weak",
                    "method_scores": {"visual": 52, "detection": 0, "hash": 50},
                    "modifications": [], "analysis": "",
                    "error_kind": None, "error": None,
                }
            with patch.object(ai_service, "ensemble_match", new=fake_ensemble):
                result, stage, diag = _run(ai_service.process_discovered_image(
                    discovered_image_id="img-1",
                    image_url="https://x/disc.png",
                    campaign_assets=[{"id": "asset-1", "file_url": "https://x/a.png"}],
                    brand_rules={},
                ))

            assert result is None
            assert stage == "below_threshold"
            assert diag["best_score"] == 52
            assert diag["best_asset_id"] == "asset-1"
            assert diag["threshold"] == 60
            assert diag["had_claude_error"] is False
            assert diag["all_comparisons_errored"] is False
        finally:
            self._teardown(patches)

    def test_all_claude_errors_returns_claude_error_stage(self):
        """When every ensemble call errored (e.g. global rate-limit),
        bucket as claude_error so the funnel doesn't silently report
        the resulting zero as "below_threshold = real mismatch"."""
        from app.services import ai_service

        patches = self._setup_passthrough_filter(ai_service)
        try:
            async def fake_ensemble(*_a, **_k):
                return {
                    "similarity_score": 0, "is_match": False,
                    "asset_found": False, "match_type": "none",
                    "method_scores": {"visual": 0, "detection": 0, "hash": 0},
                    "modifications": [], "analysis": "",
                    "error_kind": "rate_limit",
                    "error": "HTTP 429",
                }
            with patch.object(ai_service, "ensemble_match", new=fake_ensemble):
                result, stage, diag = _run(ai_service.process_discovered_image(
                    discovered_image_id="img-1",
                    image_url="https://x/disc.png",
                    campaign_assets=[
                        {"id": "asset-1", "file_url": "https://x/a.png"},
                        {"id": "asset-2", "file_url": "https://x/b.png"},
                    ],
                    brand_rules={},
                ))

            assert result is None
            assert stage == "claude_error"
            assert diag["all_comparisons_errored"] is True
            assert diag["had_claude_error"] is True
            assert diag["claude_error_kinds"] == ["rate_limit", "rate_limit"]
        finally:
            self._teardown(patches)

    def test_partial_claude_errors_still_match_on_healthy_asset(self):
        """If one comparison errors but another scores high, the
        match must still happen AND the diagnostics must still record
        the partial Claude failure for the operator."""
        from app.services import ai_service

        patches = self._setup_passthrough_filter(ai_service)
        try:
            call_count = {"n": 0}
            async def fake_ensemble(*_a, **_k):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return {
                        "similarity_score": 0, "is_match": False,
                        "asset_found": False, "match_type": "none",
                        "method_scores": {}, "modifications": [], "analysis": "",
                        "error_kind": "timeout", "error": "timed out",
                    }
                return {
                    "similarity_score": 88, "is_match": True,
                    "asset_found": True, "match_type": "strong",
                    "method_scores": {"visual": 88, "detection": 0, "hash": 85},
                    "modifications": [], "analysis": "",
                    "error_kind": None, "error": None,
                }

            with patch.object(ai_service, "ensemble_match", new=fake_ensemble), \
                 patch.object(ai_service, "calibrate_confidence",
                              new=AsyncMock(return_value=88)), \
                 patch.object(ai_service, "analyze_compliance",
                              new=AsyncMock(return_value=MagicMock(
                                  is_compliant=True, issues=[], brand_elements=[],
                                  zombie_ad=False, analysis_summary=""))):
                result, stage, diag = _run(ai_service.process_discovered_image(
                    discovered_image_id="img-1",
                    image_url="https://x/disc.png",
                    campaign_assets=[
                        {"id": "asset-1", "file_url": "https://x/a.png"},
                        {"id": "asset-2", "file_url": "https://x/b.png"},
                    ],
                    brand_rules={},
                ))

            assert stage == "matched"
            assert result is not None
            assert result["asset_id"] == "asset-2"
            # Diagnostics still surface that one comparison failed.
            assert diag["had_claude_error"] is True
            assert diag["all_comparisons_errored"] is False
            assert "timeout" in diag["claude_error_kinds"]
        finally:
            self._teardown(patches)

    def test_download_failed_carries_diagnostics_too(self):
        """Even on the earliest reject path the caller gets a
        diagnostics dict — never a 2-tuple, because the scan_runners
        unpacker assumes 3 elements."""
        from app.services import ai_service

        with patch.object(ai_service, "download_image",
                          new=AsyncMock(side_effect=Exception("404 not found"))):
            result, stage, diag = _run(ai_service.process_discovered_image(
                discovered_image_id="img-1",
                image_url="https://x/disc.png",
                campaign_assets=[{"id": "asset-1", "file_url": "https://x/a.png"}],
                brand_rules={},
            ))

        assert result is None
        assert stage == "download_failed"
        assert isinstance(diag, dict)
        assert "404" in diag["download_error"]


# ---------------------------------------------------------------------------
# download_image — direct-first probe on BD-unlocked hosts
# ---------------------------------------------------------------------------

class TestUnlockedHostDirectFirstProbe:
    """When a host has been marked as Bright-Data-unlocked, an asset
    fetch must try direct httpx FIRST. Direct returns the original
    master bytes; BD often returns a re-encoded edge rendition that
    Claude scores meaningfully lower."""

    def setup_method(self):
        from app.services import unlocker_service, ai_service
        unlocker_service._unlocked_hosts.clear()
        ai_service.clear_image_cache()

    def test_direct_success_skips_bright_data_entirely(self):
        from app.services import ai_service, unlocker_service

        unlocker_service.mark_host_unlocked("https://rent.cat.com/")
        png = _png_bytes()

        bd_mock = AsyncMock(return_value=b"BD WOULD HAVE RETURNED THIS")
        direct_mock = AsyncMock(return_value=png)

        with patch.object(ai_service, "_try_direct_image_fetch", new=direct_mock), \
             patch.object(unlocker_service, "download_via_unlocker", new=bd_mock):
            body = _run(ai_service.download_image("https://rent.cat.com/dam/hero.png"))

        assert body == png
        direct_mock.assert_awaited_once()
        # The whole point: BD was never called when direct succeeded.
        bd_mock.assert_not_awaited()

    def test_direct_failure_falls_back_to_bright_data(self):
        from app.services import ai_service, unlocker_service

        unlocker_service.mark_host_unlocked("https://rent.cat.com/")
        bd_png = _png_bytes(color=(0, 255, 0))

        with patch.object(ai_service, "_try_direct_image_fetch",
                          new=AsyncMock(return_value=None)), \
             patch.object(unlocker_service, "download_via_unlocker",
                          new=AsyncMock(return_value=bd_png)):
            body = _run(ai_service.download_image("https://rent.cat.com/dam/hero.png"))

        # Got the BD bytes — this is the legacy WAF-protected path
        # working exactly as before.
        assert body == bd_png

    def test_unmarked_host_still_uses_plain_direct_path(self):
        """A host that was NEVER unlocked must not invoke either the
        probe OR Bright Data — it goes straight through the
        non-BD direct httpx client."""
        from app.services import ai_service, unlocker_service

        png = _png_bytes()

        async def fake_get(*_a, **_k):
            resp = MagicMock()
            resp.content = png
            resp.headers = {"content-type": "image/png"}
            resp.raise_for_status = MagicMock()
            return resp

        with patch.object(ai_service, "_try_direct_image_fetch") as probe, \
             patch.object(unlocker_service, "download_via_unlocker") as bd, \
             patch("httpx.AsyncClient") as client_cls:
            client_instance = MagicMock()
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            client_instance.get = AsyncMock(side_effect=fake_get)
            client_cls.return_value = client_instance

            body = _run(ai_service.download_image("https://normal-dealer.com/banner.png"))

        assert body == png
        probe.assert_not_called()
        bd.assert_not_called()

    def test_direct_probe_returns_none_on_timeout(self):
        """The probe itself must never raise — it has to return None
        on every failure mode so the caller can fall back cleanly."""
        from app.services import ai_service
        import httpx

        with patch("httpx.AsyncClient") as client_cls:
            client_instance = MagicMock()
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            client_instance.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            client_cls.return_value = client_instance

            body = _run(ai_service._try_direct_image_fetch("https://x/y.png"))

        assert body is None

    def test_direct_probe_returns_none_on_non_image_response(self):
        from app.services import ai_service

        async def fake_get(*_a, **_k):
            resp = MagicMock()
            resp.content = b"<html>i am a 200 OK challenge page</html>"
            resp.raise_for_status = MagicMock()
            return resp

        with patch("httpx.AsyncClient") as client_cls:
            client_instance = MagicMock()
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            client_instance.get = AsyncMock(side_effect=fake_get)
            client_cls.return_value = client_instance

            body = _run(ai_service._try_direct_image_fetch("https://x/y.png"))

        assert body is None
