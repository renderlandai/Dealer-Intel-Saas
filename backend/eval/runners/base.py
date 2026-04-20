"""Shared scaffolding for per-stage runners.

Every runner produces a :class:`RunnerResult` containing one
:class:`CaseResult` per fixture.  The result object is intentionally
small and JSON-serialisable so it can be diffed against a committed
baseline without any framework-specific dependencies.

Each runner subclasses :class:`BaseRunner` and implements two methods:

* ``relevant_categories`` — which fixture categories this stage should
  evaluate (e.g. the verify runner only runs against ``borderline_*``
  cases).
* ``execute_case`` — wrap the production AI function being tested,
  return the verdict the stage produced, and let the base class capture
  cost + latency uniformly.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..manifest import FixtureCase, Manifest


@dataclass
class CaseResult:
    """One fixture's verdict from one runner."""

    case_id: str
    category: str

    # Verdict surface — only the fields produced by this stage are set.
    is_relevant: Optional[bool] = None
    is_match: Optional[bool] = None
    score: Optional[int] = None
    is_compliant: Optional[bool] = None
    zombie_ad: Optional[bool] = None

    # Diagnostic plumbing.
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None

    # Free-form per-stage payload (e.g. gates_passed for verify).
    extras: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"case_id": self.case_id, "category": self.category}
        for key in ("is_relevant", "is_match", "score", "is_compliant", "zombie_ad"):
            v = getattr(self, key)
            if v is not None:
                out[key] = v
        out["latency_ms"] = round(self.latency_ms, 1)
        out["cost_usd"] = round(self.cost_usd, 6)
        if self.cache_read_tokens or self.cache_creation_tokens:
            out["cache_creation_tokens"] = self.cache_creation_tokens
            out["cache_read_tokens"] = self.cache_read_tokens
        out["input_tokens"] = self.input_tokens
        out["output_tokens"] = self.output_tokens
        if self.error:
            out["error"] = self.error
        if self.extras:
            out["extras"] = self.extras
        return out


@dataclass
class RunnerResult:
    """All cases for one runner, ready for diffing + reporting."""

    runner: str
    model: str = ""
    total_cases: int = 0
    cases: List[CaseResult] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.cases), 4)

    @property
    def total_latency_ms(self) -> float:
        return round(sum(c.latency_ms for c in self.cases), 1)

    @property
    def avg_latency_ms(self) -> float:
        if not self.cases:
            return 0.0
        return round(self.total_latency_ms / len(self.cases), 1)

    @property
    def p95_latency_ms(self) -> float:
        if not self.cases:
            return 0.0
        ordered = sorted(c.latency_ms for c in self.cases)
        idx = max(0, int(round(0.95 * (len(ordered) - 1))))
        return round(ordered[idx], 1)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "runner": self.runner,
            "model": self.model,
            "total_cases": self.total_cases,
            "total_cost_usd": self.total_cost_usd,
            "avg_latency_ms": self.avg_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "cases": [c.as_dict() for c in self.cases],
        }


class BaseRunner:
    """Subclass and implement ``relevant_categories`` + ``execute_case``."""

    name: str = ""
    model_attr: str = ""  # e.g. "ENSEMBLE_MODEL" — used for report metadata

    def relevant_categories(self) -> List[str]:
        raise NotImplementedError

    async def execute_case(self, case: FixtureCase) -> Dict[str, Any]:
        """Run the production function under test for one fixture.

        Implementations should call the real ``ai_service`` function and
        return a dict with the verdict fields populated (``is_relevant``,
        ``is_match``, ``score``, ``is_compliant``, ``zombie_ad`` — only
        the ones this stage produces).  Return ``{"error": "..."}`` to
        record a failure without raising.
        """
        raise NotImplementedError

    async def _run_one(self, case: FixtureCase) -> CaseResult:
        # Use the real cost tracker so we get the same accounting the app
        # uses in production (including cache write/read costs).
        from app.services.cost_tracker import scan_cost_context

        result = CaseResult(case_id=case.id, category=case.category)
        with scan_cost_context(scan_job_id=f"eval-{case.id}") as tracker:
            t0 = time.perf_counter()
            try:
                verdict = await self.execute_case(case)
            except Exception as e:  # noqa: BLE001
                verdict = {"error": f"{type(e).__name__}: {e}"}
            result.latency_ms = (time.perf_counter() - t0) * 1000.0

            # Aggregate cost + Anthropic line-items captured during the call.
            summary = tracker.to_summary(include_line_items=True)
            result.cost_usd = float(summary.get("total_usd", 0.0))
            for li in summary.get("line_items", []):
                if li.get("vendor") != "anthropic":
                    continue
                meta = li.get("meta", {})
                result.input_tokens += int(meta.get("input_tokens", 0))
                result.output_tokens += int(meta.get("output_tokens", 0))
                result.cache_creation_tokens += int(meta.get("cache_creation_tokens", 0))
                result.cache_read_tokens += int(meta.get("cache_read_tokens", 0))

        if "error" in verdict:
            result.error = str(verdict["error"])
            return result

        for key in ("is_relevant", "is_match", "score", "is_compliant", "zombie_ad"):
            if key in verdict:
                setattr(result, key, verdict[key])
        if "extras" in verdict:
            result.extras = verdict["extras"]
        return result

    async def run(
        self, manifest: Manifest, *, concurrency: int = 1
    ) -> RunnerResult:
        cases = [c for c in manifest.cases if c.category in self.relevant_categories()]
        out = RunnerResult(runner=self.name, total_cases=len(cases))
        out.model = self._resolve_model_name()

        sem = asyncio.Semaphore(max(1, concurrency))

        async def _bounded(case: FixtureCase) -> CaseResult:
            async with sem:
                return await self._run_one(case)

        results = await asyncio.gather(*[_bounded(c) for c in cases])
        out.cases = list(results)
        return out

    def _resolve_model_name(self) -> str:
        if not self.model_attr:
            return ""
        try:
            from app.services import ai_service
            return getattr(ai_service, self.model_attr, "")
        except Exception:
            return ""
