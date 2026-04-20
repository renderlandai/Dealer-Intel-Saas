"""Re-run the compliance runner only and print per-case verdict vs expectation."""
from __future__ import annotations

import asyncio
import logging

from eval.config import load_config
from eval.manifest import Manifest
from eval.metrics import compute_metrics
from eval.runners.compliance import ComplianceRunner


async def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    cfg = load_config()
    manifest = Manifest.load(cfg.manifest_path)
    runner = ComplianceRunner()
    result = await runner.run(manifest, concurrency=3)
    metrics = compute_metrics(result, manifest)

    print(f"compliance: {metrics.correct}/{metrics.total_cases} correct  "
          f"recall={metrics.compliance_recall}  precision={metrics.compliance_precision}")
    print()
    print(f"{'case_id':<55} {'category':<18} {'exp_comp':<10} {'got_comp':<10} {'exp_z':<6} {'got_z':<6} ok")
    for cid, pc in metrics.per_case.items():
        exp = pc.get("expected", {}) or {}
        act = pc.get("actual", {}) or {}
        exp_c = exp.get("is_compliant")
        got_c = act.get("is_compliant")
        exp_z = exp.get("zombie_ad")
        got_z = act.get("zombie_ad")
        # Mirror the metrics module's logic.
        if exp_c is None:
            exp_c_eff = pc.get("category") in ("clear_positive", "template_positive")
        else:
            exp_c_eff = bool(exp_c)
        compliant_ok = bool(got_c) == exp_c_eff
        zombie_ok = (exp_z is None) or (bool(got_z) == bool(exp_z))
        ok = "✓" if (compliant_ok and zombie_ok) else "✗"
        print(f"{cid:<55} {pc.get('category',''):<18} "
              f"{str(exp_c_eff):<10} {str(got_c):<10} "
              f"{str(exp_z):<6} {str(got_z):<6} {ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
