"""Eval harness configuration.

Resolves filesystem paths and tunable thresholds.  Everything here is
intentionally simple and dependency-free — no Pydantic, no Supabase,
no FastAPI — so the harness can run in CI without booting the app.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_HERE = Path(__file__).resolve().parent

# Default filesystem layout (overridable via env vars for CI).
DEFAULT_FIXTURES_DIR = _HERE / "fixtures"
DEFAULT_IMAGES_DIR = DEFAULT_FIXTURES_DIR / "images"
DEFAULT_MANIFEST_PATH = DEFAULT_FIXTURES_DIR / "manifest.json"
DEFAULT_BASELINE_PATH = _HERE / "baseline.json"
DEFAULT_REPORTS_DIR = _HERE / "reports"


@dataclass(frozen=True)
class EvalConfig:
    fixtures_dir: Path
    images_dir: Path
    manifest_path: Path
    baseline_path: Path
    reports_dir: Path

    # Regression thresholds — a PR is considered to fail the eval gate
    # when ANY of these are exceeded.  Numbers chosen to favour caution
    # for a compliance product where missed matches are the worst failure.
    max_recall_drop_pct: float = 2.0           # known matches we now miss
    max_precision_drop_pct: float = 5.0        # new false positives
    max_compliance_recall_drop_pct: float = 0.0  # zero tolerance for missed drift
    max_cost_increase_pct: float = 15.0        # budget surprise threshold
    max_latency_increase_pct: float = 20.0     # p95 slowdown threshold
    max_score_drift_points: int = 10           # |Δscore| flagged on borderline
    max_score_drift_count: int = 5             # how many cases may drift before fail


def load_config() -> EvalConfig:
    return EvalConfig(
        fixtures_dir=Path(os.environ.get("EVAL_FIXTURES_DIR", DEFAULT_FIXTURES_DIR)),
        images_dir=Path(os.environ.get("EVAL_IMAGES_DIR", DEFAULT_IMAGES_DIR)),
        manifest_path=Path(os.environ.get("EVAL_MANIFEST", DEFAULT_MANIFEST_PATH)),
        baseline_path=Path(os.environ.get("EVAL_BASELINE", DEFAULT_BASELINE_PATH)),
        reports_dir=Path(os.environ.get("EVAL_REPORTS_DIR", DEFAULT_REPORTS_DIR)),
        max_recall_drop_pct=float(os.environ.get("EVAL_MAX_RECALL_DROP", 2.0)),
        max_precision_drop_pct=float(os.environ.get("EVAL_MAX_PRECISION_DROP", 5.0)),
        max_compliance_recall_drop_pct=float(
            os.environ.get("EVAL_MAX_COMPLIANCE_RECALL_DROP", 0.0)
        ),
        max_cost_increase_pct=float(os.environ.get("EVAL_MAX_COST_INCREASE", 15.0)),
        max_latency_increase_pct=float(os.environ.get("EVAL_MAX_LATENCY_INCREASE", 20.0)),
        max_score_drift_points=int(os.environ.get("EVAL_MAX_SCORE_DRIFT", 10)),
        max_score_drift_count=int(os.environ.get("EVAL_MAX_SCORE_DRIFT_COUNT", 5)),
    )
