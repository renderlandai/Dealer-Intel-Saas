"""Quality metrics for runner output.

The metrics here are intentionally narrow and tied to product-level
decisions (recall on positives, compliance recall, false-positive rate)
rather than generic ML metrics, because the decisions made downstream
(alerting a customer to a drift, surfacing a match for review) are also
narrow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .manifest import FixtureCase, Manifest
from .runners.base import CaseResult, RunnerResult


# Categories that represent ground-truth positives for the various stages.
_FILTER_POSITIVE_CATEGORIES = {
    "clear_positive", "template_positive", "modified_positive",
    "borderline_true", "compliance_drift", "zombie_ad",
    # `same_promo_diff_creative` is a *filter* positive (the Haiku stage
    # should let it through to the detector — the detector's job is to
    # then reject it as not the same creative).
    "same_promo_diff_creative",
}
_FILTER_NEGATIVE_CATEGORIES = {
    "different_brand",
}

_DETECT_POSITIVE_CATEGORIES = {
    "clear_positive", "template_positive", "modified_positive",
    "borderline_true",
}
_DETECT_NEGATIVE_CATEGORIES = {
    "same_promo_diff_creative", "same_brand_diff_campaign",
    "different_brand", "borderline_false",
}

_COMPLIANCE_POSITIVE_CATEGORIES = {  # i.e. cases that SHOULD flag a violation
    "compliance_drift", "zombie_ad",
}
_COMPLIANCE_NEGATIVE_CATEGORIES = {  # cases that SHOULD pass compliance
    "clear_positive", "template_positive",
}


@dataclass
class Metrics:
    """Aggregated metrics for one runner."""

    runner: str
    total_cases: int = 0
    correct: int = 0
    incorrect: int = 0
    skipped: int = 0
    errors: int = 0

    # Recall = how many true positives we caught / how many existed.
    recall: Optional[float] = None
    precision: Optional[float] = None
    f1: Optional[float] = None

    # Compliance-specific (drift recall is the highest-stakes metric).
    compliance_recall: Optional[float] = None
    compliance_precision: Optional[float] = None

    # Score-related diagnostics (only meaningful for stages that emit a
    # numeric score: opus_detect, verify).
    avg_score_positive: Optional[float] = None
    avg_score_negative: Optional[float] = None
    score_threshold_violations: int = 0  # cases outside expected min/max range

    # Cost / perf
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0

    # Per-case verdict map for diffing against baseline.
    per_case: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "runner": self.runner,
            "total_cases": self.total_cases,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "skipped": self.skipped,
            "errors": self.errors,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
        }
        for key in (
            "recall", "precision", "f1",
            "compliance_recall", "compliance_precision",
            "avg_score_positive", "avg_score_negative",
        ):
            v = getattr(self, key)
            if v is not None:
                out[key] = round(v, 4)
        if self.score_threshold_violations:
            out["score_threshold_violations"] = self.score_threshold_violations
        out["per_case"] = self.per_case
        return out


def _safe_div(num: float, den: float) -> Optional[float]:
    return num / den if den else None


def compute_metrics(result: RunnerResult, manifest: Manifest) -> Metrics:
    """Reduce one runner's RunnerResult to a Metrics object."""
    by_id = {c.id: c for c in manifest.cases}

    m = Metrics(
        runner=result.runner,
        total_cases=len(result.cases),
        total_cost_usd=result.total_cost_usd,
        avg_latency_ms=result.avg_latency_ms,
        p95_latency_ms=result.p95_latency_ms,
    )

    # Confusion-matrix counters (interpreted per-stage below).
    tp = fp = tn = fn = 0
    comp_tp = comp_fp = comp_tn = comp_fn = 0
    pos_scores: List[int] = []
    neg_scores: List[int] = []

    for case_result in result.cases:
        case = by_id.get(case_result.case_id)
        if case is None:
            m.skipped += 1
            continue

        per_case: Dict[str, Any] = {
            "category": case_result.category,
            "latency_ms": case_result.latency_ms,
            "cost_usd": round(case_result.cost_usd, 6),
        }

        if case_result.error:
            m.errors += 1
            per_case["error"] = case_result.error
            m.per_case[case_result.case_id] = per_case
            continue

        verdict_match = _evaluate_case(result.runner, case, case_result, m)
        if verdict_match is None:
            m.skipped += 1
            per_case["skipped"] = True
            m.per_case[case_result.case_id] = per_case
            continue

        if verdict_match:
            m.correct += 1
        else:
            m.incorrect += 1

        # Confusion-matrix accumulation differs per stage.
        if result.runner in ("haiku_filter",):
            expected_pos = case.category in _FILTER_POSITIVE_CATEGORIES
            actual_pos = bool(case_result.is_relevant)
            tp, fp, tn, fn = _bump_confusion(tp, fp, tn, fn, expected_pos, actual_pos)
            per_case["expected"] = {"is_relevant": expected_pos}
            per_case["actual"] = {"is_relevant": actual_pos}
        elif result.runner in ("opus_detect", "verify"):
            expected_pos = case.category in _DETECT_POSITIVE_CATEGORIES
            actual_pos = bool(case_result.is_match)
            tp, fp, tn, fn = _bump_confusion(tp, fp, tn, fn, expected_pos, actual_pos)
            per_case["expected"] = {
                "is_match": expected_pos,
                "min_score": case.expected.min_score,
                "max_score": case.expected.max_score,
            }
            per_case["actual"] = {
                "is_match": actual_pos,
                "score": case_result.score,
            }
            if case_result.score is not None:
                if expected_pos:
                    pos_scores.append(case_result.score)
                else:
                    neg_scores.append(case_result.score)
        elif result.runner == "compliance":
            # For compliance, "positive" = a violation we should catch.
            expected_violation = case.category in _COMPLIANCE_POSITIVE_CATEGORIES
            actual_violation = (case_result.is_compliant is False) or bool(case_result.zombie_ad)
            comp_tp, comp_fp, comp_tn, comp_fn = _bump_confusion(
                comp_tp, comp_fp, comp_tn, comp_fn, expected_violation, actual_violation,
            )
            per_case["expected"] = {
                "is_compliant": case.expected.is_compliant,
                "zombie_ad": case.expected.zombie_ad,
            }
            per_case["actual"] = {
                "is_compliant": case_result.is_compliant,
                "zombie_ad": case_result.zombie_ad,
            }

        m.per_case[case_result.case_id] = per_case

    # Recall / precision / F1.
    m.recall = _safe_div(tp, tp + fn)
    m.precision = _safe_div(tp, tp + fp)
    if m.recall is not None and m.precision is not None and (m.recall + m.precision):
        m.f1 = 2 * m.recall * m.precision / (m.recall + m.precision)

    if result.runner == "compliance":
        m.compliance_recall = _safe_div(comp_tp, comp_tp + comp_fn)
        m.compliance_precision = _safe_div(comp_tp, comp_tp + comp_fp)

    if pos_scores:
        m.avg_score_positive = sum(pos_scores) / len(pos_scores)
    if neg_scores:
        m.avg_score_negative = sum(neg_scores) / len(neg_scores)

    return m


