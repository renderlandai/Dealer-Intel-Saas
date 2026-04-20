"""Markdown reporter for eval runs.

Produces a single Markdown document summarising:

  * the run-level metadata (model ids, fixture count, total cost)
  * per-runner metrics tables
  * a diff section vs the committed baseline (or "first run" if absent)
  * the gate verdict (PASS / FAIL with reasons)

The report is meant to be both human-readable in a PR description and
machine-parseable enough to surface in CI status messages.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .baseline import Baseline, DiffReport
from .config import EvalConfig
from .metrics import Metrics


def write_report(
    metrics_by_runner: Dict[str, Metrics],
    diff: DiffReport,
    baseline: Optional[Baseline],
    cfg: EvalConfig,
    out_path: Path,
) -> None:
    md = render_markdown(metrics_by_runner, diff, baseline, cfg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)


def render_markdown(
    metrics_by_runner: Dict[str, Metrics],
    diff: DiffReport,
    baseline: Optional[Baseline],
    cfg: EvalConfig,
) -> str:
    lines: List[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    gate = "PASS" if not diff.gate_failed else "FAIL"
    lines.append(f"# Eval Report — {gate}")
    lines.append("")
    lines.append(f"_Generated {now}_")
    if baseline and baseline.captured_at:
        lines.append(f"_Baseline captured {baseline.captured_at}_")
    if baseline and baseline.git_sha:
        lines.append(f"_Baseline git sha `{baseline.git_sha[:12]}`_")
    lines.append("")

    if diff.gate_failed:
        lines.append("## Gate Failures")
        lines.append("")
        for r in diff.gate_reasons:
            lines.append(f"- {r}")
        lines.append("")
        lines.append(
            "_To accept these changes intentionally, re-run with `--update-baseline` "
            "and commit the new `eval/baseline.json` together with the change._"
        )
        lines.append("")

    # Summary across all runners.
    total_cost = sum(m.total_cost_usd for m in metrics_by_runner.values())
    total_cases = sum(m.total_cases for m in metrics_by_runner.values())
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Runners executed: {len(metrics_by_runner)}")
    lines.append(f"- Cases executed: {total_cases}")
    lines.append(f"- Total cost: ${total_cost:.4f}")
    lines.append("")

    # Per-runner detail.
    for runner_name, m in metrics_by_runner.items():
        lines.extend(_runner_section(runner_name, m, baseline))

    # Diff section.
    if diff.flipped_verdicts:
        lines.append("## Verdict Flips vs Baseline")
        lines.append("")
        lines.append("| Runner | Case | Field | Baseline | Current |")
        lines.append("|---|---|---|---|---|")
        for f in diff.flipped_verdicts:
            lines.append(
                f"| {f['runner']} | `{f['case_id']}` ({f['category']}) | "
                f"{f['field']} | {f['baseline']} | {f['current']} |"
            )
        lines.append("")

    if diff.drifted_scores:
        lines.append("## Score Drift vs Baseline")
        lines.append(
            f"_Cases where the numeric score changed by ≥{cfg.max_score_drift_points} points "
            f"(threshold to fail gate: >{cfg.max_score_drift_count} cases)._"
        )
        lines.append("")
        lines.append("| Runner | Case | Category | Baseline | Current | Δ |")
        lines.append("|---|---|---|---|---|---|")
        for d in diff.drifted_scores:
            sign = "+" if d["delta"] >= 0 else ""
            lines.append(
                f"| {d['runner']} | `{d['case_id']}` | {d['category']} | "
                f"{d['baseline_score']} | {d['current_score']} | {sign}{d['delta']} |"
            )
        lines.append("")

    if diff.entries:
        lines.append("## Metric Diffs")
        lines.append("")
        lines.append("| Runner | Metric | Baseline | Current | Δ | Severity |")
        lines.append("|---|---|---|---|---|---|")
        for e in diff.entries:
            delta_str = ""
            if e.delta is not None:
                sign = "+" if e.delta >= 0 else ""
                delta_str = f"{sign}{e.delta:.2f}%"
            lines.append(
                f"| {e.runner} | {e.metric} | {_fmt(e.baseline_value)} | "
                f"{_fmt(e.current_value)} | {delta_str} | {e.severity} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def _runner_section(runner_name: str, m: Metrics, baseline: Optional[Baseline]) -> List[str]:
    lines: List[str] = []
    lines.append(f"## Runner: `{runner_name}`")
    lines.append("")
    bl = baseline.runner_metrics.get(runner_name) if baseline else None

    rows: List[tuple] = [
        ("Cases", m.total_cases, (bl or {}).get("total_cases")),
        ("Correct", m.correct, (bl or {}).get("correct")),
        ("Incorrect", m.incorrect, (bl or {}).get("incorrect")),
        ("Errors", m.errors, (bl or {}).get("errors")),
        ("Recall", _fmt(m.recall), _fmt((bl or {}).get("recall"))),
        ("Precision", _fmt(m.precision), _fmt((bl or {}).get("precision"))),
        ("F1", _fmt(m.f1), _fmt((bl or {}).get("f1"))),
    ]
    if runner_name == "compliance":
        rows.extend([
            ("Compliance recall", _fmt(m.compliance_recall),
             _fmt((bl or {}).get("compliance_recall"))),
            ("Compliance precision", _fmt(m.compliance_precision),
             _fmt((bl or {}).get("compliance_precision"))),
        ])
    rows.extend([
        ("Avg score (positives)", _fmt(m.avg_score_positive),
         _fmt((bl or {}).get("avg_score_positive"))),
        ("Avg score (negatives)", _fmt(m.avg_score_negative),
         _fmt((bl or {}).get("avg_score_negative"))),
        ("Total cost (USD)", f"${m.total_cost_usd:.4f}",
         f"${(bl or {}).get('total_cost_usd', 0):.4f}" if bl else "—"),
        ("Avg latency (ms)", f"{m.avg_latency_ms:.1f}",
         f"{(bl or {}).get('avg_latency_ms', 0):.1f}" if bl else "—"),
        ("p95 latency (ms)", f"{m.p95_latency_ms:.1f}",
         f"{(bl or {}).get('p95_latency_ms', 0):.1f}" if bl else "—"),
    ])

    lines.append("| Metric | Current | Baseline |")
    lines.append("|---|---|---|")
    for name, cur, base in rows:
        lines.append(f"| {name} | {cur} | {base if base is not None else '—'} |")
    lines.append("")
    return lines


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def render_console_summary(
    metrics_by_runner: Dict[str, Metrics],
    diff: DiffReport,
) -> str:
    """One-screen text summary for terminal output."""
    out: List[str] = []
    gate = "PASS" if not diff.gate_failed else "FAIL"
    out.append(f"=== Eval Gate: {gate} ===")
    for r in diff.gate_reasons:
        out.append(f"  ! {r}")
    for runner_name, m in metrics_by_runner.items():
        out.append(
            f"  {runner_name:<14} cases={m.total_cases:<3} "
            f"correct={m.correct:<3} errors={m.errors:<2} "
            f"recall={_fmt(m.recall):<6} precision={_fmt(m.precision):<6} "
            f"cost=${m.total_cost_usd:.4f}"
        )
    if diff.flipped_verdicts:
        out.append(f"  {len(diff.flipped_verdicts)} verdict flip(s) vs baseline")
    if diff.drifted_scores:
        out.append(f"  {len(diff.drifted_scores)} score drift(s) vs baseline")
    return "\n".join(out)
