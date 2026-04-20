"""Haiku relevance-filter runner.

Exercises ``ai_service.filter_image`` against fixtures that have an
``is_relevant`` expectation.  Stage 3 of the production pipeline — runs
on every image that survives the hash + CLIP gates, so any quality
regression here multiplies across the entire scan volume.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..manifest import FixtureCase
from .base import BaseRunner

log = logging.getLogger("eval.haiku_filter")


class HaikuFilterRunner(BaseRunner):
    name = "haiku_filter"
    model_attr = "FILTER_MODEL"

    def relevant_categories(self) -> List[str]:
        # The Haiku filter must let through everything that could possibly
        # be a match (high recall) — so we test it against the positives
        # *and* the obvious negatives.  Borderline cases are explicitly
        # excluded because the filter isn't supposed to make a verdict on
        # them; that's the verifier's job.
        return [
            "clear_positive",
            "template_positive",
            "modified_positive",
            "same_promo_diff_creative",  # filter should still pass these
            "same_brand_diff_campaign",
            "different_brand",
        ]

    async def execute_case(self, case: FixtureCase) -> Dict[str, Any]:
        from app.services import ai_service

        # Use the real production code path but with bytes loaded from disk.
        # We patch ``download_image`` for the duration of the call so the
        # test never touches the network.
        from ..config import load_config
        cfg = load_config()
        asset_bytes = case.asset_bytes(cfg.fixtures_dir)
        discovered_bytes = case.discovered_bytes(cfg.fixtures_dir)

        # Stub URLs — the real ones are unused once download_image is patched.
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
            result = await ai_service.filter_image(
                fake_discovered_url, asset_urls=[fake_asset_url],
            )
        finally:
            ai_service.download_image = original_download  # type: ignore[assignment]

        return {
            "is_relevant": bool(result.is_relevant),
            "extras": {
                "confidence": float(getattr(result, "confidence", 0) or 0),
                "reason": getattr(result, "reason", "")[:200],
            },
        }
