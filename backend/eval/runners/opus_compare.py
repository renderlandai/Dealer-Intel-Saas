"""Regular-image comparison runner.

Exercises ``ai_service.ensemble_match(..., is_screenshot=False)`` — the
production Stage-4 path for *extracted images* (non-screenshots). This is
the 1:1 per-asset comparison that combines ``compare_images`` (Opus visual)
with ``compare_with_hash`` (perceptual hash) and applies the hash-veto.

Until now the eval harness only covered the *screenshot* detection path
(``opus_detect``); the regular-image path — which is the dominant production
code path for website/extracted creatives and the one prompt caching was
added to — had no eval coverage. This runner closes that gap so a change to
``compare_images`` / ``ensemble_match`` is gated on recall/precision the same
way ``opus_detect`` is.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..manifest import FixtureCase
from .base import BaseRunner, fixture_downloads

log = logging.getLogger("eval.opus_compare")


class OpusCompareRunner(BaseRunner):
    name = "opus_compare"
    model_attr = "ENSEMBLE_MODEL"

    def relevant_categories(self) -> List[str]:
        # Same matching categories as opus_detect: every case that should
        # produce a meaningful same-creative / not-same-creative verdict.
        return [
            "clear_positive",
            "template_positive",
            "modified_positive",
            "same_promo_diff_creative",
            "same_brand_diff_campaign",
            "different_brand",
            "borderline_true",
            "borderline_false",
        ]

    async def execute_case(self, case: FixtureCase) -> Dict[str, Any]:
        from app.services import ai_service

        from ..config import load_config
        cfg = load_config()
        asset_bytes = case.asset_bytes(cfg.fixtures_dir)
        discovered_bytes = case.discovered_bytes(cfg.fixtures_dir)

        fake_asset_url = f"eval://asset/{case.id}"
        fake_discovered_url = f"eval://discovered/{case.id}"
        url_to_bytes = {
            fake_asset_url: asset_bytes,
            fake_discovered_url: discovered_bytes,
        }

        with fixture_downloads(url_to_bytes):
            result = await ai_service.ensemble_match(
                fake_asset_url, fake_discovered_url, is_screenshot=False,
            )

        return {
            "is_match": bool(result.get("is_match", False)),
            "score": int(result.get("similarity_score", 0) or 0),
            "extras": {
                "match_type": result.get("match_type", "none"),
                "method_scores": result.get("method_scores", {}),
                "modifications": result.get("modifications", [])[:5],
            },
        }
