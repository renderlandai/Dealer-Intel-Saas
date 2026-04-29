"""Pluggable render-strategy ladder for dealer-website extraction.

Background
----------
Until tonight every dealer page was rendered the same way: Playwright
desktop, retry-on-failure with mobile, fall back to ScreenshotOne if
the host returned an HTTP 403. That works for ~80% of hosts but burns
60-120s of timeouts on Akamai/Cloudflare-protected sites that we
already know are going to fail. The fix is two-part:

* This module defines a *ladder* of render strategies, each one
  cheaper-but-flakier or pricier-but-stealthier than the next. The
  runner walks the chosen strategy's ordered attempt list until one
  succeeds (returns ``OUTCOME_IMAGES``) or every attempt is exhausted.

* ``host_policy_service`` records which strategy each hostname
  converges on, so subsequent scans skip the doomed attempts. The
  first scan of a brand-new host pays the full discovery cost; every
  scan after that is fast.

Strategy names (single source of truth shared with the SQL CHECK
constraint in migration ``030_host_scan_policy.sql``):

============================== =========================================================
name                            attempts in order
============================== =========================================================
playwright_desktop             [Playwright desktop, Playwright mobile,
                                ScreenshotOne datacenter, ScreenshotOne residential]
playwright_mobile_first        [Playwright mobile, Playwright desktop,
                                ScreenshotOne datacenter, ScreenshotOne residential]
playwright_then_screenshotone  [Playwright desktop, ScreenshotOne datacenter,
                                ScreenshotOne residential]
screenshotone_only             [ScreenshotOne datacenter, ScreenshotOne residential]
screenshotone_residential      [ScreenshotOne residential]
unreachable                    [ScreenshotOne residential]   (still try once for evidence)
============================== =========================================================

Each attempt returns an :class:`ExtractionResult` so the ladder can
decide whether to stop or keep going. The ladder stops on the first
``OUTCOME_IMAGES`` (real images extracted) and otherwise returns the
best-evidence result it has seen — typically a screenshot from the
last attempt that produced one — so the user is never left with a
completely empty row.

This module deliberately holds no global state. ``host_policy_service``
owns the per-host learning; the strategies themselves are pure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Set
from uuid import UUID

log = logging.getLogger("dealer_intel.render_strategies")


# ---------------------------------------------------------------------------
# Strategy names — single source of truth shared with the SQL CHECK constraint
# in migration 030_host_scan_policy.sql. Adding a new strategy means: append
# below, add an entry to ``STRATEGY_LADDERS``, and bump the SQL CHECK in a
# follow-up migration.
# ---------------------------------------------------------------------------
STRATEGY_PLAYWRIGHT_DESKTOP = "playwright_desktop"
STRATEGY_PLAYWRIGHT_MOBILE_FIRST = "playwright_mobile_first"
STRATEGY_PLAYWRIGHT_THEN_SCREENSHOTONE = "playwright_then_screenshotone"
STRATEGY_SCREENSHOTONE_ONLY = "screenshotone_only"
STRATEGY_SCREENSHOTONE_RESIDENTIAL = "screenshotone_residential"
STRATEGY_UNREACHABLE = "unreachable"

ALL_STRATEGIES: List[str] = [
    STRATEGY_PLAYWRIGHT_DESKTOP,
    STRATEGY_PLAYWRIGHT_MOBILE_FIRST,
    STRATEGY_PLAYWRIGHT_THEN_SCREENSHOTONE,
    STRATEGY_SCREENSHOTONE_ONLY,
    STRATEGY_SCREENSHOTONE_RESIDENTIAL,
    STRATEGY_UNREACHABLE,
]

# Stable promotion order (cheap → expensive). The auto-promotion logic in
# ``host_policy_service`` walks this when a host needs to escalate.
PROMOTION_ORDER: List[str] = [
    STRATEGY_PLAYWRIGHT_DESKTOP,
    STRATEGY_PLAYWRIGHT_MOBILE_FIRST,
    STRATEGY_PLAYWRIGHT_THEN_SCREENSHOTONE,
    STRATEGY_SCREENSHOTONE_ONLY,
    STRATEGY_SCREENSHOTONE_RESIDENTIAL,
    STRATEGY_UNREACHABLE,
]


def next_strategy(current: str) -> str:
    """Return the strategy one step up the promotion ladder.

    The terminal ``unreachable`` rung is sticky — calling this on it
    returns ``unreachable`` again. Unknown strategies are normalised to
    the cheapest tier.
    """
    if current not in PROMOTION_ORDER:
        return STRATEGY_PLAYWRIGHT_DESKTOP
    idx = PROMOTION_ORDER.index(current)
    if idx + 1 >= len(PROMOTION_ORDER):
        return current
    return PROMOTION_ORDER[idx + 1]


# ---------------------------------------------------------------------------
# Render context (immutable inputs per page)
# ---------------------------------------------------------------------------

@dataclass
class RenderContext:
    """Inputs every attempt receives.

    ``seen_srcs`` is mutable on purpose: it accumulates image src URLs
    across viewport switches within a single page so we never insert the
    same image twice. The ladder threads the same set through every
    attempt.
    """
    url: str
    scan_job_id: UUID
    distributor_id: Optional[UUID] = None
    campaign_assets: Optional[List[Dict[str, Any]]] = None
    seen_srcs: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# RenderAttempt protocol — one rung the ladder calls
# ---------------------------------------------------------------------------

class RenderAttempt(Protocol):
    """One executable step. Stateless; per-attempt state lives on
    :class:`RenderContext`."""
    name: str
    cost_per_render_usd: float

    async def render(self, ctx: RenderContext) -> "ExtractionResult":  # noqa: F821
        ...


# ---------------------------------------------------------------------------
# Concrete attempts
# ---------------------------------------------------------------------------
#
# Each attempt late-imports ``extraction_service`` to break the circular
# dependency (``extraction_service`` imports this module to choose a ladder).
# Cost figures inform the future cost-guardrail layer; in-process Chromium
# has no per-call $$.

class _PlaywrightAttempt:
    name: str
    mobile: bool
    cost_per_render_usd: float = 0.0

    def __init__(self, mobile: bool, name: str):
        self.mobile = mobile
        self.name = name

    async def render(self, ctx: RenderContext):
        from . import extraction_service  # late import; see module docstring
        return await extraction_service._extract_from_viewport(
            url=ctx.url,
            scan_job_id=ctx.scan_job_id,
            distributor_id=ctx.distributor_id,
            mobile=self.mobile,
            seen_srcs=ctx.seen_srcs,
            campaign_assets=ctx.campaign_assets,
        )


class _ScreenshotOneAttempt:
    name: str
    cost_per_render_usd: float
    use_residential_proxy: bool

    def __init__(self, *, residential: bool, name: str, cost: float):
        self.use_residential_proxy = residential
        self.name = name
        self.cost_per_render_usd = cost

    async def render(self, ctx: RenderContext):
        from . import extraction_service       # late import
        from . import screenshot_service       # late import

        overrides: Dict[str, Any] = {}
        if self.use_residential_proxy:
            # ScreenshotOne residential pool: same API, residential IP egress.
            # Adds ~$0.006/render on top of the base $0.004 charge. Empirically
            # the only thing that defeats Akamai's IP-reputation block from
            # a datacenter source.
            overrides["proxy"] = "residential"
            overrides["delay"] = 8     # let any challenge-page JS clear

        try:
            shot_url = await screenshot_service.capture_and_upload(
                ctx.url, ctx.scan_job_id, **overrides,
            )
        except Exception as e:
            log.warning(
                "ScreenshotOne (%s) raised for %s: %s",
                self.name, ctx.url, e,
            )
            shot_url = None

        if shot_url:
            log.info("%s captured %s", self.name, ctx.url)
            return extraction_service.ExtractionResult(
                count=0,
                evidence_url=shot_url,
                # Marked BLOCKED (not IMAGES) because we did NOT extract
                # individual images — only a full-page screenshot. Truthful
                # metrics depend on this distinction.
                outcome=extraction_service.OUTCOME_BLOCKED,
                block_reason=f"captured_via_{self.name}",
            )

        return extraction_service.ExtractionResult(
            count=0,
            evidence_url=None,
            outcome=extraction_service.OUTCOME_BLOCKED,
            block_reason=f"{self.name}_failed",
        )


# Single concrete attempt instances reused across the ladders below.
# Strategies are just different *orderings* of the same three primitives.
_PLAYWRIGHT_DESKTOP = _PlaywrightAttempt(mobile=False, name="playwright_desktop")
_PLAYWRIGHT_MOBILE = _PlaywrightAttempt(mobile=True, name="playwright_mobile")
_SCREENSHOTONE_DC = _ScreenshotOneAttempt(
    residential=False, name="screenshotone_datacenter", cost=0.004,
)
_SCREENSHOTONE_RES = _ScreenshotOneAttempt(
    residential=True, name="screenshotone_residential", cost=0.010,
)


# Each strategy is just an ordered tuple of attempts. The runner walks
# them until OUTCOME_IMAGES or end of list.
STRATEGY_LADDERS: Dict[str, List[RenderAttempt]] = {
    STRATEGY_PLAYWRIGHT_DESKTOP: [
        _PLAYWRIGHT_DESKTOP, _PLAYWRIGHT_MOBILE,
        _SCREENSHOTONE_DC, _SCREENSHOTONE_RES,
    ],
    STRATEGY_PLAYWRIGHT_MOBILE_FIRST: [
        _PLAYWRIGHT_MOBILE, _PLAYWRIGHT_DESKTOP,
        _SCREENSHOTONE_DC, _SCREENSHOTONE_RES,
    ],
    STRATEGY_PLAYWRIGHT_THEN_SCREENSHOTONE: [
        _PLAYWRIGHT_DESKTOP, _SCREENSHOTONE_DC, _SCREENSHOTONE_RES,
    ],
    STRATEGY_SCREENSHOTONE_ONLY: [
        _SCREENSHOTONE_DC, _SCREENSHOTONE_RES,
    ],
    STRATEGY_SCREENSHOTONE_RESIDENTIAL: [
        _SCREENSHOTONE_RES,
    ],
    STRATEGY_UNREACHABLE: [
        # Still try once so the report has visual evidence; the recording
        # layer is responsible for not promoting past this rung.
        _SCREENSHOTONE_RES,
    ],
}


# ---------------------------------------------------------------------------
# Ladder runner
# ---------------------------------------------------------------------------

@dataclass
class LadderAttempt:
    """One step's outcome. Aggregated into ``LadderResult.attempts`` so
    the post-scan aggregation hook (and the operator UI) can see exactly
    what was tried."""
    attempt: str
    outcome: str
    block_reason: Optional[str]
    http_status: Optional[int]
    count: int


@dataclass
class LadderResult:
    """End-to-end result for one page across all attempted rungs."""
    final: "ExtractionResult"           # noqa: F821
    attempts: List[LadderAttempt]
    succeeded_attempt: Optional[str]    # attempt that produced OUTCOME_IMAGES, if any


async def run_ladder(
    ctx: RenderContext,
    strategy: str = STRATEGY_PLAYWRIGHT_DESKTOP,
) -> LadderResult:
    """Walk the chosen strategy's attempts until success or exhaustion.

    Behaviour:
      * Stops on the first ``OUTCOME_IMAGES`` (real extraction) — that is
        the win condition.
      * Otherwise keeps going through every later rung. The final result
        is whichever attempt produced the most informative evidence:
        prefer ``OUTCOME_IMAGES`` (none here, by definition), else prefer
        any result with a screenshot (``evidence_url``); break ties by
        the attempt that ran latest on the ladder (residential beats
        datacenter beats Playwright).
      * Unknown strategy names fall back to the
        ``playwright_desktop`` ladder so a corrupt policy row never
        silently disables scanning.
    """
    from . import extraction_service  # for ExtractionResult / OUTCOME_*

    attempts_to_run = STRATEGY_LADDERS.get(
        strategy, STRATEGY_LADDERS[STRATEGY_PLAYWRIGHT_DESKTOP],
    )

    log_attempts: List[LadderAttempt] = []
    best: Optional[extraction_service.ExtractionResult] = None
    best_idx: int = -1

    for idx, attempt in enumerate(attempts_to_run):
        log.info(
            "Ladder strategy=%s step %d/%d (%s) for %s",
            strategy, idx + 1, len(attempts_to_run), attempt.name, ctx.url,
        )
        try:
            res = await attempt.render(ctx)
        except Exception as e:
            log.error(
                "Attempt %s crashed on %s: %s",
                attempt.name, ctx.url, e, exc_info=True,
            )
            res = extraction_service.ExtractionResult(
                count=0,
                outcome=extraction_service.OUTCOME_CRASHED,
                block_reason=f"{attempt.name}: {str(e)[:120]}",
            )

        log_attempts.append(LadderAttempt(
            attempt=attempt.name,
            outcome=res.outcome,
            block_reason=res.block_reason,
            http_status=res.http_status,
            count=res.count,
        ))

        # Track best-evidence result.
        if best is None:
            best, best_idx = res, idx
        elif res.outcome == extraction_service.OUTCOME_IMAGES:
            best, best_idx = res, idx
        elif (
            res.evidence_url
            and (best.evidence_url is None or idx > best_idx)
        ):
            best, best_idx = res, idx

        if res.outcome == extraction_service.OUTCOME_IMAGES:
            return LadderResult(
                final=res,
                attempts=log_attempts,
                succeeded_attempt=attempt.name,
            )

    return LadderResult(
        final=best if best is not None else extraction_service.ExtractionResult(),
        attempts=log_attempts,
        succeeded_attempt=None,
    )
