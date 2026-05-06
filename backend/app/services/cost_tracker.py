"""Per-scan vendor cost tracking.

A `ScanCostTracker` accumulates line items for every paid API call made
during a scan (Anthropic, Apify, SerpApi, ScreenshotOne).  At the end of
the scan, the tracker is serialized into ``scan_jobs.cost_usd`` and
``scan_jobs.cost_breakdown`` (and also nested under ``pipeline_stats.cost``).

The tracker is exposed via a :class:`contextvars.ContextVar` so any
service module deep in the call stack can record usage without having
the tracker passed through its function signature.  Because each scan
runs in its own ``asyncio.create_task`` (see ``app/tasks.py``), the
context is automatically isolated between concurrent scans.
"""
from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("dealer_intel.cost")


# ---------------------------------------------------------------------------
# Pricing tables (USD).  These are the published list prices for the vendors
# we use; override via env if your contracted rates differ.
# ---------------------------------------------------------------------------

# Anthropic — per 1M tokens.
# Source: https://www.anthropic.com/pricing
# Opus 4.5+ moved to $5/$25 per MTok (vs original Opus 4 at $15/$75).
# Opus 4.7 (Apr 2026) kept the same pricing as 4.6.
ANTHROPIC_PRICING_PER_MTOK: Dict[str, Dict[str, float]] = {
    # Opus family
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4": {"input": 15.0, "output": 75.0},  # legacy Opus 4
    # Sonnet family
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    # Haiku family
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-haiku-4": {"input": 1.0, "output": 5.0},
}
# Fallback when an unknown model slug is reported — bias high so we never
# silently undercount.
ANTHROPIC_DEFAULT_PRICING = {"input": 5.0, "output": 25.0}

# Prompt caching multipliers (Anthropic ephemeral 5-min cache).
# Source: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
#   - Cache writes:  1.25x base input rate
#   - Cache reads:   0.10x base input rate (90% discount)
#   - Regular input: 1.00x base input rate
ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25
ANTHROPIC_CACHE_READ_MULTIPLIER = 0.10

# SerpApi — per request.  Production plan is ~$0.005/req at the time of
# writing.  Override via SERPAPI_COST_PER_REQUEST_USD env var if needed.
SERPAPI_DEFAULT_COST_PER_REQUEST_USD = 0.005

# ScreenshotOne — per render.  Pay-as-you-go is ~$0.002/screenshot for
# 1080p; full-page retina (what we use) is closer to $0.004.  We default
# to the higher value so estimates are conservative.
SCREENSHOTONE_DEFAULT_COST_PER_RENDER_USD = 0.004


def _pricing_from_env() -> Dict[str, float]:
    """Read overrides from environment variables (lazy, no settings dep)."""
    import os

    out: Dict[str, float] = {
        "serpapi_per_request": SERPAPI_DEFAULT_COST_PER_REQUEST_USD,
        "screenshotone_per_render": SCREENSHOTONE_DEFAULT_COST_PER_RENDER_USD,
    }
    try:
        if v := os.getenv("SERPAPI_COST_PER_REQUEST_USD"):
            out["serpapi_per_request"] = float(v)
        if v := os.getenv("SCREENSHOTONE_COST_PER_RENDER_USD"):
            out["screenshotone_per_render"] = float(v)
    except ValueError:
        log.warning("Invalid pricing override env var — using defaults")
    return out


def _anthropic_rate(model: str) -> Dict[str, float]:
    """Return (input, output) per-MTok USD rates for a model slug."""
    if not model:
        return ANTHROPIC_DEFAULT_PRICING
    # Try exact match, then case-insensitive prefix match.
    if model in ANTHROPIC_PRICING_PER_MTOK:
        return ANTHROPIC_PRICING_PER_MTOK[model]
    low = model.lower()
    for key, rate in ANTHROPIC_PRICING_PER_MTOK.items():
        if low.startswith(key.lower()):
            return rate
    return ANTHROPIC_DEFAULT_PRICING


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

