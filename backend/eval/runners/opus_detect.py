"""Opus detection runner.

Exercises ``ai_service.detect_asset_in_screenshot`` (which fans out to
either ``_detect_asset_single`` or ``_detect_asset_tiled`` depending on
the ``enable_tiling_fallback`` setting).  Stage 4 of the production
pipeline — this is where the per-asset confidence score is produced.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..manifest import FixtureCase
from .base import BaseRunner

log = logging.getLogger("eval.opus_detect")


class OpusDetectRunner(BaseRunner):
    name = "opus_detect"
    model_attr = "ENSEMBLE_MODEL"

    def relevant_categories(self) -> List[str]:
        # Run detection on everything that should produce a meaningful
        # match verdict.  Excludes pure relevance-filter cases where the
        # discovered image is so off-topic that detection wouldn't even
        # be invoked in production.
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

        original_download = ai_service.download_image

        async def _patched_download(url: str) -> bytes:
            if url in url_to_bytes:
                return url_to_bytes[url]
            return await original_download(url)

        ai_service.download_image = _patched_download  # type: ignore[assignment]
        try:
            result = await ai_service.detect_asset_in_screenshot(
                fake_asset_url, fake_discovered_url,
            )
        finally:
            ai_service.download_image = original_download  # type: ignore[assignment]

        return {
            "is_match": bool(result.get("is_match", False)),
            "score": int(result.get("similarity_score", 0) or 0),
            "extras": {
                "match_type": result.get("match_type", "none"),
                "modifications": result.get("modifications", [])[:5],
                "tiles_checked": result.get("tiles_checked"),
            },
        }