def _bump_confusion(tp: int, fp: int, tn: int, fn: int,
                    expected_pos: bool, actual_pos: bool):
    if expected_pos and actual_pos:
        tp += 1
    elif expected_pos and not actual_pos:
        fn += 1
    elif (not expected_pos) and actual_pos:
        fp += 1
    else:
        tn += 1
    return tp, fp, tn, fn


def _evaluate_case(runner: str, case: FixtureCase, result: CaseResult,
                   metrics: Metrics) -> Optional[bool]:
    """Return True if the runner's verdict matches the expectation,
    False if it doesn't, or None if this case isn't applicable to this
    runner (and should be counted as skipped).
    """
    exp = case.expected
    if runner == "haiku_filter":
        if exp.is_relevant is None and case.category not in _FILTER_NEGATIVE_CATEGORIES:
            return None
        expected = (
            exp.is_relevant
            if exp.is_relevant is not None
            else (case.category in _FILTER_POSITIVE_CATEGORIES)
        )
        return bool(result.is_relevant) == bool(expected)

    if runner in ("opus_detect", "verify"):
        if exp.is_match is None:
            # Fall back to category mapping when the manifest didn't
            # explicitly set is_match.
            expected = case.category in _DETECT_POSITIVE_CATEGORIES
        else:
            expected = bool(exp.is_match)
        match_ok = bool(result.is_match) == expected
        # Score-range check is a separate, softer signal.
        if (
            result.score is not None
            and (exp.min_score is not None or exp.max_score is not None)
        ):
            lo = exp.min_score if exp.min_score is not None else -1
            hi = exp.max_score if exp.max_score is not None else 101
            if not (lo <= result.score <= hi):
                metrics.score_threshold_violations += 1
        return match_ok

    if runner == "compliance":
        if exp.is_compliant is None and exp.zombie_ad is None:
            # Compliance fixture without ground truth — skip.
            if case.category not in (_COMPLIANCE_POSITIVE_CATEGORIES |
                                     _COMPLIANCE_NEGATIVE_CATEGORIES):
                return None
        expected_compliant = (
            exp.is_compliant
            if exp.is_compliant is not None
            else (case.category in _COMPLIANCE_NEGATIVE_CATEGORIES)
        )
        compliant_ok = bool(result.is_compliant) == bool(expected_compliant)
        if exp.zombie_ad is not None:
            zombie_ok = bool(result.zombie_ad) == bool(exp.zombie_ad)
            return compliant_ok and zombie_ok
        return compliant_ok

    return None