@dataclass
class _LineItem:
    vendor: str
    op: str
    units: float
    unit: str
    unit_cost_usd: float
    cost_usd: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "vendor": self.vendor,
            "op": self.op,
            "units": self.units,
            "unit": self.unit,
            "unit_cost_usd": self.unit_cost_usd,
            "cost_usd": self.cost_usd,
            "meta": self.meta,
        }


class ScanCostTracker:
    """Mutable bag of cost line items for one scan."""

    def __init__(self, scan_job_id: Optional[str] = None) -> None:
        self.scan_job_id = str(scan_job_id) if scan_job_id else None
        self._items: List[_LineItem] = []
        self._pricing = _pricing_from_env()

    # -- low-level ---------------------------------------------------------

    def record(
        self,
        vendor: str,
        op: str,
        units: float,
        unit: str,
        unit_cost_usd: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> float:
        cost = round(float(units) * float(unit_cost_usd), 6)
        self._items.append(_LineItem(
            vendor=vendor, op=op, units=float(units), unit=unit,
            unit_cost_usd=float(unit_cost_usd), cost_usd=cost,
            meta=meta or {},
        ))
        return cost

    # -- vendor-specific helpers ------------------------------------------

    def record_anthropic(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        op: str = "messages.create",
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Record one Anthropic call.

        ``input_tokens`` is the number of *uncached* input tokens billed at
        the regular rate.  ``cache_creation_tokens`` is the prefix that was
        written to the ephemeral cache (billed at 1.25x).  ``cache_read_tokens``
        is the prefix served from cache on this call (billed at 0.10x).

        The Anthropic API returns these fields separately on
        ``response.usage`` so each is billed independently.
        """
        rate = _anthropic_rate(model)
        in_cost = (input_tokens / 1_000_000.0) * rate["input"]
        cache_write_cost = (
            cache_creation_tokens / 1_000_000.0
        ) * rate["input"] * ANTHROPIC_CACHE_WRITE_MULTIPLIER
        cache_read_cost = (
            cache_read_tokens / 1_000_000.0
        ) * rate["input"] * ANTHROPIC_CACHE_READ_MULTIPLIER
        out_cost = (output_tokens / 1_000_000.0) * rate["output"]
        total = round(in_cost + cache_write_cost + cache_read_cost + out_cost, 6)

        total_input = int(input_tokens) + int(cache_creation_tokens) + int(cache_read_tokens)
        self._items.append(_LineItem(
            vendor="anthropic",
            op=op,
            units=float(total_input + output_tokens),
            unit="tokens",
            unit_cost_usd=0.0,  # variable; see meta
            cost_usd=total,
            meta={
                "model": model,
                "input_tokens": int(input_tokens),
                "cache_creation_tokens": int(cache_creation_tokens),
                "cache_read_tokens": int(cache_read_tokens),
                "output_tokens": int(output_tokens),
                "input_cost_usd": round(in_cost, 6),
                "cache_write_cost_usd": round(cache_write_cost, 6),
                "cache_read_cost_usd": round(cache_read_cost, 6),
                "output_cost_usd": round(out_cost, 6),
                "rate_input_per_mtok": rate["input"],
                "rate_output_per_mtok": rate["output"],
            },
        ))
        return total

    def record_apify_run(
        self,
        actor_or_task: str,
        run_id: str,
        usage_total_usd: Optional[float],
        items_returned: Optional[int] = None,
    ) -> float:
        """Record a single Apify actor/task run.

        Apify returns the exact billed cost on the run object as
        ``usageTotalUsd``.  We trust that value and store it verbatim.
        """
        cost = round(float(usage_total_usd or 0.0), 6)
        self._items.append(_LineItem(
            vendor="apify",
            op="actor_run",
            units=1.0,
            unit="run",
            unit_cost_usd=cost,
            cost_usd=cost,
            meta={
                "actor": actor_or_task,
                "run_id": run_id,
                "items_returned": items_returned,
            },
        ))
        return cost

    def record_serpapi(self, requests: int = 1, advertiser_id: Optional[str] = None) -> float:
        rate = self._pricing["serpapi_per_request"]
        cost = round(rate * requests, 6)
        self._items.append(_LineItem(
            vendor="serpapi",
            op="search",
            units=float(requests),
            unit="request",
            unit_cost_usd=rate,
            cost_usd=cost,
            meta={"advertiser_id": advertiser_id} if advertiser_id else {},
        ))
        return cost

    def record_screenshotone(self, renders: int = 1, target: Optional[str] = None) -> float:
        rate = self._pricing["screenshotone_per_render"]
        cost = round(rate * renders, 6)
        self._items.append(_LineItem(
            vendor="screenshotone",
            op="capture",
            units=float(renders),
            unit="render",
            unit_cost_usd=rate,
            cost_usd=cost,
            meta={"target": target[:200]} if target else {},
        ))
        return cost

    # -- aggregation -------------------------------------------------------

    @property
    def total_usd(self) -> float:
        return round(sum(li.cost_usd for li in self._items), 4)

    def by_vendor(self) -> Dict[str, float]:
        agg: Dict[str, float] = {}
        for li in self._items:
            agg[li.vendor] = round(agg.get(li.vendor, 0.0) + li.cost_usd, 6)
        return agg

    def to_summary(self, include_line_items: bool = True) -> Dict[str, Any]:
        return {
            "total_usd": self.total_usd,
            "by_vendor": self.by_vendor(),
            "line_items": [li.as_dict() for li in self._items] if include_line_items else [],
            "line_item_count": len(self._items),
        }


# ---------------------------------------------------------------------------
# Context propagation
# ---------------------------------------------------------------------------

_current: contextvars.ContextVar[Optional[ScanCostTracker]] = contextvars.ContextVar(
    "current_scan_cost_tracker", default=None,
)


def get_tracker() -> Optional[ScanCostTracker]:
    """Return the tracker bound to the current async context, if any."""
    return _current.get()


def record_anthropic(
    model: str,
    input_tokens: int,
    output_tokens: int,
    op: str = "messages.create",
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """Convenience: record Anthropic usage on the active tracker (no-op if absent)."""
    t = _current.get()
    if t is None:
        return
    try:
        t.record_anthropic(
            model,
            input_tokens,
            output_tokens,
            op=op,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
        )
    except Exception as e:
        log.warning("Cost record (anthropic) failed: %s", e)


def record_apify_run(actor_or_task: str, run_id: str, usage_total_usd: Optional[float], items_returned: Optional[int] = None) -> None:
    t = _current.get()
    if t is None:
        return
    try:
        t.record_apify_run(actor_or_task, run_id, usage_total_usd, items_returned)
    except Exception as e:
        log.warning("Cost record (apify) failed: %s", e)


def record_serpapi(requests: int = 1, advertiser_id: Optional[str] = None) -> None:
    t = _current.get()
    if t is None:
        return
    try:
        t.record_serpapi(requests=requests, advertiser_id=advertiser_id)
    except Exception as e:
        log.warning("Cost record (serpapi) failed: %s", e)


def record_screenshotone(renders: int = 1, target: Optional[str] = None) -> None:
    t = _current.get()
    if t is None:
        return
    try:
        t.record_screenshotone(renders=renders, target=target)
    except Exception as e:
        log.warning("Cost record (screenshotone) failed: %s", e)


class scan_cost_context:
    """Context manager that binds a fresh tracker to the current async context.

    Usage::

        with scan_cost_context(scan_job_id) as tracker:
            await run_scan(...)
            persist(tracker.to_summary())
    """

    def __init__(self, scan_job_id: Optional[str] = None) -> None:
        self.tracker = ScanCostTracker(scan_job_id)
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> ScanCostTracker:
        self._token = _current.set(self.tracker)
        return self.tracker

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            try:
                _current.reset(self._token)
            except ValueError:
                # Tracker context lifetime crossed task boundaries;
                # safe to ignore — the var simply stays unset.
                pass
            self._token = None
