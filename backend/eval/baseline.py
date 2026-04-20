"""Baseline persistence + diff logic.

A baseline is a JSON snapshot of the metrics produced by the most recent
known-good run.  Every PR that touches the AI pipeline diffs against this
snapshot; if any guarded metric regresses beyond its tolerance, the eval
gate fails.

Updating the baseline is an explicit, reviewable action — `eval/run.py
--update-baseline` overwrites the file, which is then committed alongside
the prompt or model change that justified it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import EvalConfig
from .metrics import Metrics


@dataclass
class Baseline:
    version: int = 1
    captured_at: str = ""
    git_sha: str = ""
    runner_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "captured_at": self.captured_at,
            "git_sha": self.git_sha,
            "runner_metrics": self.runner_metrics,
        }

    @classmethod
    def from_metrics(cls, metrics_by_runner: Dict[str, Metrics],
                     git_sha: str = "") -> "Baseline":
        return cls(
            version=1,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            git_sha=git_sha,
            runner_metrics={
                runner: m.as_dict() for runner, m in metrics_by_runner.items()
            },
        )

    @classmethod
    def load(cls, path: Path) -> Optional["Baseline"]:
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        return cls(
            version=raw.get("version", 1),
            captured_at=raw.get("captured_at", ""),
            git_sha=raw.get("git_sha", ""),
            runner_metrics=raw.get("runner_metrics", {}),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=False) + "\n")


@dataclass
class DiffEntry:
    """One regression / improvement vs baseline."""

    runner: str
    metric: str
    baseline_value: Any
    current_value: Any
    delta: Optional[float] = None
    severity: str = "info"   # "info" | "regression" | "improvement"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "runner": self.runner,
            "metric": self.metric,
            "baseline": self.baseline_value,
            "current": self.current_value,
            "delta": self.delta,
            "severity": self.severity,
        }


@dataclass
class DiffReport:
    entries: List[DiffEntry] = field(default_factory=list)
    flipped_verdicts: List[Dict[str, Any]] = field(default_factory=list)
    drifted_scores: List[Dict[str, Any]] = field(default_factory=list)
    gate_failed: bool = False
    gate_reasons: List[str] = field(default_factory=list)

    def add(self, entry: DiffEntry) -> None:
        self.entries.append(entry)

    def fail_gate(self, reason: str) -> None:
        self.gate_failed = True
        self.gate_reasons.append(reason)


def diff_against_baseline(
    current: Dict[str, Metrics],
    baseline: Optional[Baseline],
    cfg: EvalConfig,
) -> DiffReport:
    """Diff current metrics against a stored baseline and apply the gate."""
    report = DiffReport()
    if baseline is None:
        # First-ever run: nothing to diff against.  Emit a single info row.
        report.add(DiffEntry(
            runner="*", metric="baseline",
            baseline_value=None, current_value="captured",
            severity="info",
        ))
        return report

    for runner, m in current.items():
        bl = baseline.runner_metrics.get(runner)
        if not bl:
            report.add(DiffEntry(
                runner=runner, metric="*",
                baseline_value=None,
                current_value="new runner — no baseline",
                severity="info",
            ))
            continue

        # Per-metric checks.
        _check_recall(report, runner, m, bl, cfg)
        _check_precision(report, runner, m, bl, cfg)
        _check_compliance_recall(report, runner, m, bl, cfg)
        _check_cost(report, runner, m, bl, cfg)
        _check_latency(report, runner, m, bl, cfg)
        _check_score_drift(report, runner, m, bl, cfg)
        _check_verdict_flips(report, runner, m, bl)

    return report


def _pct_delta(current: Optional[float], baseline_v: Optional[float]) -> Optional[float]:
    if current is None or baseline_v is None:
        return None
    if baseline_v == 0:
        return None
    return (current - baseline_v) / baseline_v * 100.0


def _check_recall(report, runner, m, bl, cfg):
    bl_recall = bl.get("recall")
    if m.recall is None or bl_recall is None:
        return
    delta_pct = (m.recall - bl_recall) * 100  # absolute pct points
    sev = "info"
    if delta_pct < -cfg.max_recall_drop_pct:
        sev = "regression"
        report.fail_gate(
            f"{runner}: recall dropped {abs(delta_pct):.2f} pts "
            f"({bl_recall:.4f} → {m.recall:.4f}, max allowed -{cfg.max_recall_drop_pct})"
        )
    elif delta_pct > 0:
        sev = "improvement"
    report.add(DiffEntry(runner, "recall", bl_recall, m.recall, delta_pct, sev))


def _check_precision(report, runner, m, bl, cfg):
    bl_precision = bl.get("precision")
    if m.precision is None or bl_precision is None:
        return
    delta_pct = (m.precision - bl_precision) * 100
    sev = "info"
    if delta_pct < -cfg.max_precision_drop_pct:
        sev = "regression"
        report.fail_gate(
            f"{runner}: precision dropped {abs(delta_pct):.2f} pts "
            f"({bl_precision:.4f} → {m.precision:.4f}, max allowed -{cfg.max_precision_drop_pct})"
        )
    elif delta_pct > 0:
        sev = "improvement"
    report.add(DiffEntry(runner, "precision", bl_precision, m.precision, delta_pct, sev))


def _check_compliance_recall(report, runner, m, bl, cfg):
    if runner != "compliance":
        return
    bl_v = bl.get("compliance_recall")
    if m.compliance_recall is None or bl_v is None:
        return
    delta_pct = (m.compliance_recall - bl_v) * 100
    sev = "info"
    if delta_pct < -cfg.max_compliance_recall_drop_pct:
        sev = "regression"
        report.fail_gate(
            f"compliance: drift recall dropped {abs(delta_pct):.2f} pts "
            f"({bl_v:.4f} → {m.compliance_recall:.4f}, zero tolerance)"
        )
    elif delta_pct > 0:
        sev = "improvement"
    report.add(DiffEntry(
        runner, "compliance_recall", bl_v, m.compliance_recall, delta_pct, sev,
    ))


def _check_cost(report, runner, m, bl, cfg):
    bl_v = bl.get("total_cost_usd", 0)
    if not bl_v:
        return
    delta_pct = _pct_delta(m.total_cost_usd, bl_v)
    if delta_pct is None:
        return
    sev = "info"
    if delta_pct > cfg.max_cost_increase_pct:
        sev = "regression"
        report.fail_gate(
            f"{runner}: cost up {delta_pct:.1f}% "
            f"(${bl_v:.4f} → ${m.total_cost_usd:.4f}, max allowed +{cfg.max_cost_increase_pct}%)"
        )
    elif delta_pct < -5:
        sev = "improvement"
    report.add(DiffEntry(runner, "total_cost_usd", bl_v, m.total_cost_usd, delta_pct, sev))


def _check_latency(report, runner, m, bl, cfg):
    bl_v = bl.get("p95_latency_ms", 0)
    if not bl_v:
        return
    delta_pct = _pct_delta(m.p95_latency_ms, bl_v)
    if delta_pct is None:
        return
    sev = "info"
    if delta_pct > cfg.max_latency_increase_pct:
        sev = "regression"
        report.fail_gate(
            f"{runner}: p95 latency up {delta_pct:.1f}% "
            f"({bl_v:.1f}ms → {m.p95_latency_ms:.1f}ms, "
            f"max allowed +{cfg.max_latency_increase_pct}%)"
        )
    elif delta_pct < -10:
        sev = "improvement"
    report.add(DiffEntry(runner, "p95_latency_ms", bl_v, m.p95_latency_ms, delta_pct, sev))


def _check_score_drift(report, runner, m, bl, cfg):
    """Detect cases where a numeric score moved by more than the threshold,
    even when the boolean verdict didn't flip.  This is what catches the
    Option-B-style prompt restructure that doesn't change verdicts but
    poisons your adaptive thresholds.
    """
    if runner not in ("opus_detect", "verify"):
        return
    drifted_count = 0
    for case_id, current_per in m.per_case.items():
        bl_per = bl.get("per_case", {}).get(case_id)
        if not bl_per:
            continue
        cur_score = (current_per.get("actual") or {}).get("score")
        bl_score = (bl_per.get("actual") or {}).get("score")
        if cur_score is None or bl_score is None:
            continue
        delta = cur_score - bl_score
        if abs(delta) >= cfg.max_score_drift_points:
            drifted_count += 1
            report.drifted_scores.append({
                "runner": runner,
                "case_id": case_id,
                "category": current_per.get("category"),
                "baseline_score": bl_score,
                "current_score": cur_score,
                "delta": delta,
            })
    if drifted_count > cfg.max_score_drift_count:
        report.fail_gate(
            f"{runner}: {drifted_count} cases drifted by ≥{cfg.max_score_drift_points} "
            f"score points (max allowed {cfg.max_score_drift_count})"
        )


def _check_verdict_flips(report, runner, m, bl):
    bl_per = bl.get("per_case", {})
    for case_id, current_per in m.per_case.items():
        bl_case = bl_per.get(case_id)
        if not bl_case:
            continue
        cur_actual = current_per.get("actual") or {}
        bl_actual = bl_case.get("actual") or {}
        for key in ("is_relevant", "is_match", "is_compliant", "zombie_ad"):
            if key in cur_actual and key in bl_actual and cur_actual[key] != bl_actual[key]:
                report.flipped_verdicts.append({
                    "runner": runner,
                    "case_id": case_id,
                    "category": current_per.get("category"),
                    "field": key,
                    "baseline": bl_actual[key],
                    "current": cur_actual[key],
                })
