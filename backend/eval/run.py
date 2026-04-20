"""CLI entry point — ``python -m eval.run``.

Usage::

    # Run every runner against the manifest, diff against the baseline,
    # write a Markdown report, and exit non-zero if the gate fails.
    python -m eval.run

    # Limit to one stage (useful while iterating on a prompt).
    python -m eval.run --stage haiku_filter

    # Capture a new baseline (only do this once you've reviewed the
    # diff and accepted the change).
    python -m eval.run --update-baseline

    # Higher concurrency speeds up multi-case runs but burns more API
    # quota in parallel.
    python -m eval.run --concurrency 4

Exit codes:
  0  → gate passed (or first-ever baseline captured)
  2  → gate failed (regression detected)
  3  → infrastructure error (no manifest, missing fixtures, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .baseline import Baseline, diff_against_baseline
from .config import load_config
from .manifest import Manifest
from .metrics import Metrics, compute_metrics
from .report import render_console_summary, write_report
from .runners import RUNNERS

log = logging.getLogger("eval")


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
        ).decode().strip()
        return out
    except Exception:
        return ""


async def _run_async(args) -> int:
    cfg = load_config()

    try:
        manifest = Manifest.load(cfg.manifest_path)
    except FileNotFoundError as e:
        log.error(str(e))
        return 3

    if not manifest.cases:
        log.error("Manifest has no cases — seed it first.")
        return 3

    print(manifest.summary())
    print()

    selected = args.stage.split(",") if args.stage else list(RUNNERS.keys())
    unknown = [s for s in selected if s not in RUNNERS]
    if unknown:
        log.error("Unknown stage(s): %s. Choose from: %s",
                  ", ".join(unknown), ", ".join(RUNNERS.keys()))
        return 3

    metrics_by_runner: Dict[str, Metrics] = {}
    for runner_name in selected:
        runner_cls = RUNNERS[runner_name]
        runner = runner_cls()
        log.info("Running %s …", runner_name)
        result = await runner.run(manifest, concurrency=args.concurrency)
        m = compute_metrics(result, manifest)
        metrics_by_runner[runner_name] = m
        log.info(
            "  → %d cases, %d correct, %d errors, cost=$%.4f, p95=%.1fms",
            m.total_cases, m.correct, m.errors, m.total_cost_usd, m.p95_latency_ms,
        )

    baseline = Baseline.load(cfg.baseline_path)
    diff = diff_against_baseline(metrics_by_runner, baseline, cfg)

    # Console summary first so it shows up even if the report write fails.
    print()
    print(render_console_summary(metrics_by_runner, diff))
    print()

    # Markdown report.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_name = f"eval-{timestamp}.md"
    report_path = cfg.reports_dir / report_name
    write_report(metrics_by_runner, diff, baseline, cfg, report_path)
    print(f"Report written to {report_path}")

    if args.update_baseline:
        new_baseline = Baseline.from_metrics(metrics_by_runner, git_sha=_git_sha())
        new_baseline.save(cfg.baseline_path)
        print(f"Baseline updated → {cfg.baseline_path}")
        return 0

    if diff.gate_failed:
        print("EVAL GATE FAILED — see report for details.")
        return 2
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval.run",
        description="Run the Dealer Intel AI eval harness.",
    )
    parser.add_argument(
        "--stage",
        help="Comma-separated runner names to run (default: all). "
             "Choices: " + ", ".join(RUNNERS.keys()),
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Max concurrent fixtures per runner (default: 1).",
    )
    parser.add_argument(
        "--update-baseline", action="store_true",
        help="Overwrite eval/baseline.json with the current run's metrics. "
             "Only do this after reviewing the diff and intentionally "
             "accepting the change.",
    )
    parser.add_argument(
        "--log-level", default=os.environ.get("EVAL_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    # Quiet down noisy upstreams.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    return asyncio.run(_run_async(args))


if __name__ == "__main__":
    sys.exit(main())
