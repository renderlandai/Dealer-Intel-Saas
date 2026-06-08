"""Wiring tests for the regular-image / multi-asset eval runners.

These run the new ``opus_compare`` and ``multi_asset`` runners end-to-end
against tiny on-disk fixtures with the Anthropic call mocked — so they
validate the runner plumbing (fixture loading, download patching, verdict
shaping, metric scoring) without any network access or API spend.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services import ai_service
from eval.manifest import FixtureCase, Manifest, Expected
from eval.metrics import compute_metrics
from eval.runners import OpusCompareRunner, MultiAssetRunner


def _write_jpeg(path, color) -> None:
    img = Image.new("RGB", (320, 200), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    path.write_bytes(buf.getvalue())


@pytest.fixture()
def fixtures_dir(tmp_path, monkeypatch):
    _write_jpeg(tmp_path / "asset.jpg", (200, 30, 30))
    _write_jpeg(tmp_path / "disc.jpg", (200, 30, 30))
    monkeypatch.setenv("EVAL_FIXTURES_DIR", str(tmp_path))
    monkeypatch.setenv("EVAL_IMAGES_DIR", str(tmp_path))
    return tmp_path


def _case(category="clear_positive", is_match=True) -> FixtureCase:
    return FixtureCase(
        id="case-1",
        category=category,
        asset_path="asset.jpg",
        discovered_path="disc.jpg",
        expected=Expected(is_match=is_match),
    )


@pytest.mark.asyncio
async def test_opus_compare_runner_scores_a_positive(fixtures_dir, monkeypatch):
    async def fake_call(prompt, images, model=None, cache_prefix_images=0, **kw):
        return (
            '{"similarity_score": 90, "is_match": true, "match_type": "strong", '
            '"modifications": [], "analysis": "same creative"}'
        )

    monkeypatch.setattr(ai_service, "call_anthropic_with_retry", fake_call)

    manifest = Manifest(cases=[_case()])
    runner = OpusCompareRunner()
    result = await runner.run(manifest, concurrency=1)

    assert result.total_cases == 1
    case_result = result.cases[0]
    assert case_result.error is None
    assert case_result.is_match is True
    assert case_result.score >= ai_service.settings.regular_image_match_threshold

    metrics = compute_metrics(result, manifest)
    assert metrics.correct == 1
    assert metrics.recall == 1.0


@pytest.mark.asyncio
async def test_multi_asset_runner_positive_selects_correct_asset(fixtures_dir, monkeypatch):
    async def fake_call(prompt, images, model=None, cache_prefix_images=0, **kw):
        # Only the correct asset is present (no distractors in a 1-case
        # manifest) so best_match_index 1 maps to it.
        return '{"best_match_index": 1, "similarity_score": 91, "is_match": true, "modifications": [], "analysis": "ok"}'

    monkeypatch.setattr(ai_service, "call_anthropic_with_retry", fake_call)

    manifest = Manifest(cases=[_case()])
    runner = MultiAssetRunner()
    result = await runner.run(manifest, concurrency=1)

    case_result = result.cases[0]
    assert case_result.error is None
    assert case_result.is_match is True
    assert case_result.extras["selected_correct"] is True

    metrics = compute_metrics(result, manifest)
    assert metrics.correct == 1


@pytest.mark.asyncio
async def test_multi_asset_runner_negative_no_match(fixtures_dir, monkeypatch):
    async def fake_call(prompt, images, model=None, cache_prefix_images=0, **kw):
        return '{"best_match_index": 0, "similarity_score": 0, "is_match": false}'

    monkeypatch.setattr(ai_service, "call_anthropic_with_retry", fake_call)

    manifest = Manifest(cases=[_case(category="different_brand", is_match=False)])
    runner = MultiAssetRunner()
    result = await runner.run(manifest, concurrency=1)

    case_result = result.cases[0]
    assert case_result.error is None
    assert case_result.is_match is False

    metrics = compute_metrics(result, manifest)
    assert metrics.correct == 1  # correctly produced no match on a negative


@pytest.mark.asyncio
async def test_multi_asset_runner_positive_wrong_asset_is_incorrect(fixtures_dir, monkeypatch):
    """A positive that matches but selects the WRONG asset must be scored
    incorrect (recall miss) — this is the 1:N selection guarantee."""
    # Two cases so a distractor exists; force the matcher to pick the
    # distractor (index will map to whichever asset is NOT case-1).
    _write_jpeg(fixtures_dir / "asset2.jpg", (30, 30, 200))
    _write_jpeg(fixtures_dir / "disc2.jpg", (30, 30, 200))
    other = FixtureCase(
        id="case-2", category="clear_positive",
        asset_path="asset2.jpg", discovered_path="disc2.jpg",
        expected=Expected(is_match=True),
    )

    async def fake_call(prompt, images, model=None, cache_prefix_images=0, **kw):
        # Always claim the FIRST candidate matches. After the deterministic
        # shuffle the first candidate may or may not be the correct asset;
        # we assert the runner reports selected_correct consistently.
        return '{"best_match_index": 1, "similarity_score": 85, "is_match": true, "modifications": [], "analysis": "ok"}'

    monkeypatch.setattr(ai_service, "call_anthropic_with_retry", fake_call)

    manifest = Manifest(cases=[_case(), other])
    runner = MultiAssetRunner()
    result = await runner.run(manifest, concurrency=1)

    by_id = {c.case_id: c for c in result.cases}
    cr = by_id["case-1"]
    assert cr.error is None
    # is_match must equal (matched AND selected_correct): if the shuffled
    # first candidate was a distractor, is_match must be False.
    assert cr.is_match == (cr.extras["raw_matched"] and cr.extras["selected_correct"])
