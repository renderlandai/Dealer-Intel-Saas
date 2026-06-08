"""Multi-asset single-call matcher runner (EXPERIMENTAL path).

Exercises ``ai_service.match_image_against_assets`` — the experimental
single-Opus-call matcher gated behind ``settings.enable_multi_asset_matching``.
That path compares ONE discovered image against ALL campaign assets at once
(asset images form a cached prefix) and returns the single best-matching
asset. It collapses the per-asset ``images × assets`` fan-out into one call
per image, but it changes matcher reasoning (1:N) and drops the per-pair
perceptual-hash veto — so it must be eval-gated before being enabled.

The fixture manifest stores 1:1 ``(asset, discovered)`` pairs, so to test the
1:N *selection* behaviour this runner builds a candidate set of
``[correct asset] + K distractor assets`` (sampled deterministically from
other cases) and verifies the matcher picks the right one:

  * positive case  → correct iff it matches AND selects the case's own asset
  * negative case  → correct iff it matches NOTHING (any match = false positive)

The runner calls the matcher directly (independent of the feature flag) so the
path is gated regardless of whether it is currently enabled in production.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List

from ..manifest import FixtureCase, Manifest
from .base import BaseRunner, RunnerResult, fixture_downloads

log = logging.getLogger("eval.multi_asset")

# How many distractor assets to mix in alongside the correct one. 4 → a
# 5-asset candidate set, enough to exercise selection without ballooning the
# per-call token count (and matching the kind of multi-creative campaign that
# triggered the runaway-cost incident).
_DISTRACTOR_COUNT = 4

# Categories that carry a meaningful same-creative / not-same verdict.
_POSITIVE_CATEGORIES = {
    "clear_positive", "template_positive", "modified_positive", "borderline_true",
}


class MultiAssetRunner(BaseRunner):
    name = "multi_asset"
    model_attr = "ENSEMBLE_MODEL"

    def __init__(self) -> None:
        self._all_cases: List[FixtureCase] = []

    def relevant_categories(self) -> List[str]:
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

    async def run(self, manifest: Manifest, *, concurrency: int = 1) -> RunnerResult:
        # Capture the full case list so execute_case can mine distractor
        # assets from other fixtures. Read-only; safe under concurrency.
        self._all_cases = list(manifest.cases)
        return await super().run(manifest, concurrency=concurrency)

    def _distractors(self, case: FixtureCase) -> List[FixtureCase]:
        """Deterministically pick distractor cases whose asset differs."""
        pool = [
            c for c in self._all_cases
            if c.id != case.id and c.asset_path != case.asset_path
        ]
        pool.sort(key=lambda c: c.id)
        return pool[:_DISTRACTOR_COUNT]

    async def execute_case(self, case: FixtureCase) -> Dict[str, Any]:
        from app.services import ai_service

        from ..config import load_config
        cfg = load_config()

        # Build the candidate asset set: the correct asset + distractors.
        url_to_bytes: Dict[str, bytes] = {}
        assets: List[Dict[str, Any]] = []

        correct_url = f"eval://asset/{case.id}"
        url_to_bytes[correct_url] = case.asset_bytes(cfg.fixtures_dir)
        assets.append({"id": case.id, "file_url": correct_url})

        for d in self._distractors(case):
            durl = f"eval://asset/{d.id}"
            try:
                url_to_bytes[durl] = d.asset_bytes(cfg.fixtures_dir)
            except Exception:  # noqa: BLE001 — skip a missing distractor file
                continue
            assets.append({"id": d.id, "file_url": durl})

        discovered_url = f"eval://discovered/{case.id}"
        url_to_bytes[discovered_url] = case.discovered_bytes(cfg.fixtures_dir)

        # Deterministic shuffle (seeded by case id) so the correct asset is
        # not always first, but the ordering is stable across runs for clean
        # baseline diffing.
        random.Random(case.id).shuffle(assets)

        with fixture_downloads(url_to_bytes):
            best_match, score = await ai_service.match_image_against_assets(
                assets, discovered_url,
            )

        threshold = ai_service.settings.regular_image_match_threshold
        matched = best_match is not None and score >= threshold
        selected_id = best_match["asset"]["id"] if best_match else None
        selected_correct = selected_id == case.id

        # Category-aware verdict so recall/precision stay honest for a 1:N
        # selector: a positive only counts when it matches the RIGHT asset; a
        # negative counts as a (false) match when it matches ANY asset.
        if case.category in _POSITIVE_CATEGORIES:
            is_match = matched and selected_correct
        else:
            is_match = matched

        return {
            "is_match": bool(is_match),
            "score": int(score or 0),
            "extras": {
                "raw_matched": matched,
                "selected_asset_id": selected_id,
                "selected_correct": selected_correct,
                "num_candidate_assets": len(assets),
                "match_type": (best_match or {}).get("comparison", {}).get("match_type", "none") if best_match else "none",
            },
        }
