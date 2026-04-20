"""Compliance runner.

Exercises ``ai_service.analyze_compliance`` — the deepest stage of the
pipeline, which combines brand-rule checking with zombie-ad detection.
A regression here is the highest-stakes category in the product because
it's what the customer actually pays to detect.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..manifest import FixtureCase
from .base import BaseRunner

log = logging.getLogger("eval.compliance")


class ComplianceRunner(BaseRunner):
    name = "compliance"
    model_attr = "ENSEMBLE_MODEL"

    def relevant_categories(self) -> List[str]:
        return ["compliance_drift", "zombie_ad", "clear_positive", "template_positive"]

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
            result = await ai_service.analyze_compliance(
                discovered_image_url=fake_discovered_url,
                original_asset_url=fake_asset_url,
                brand_rules=case.brand_rules or {},
                campaign_end_date=case.campaign_end_date,
            )
        finally:
            ai_service.download_image = original_download  # type: ignore[assignment]

        return {
            "is_compliant": bool(result.is_compliant),
            "zombie_ad": bool(getattr(result, "zombie_ad", False)),
            "extras": {
                "issue_count": len(result.issues or []),
                "summary": (result.analysis_summary or "")[:200],
            },
        }
