"""Verification runner.

Exercises ``ai_service.verify_borderline_match`` — the boolean-gate
second pass that decides whether a borderline detection score (60-80)
should be promoted to a confirmed match or rejected.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..manifest import FixtureCase
from .base import BaseRunner

log = logging.getLogger("eval.verify")


class VerifyRunner(BaseRunner):
    name = "verify"
    model_attr = "ENSEMBLE_MODEL"

    def relevant_categories(self) -> List[str]:
        # The verifier only runs on borderline scores in production,
        # so we limit the eval to the same.
        return ["borderline_true", "borderline_false"]

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
            # Initial score 70 is the canonical borderline value.  In
            # production it comes from the detector; for the eval we fix
            # it so ``verify`` outputs are diff-stable across runs.
            result = await ai_service.verify_borderline_match(
                fake_asset_url, fake_discovered_url, initial_score=70,
            )
        finally:
            ai_service.download_image = original_download  # type: ignore[assignment]

        return {
            "is_match": bool(result.get("is_match", False)),
            "score": int(result.get("verified_score", 0) or 0),
            "extras": {
                "gates": result.get("gates", {}),
                "gates_passed": result.get("gates_passed", 0),
                "verdict": result.get("verdict", "")[:200],
            },
        }
