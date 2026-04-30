"""Pluggable render-strategy ladder for dealer-website extraction.

Background
----------
Until Phase 6.5 every dealer page was rendered the same way: Playwright
desktop, retry-on-failure with mobile, fall back to ScreenshotOne if
the host returned an HTTP 403. That works for ~80% of hosts but burns
60-120s of timeouts on Akamai/Cloudflare-protected sites that we
already know are going to fail. Phase 6 added a *learning layer* that
remembers which strategy worked per hostname; Phase 6.5 replaced the
SS1 fallback with **Bright Data Web Unlocker**, the actual answer to
"how do we bypass arbitrary WAF-protected sites" (see
``unlocker_service.py`` for why).

The ladder structure is unchanged. What's different:

* The top of every ladder is now ``_UNLOCKER`` (Bright Data) instead of
  ``_SCREENSHOTONE_*``. The unlocker returns rendered HTML which we
  parse for ``<img>`` tags directly, so it produces ``OUTCOME_IMAGES``
  rather than the screenshot-with-localizer dance SS1 needed.
* Every ladder is at least two rungs. The previous single-rung
  ``screenshotone_residential`` strategy was structurally fragile —
  one provider failure killed all evidence collection on a host. Now
  the worst case is "Playwright failed, BD failed too" → operator sees
  the host as unreachable rather than silently dropping rows.
* The new ``unreachable`` rung is purely flag-only: it still tries the
  unlocker once for evidence but ``host_policy_service`` won't promote
  past it.

Strategy names (single source of truth shared with the SQL CHECK
constraint in migration ``031_replace_screenshotone_with_unlocker.sql``):

============================== =========================================================
name                            attempts in order
============================== =========================================================
playwright_desktop             [Playwright desktop, Playwright mobile, Bright Data]
playwright_mobile_first        [Playwright mobile, Playwright desktop, Bright Data]
playwright_then_unlocker       [Playwright desktop, Bright Data]
unlocker_only                  [Bright Data]
unreachable                    [Bright Data]   (still try once for evidence)
============================== =========================================================

Each attempt returns an :class:`ExtractionResult` so the ladder can
decide whether to stop or keep going. The ladder stops on the first
``OUTCOME_IMAGES`` (real images extracted). Because the unlocker rung
returns ``OUTCOME_IMAGES`` directly when it succeeds (no
screenshot-only intermediate state), the early-stop ``is_screenshot_capture``
short-circuit from the SS1 era is no longer needed for the unlocker —
it's still on the ``RenderAttempt`` protocol for backwards compat in
case a future provider returns evidence-only.

This module deliberately holds no global state. ``host_policy_service``
owns the per-host learning; ``unlocker_service`` owns the API
availability flag; the strategies themselves are pure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Set
from uuid import UUID

log = logging.getLogger("dealer_intel.render_strategies")


# ---------------------------------------------------------------------------
# Strategy names — single source of truth shared with the SQL CHECK constraint
# in migration 031_replace_screenshotone_with_unlocker.sql. Adding a new
# strategy means: append below, add an entry to ``STRATEGY_LADDERS``, and bump
# the SQL CHECK in a follow-up migration.
# ---------------------------------------------------------------------------
STRATEGY_PLAYWRIGHT_DESKTOP = "playwright_desktop"
STRATEGY_PLAYWRIGHT_MOBILE_FIRST = "playwright_mobile_first"
STRATEGY_PLAYWRIGHT_THEN_UNLOCKER = "playwright_then_unlocker"
STRATEGY_UNLOCKER_ONLY = "unlocker_only"
STRATEGY_UNREACHABLE = "unreachable"

ALL_STRATEGIES: List[str] = [
    STRATEGY_PLAYWRIGHT_DESKTOP,
    STRATEGY_PLAYWRIGHT_MOBILE_FIRST,
    STRATEGY_PLAYWRIGHT_THEN_UNLOCKER,
    STRATEGY_UNLOCKER_ONLY,
    STRATEGY_UNREACHABLE,
]

# Stable promotion order (cheap → expensive). The auto-promotion logic in
# ``host_policy_service`` walks this when a host needs to escalate.
PROMOTION_ORDER: List[str] = [
    STRATEGY_PLAYWRIGHT_DESKTOP,
    STRATEGY_PLAYWRIGHT_MOBILE_FIRST,
    STRATEGY_PLAYWRIGHT_THEN_UNLOCKER,
    STRATEGY_UNLOCKER_ONLY,
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
# Each attempt late-imports its underlying service to break the circular
# dependency (``extraction_service`` and ``unlocker_service`` both import
# this module to choose a ladder). Cost figures inform the future
# cost-guardrail layer; in-process Chromium has no per-call $$.

class _PlaywrightAttempt:
    name: str
    mobile: bool
    cost_per_render_usd: float = 0.0
    # When False the ladder must keep trying — Playwright can return
    # OUTCOME_BLOCKED with no evidence and the next rung might recover.
    is_screenshot_capture: bool = False

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


class _UnlockerAttempt:
    """Bright Data Web Unlocker rung.

    Calls Bright Data's REST endpoint, parses the returned HTML for
    images, and inserts each one as a ``discovered_images`` row. Because
    the unlocker returns a rendered DOM (not a screenshot), the result
    can be ``OUTCOME_IMAGES`` directly — no separate cv-localizer pass
    is needed. The actual work lives in :mod:`unlocker_service`.
    """
    name: str = "brightdata_unlocker"
    # PAYG list price as of 2026-04-30. ``cost_tracker.record_unlocker``
    # is the source of truth for billing; this field is informational and
    # used by the future cost-guardrail layer to pick cheaper rungs first.
    cost_per_render_usd: float = 0.0015
    # Not a "screenshot-only" capture in the SS1 sense — it returns real
    # extracted images, so the ladder doesn't need the early-stop
    # short-circuit that SS1 needed.
    is_screenshot_capture: bool = False

    async def render(self, ctx: RenderContext):
        from . import unlocker_service       # late import
        return await unlocker_service.unlock_and_extract(
            url=ctx.url,
            scan_job_id=ctx.scan_job_id,
            distributor_id=ctx.distributor_id,
            seen_srcs=ctx.seen_srcs,
            campaign_assets=ctx.campaign_assets,
        )


# Single concrete attempt instances reused across the ladders below.
# Strategies are just different *orderings* of the same primitives.
_PLAYWRIGHT_DESKTOP = _PlaywrightAttempt(mobile=False, name="playwright_desktop")
_PLAYWRIGHT_MOBILE = _PlaywrightAttempt(mobile=True, name="playwright_mobile")
_UNLOCKER = _UnlockerAttempt()


# Each strategy is just an ordered tuple of attempts. The runner walks
# them until OUTCOME_IMAGES or end of list. Every ladder has at least
# two rungs (with at least two distinct providers across them) so a
# single-rung outage can never silently drop all evidence — this is the
# structural fix for the 2026-04-30 incident where
# ``screenshotone_residential`` had a single broken rung and produced
# zero rows for every Akamai-protected dealer.
STRATEGY_LADDERS: Dict[str, List[RenderAttempt]] = {
    STRATEGY_PLAYWRIGHT_DESKTOP: [
        _PLAYWRIGHT_DESKTOP, _PLAYWRIGHT_MOBILE, _UNLOCKER,
    ],
    STRATEGY_PLAYWRIGHT_MOBILE_FIRST: [
        _PLAYWRIGHT_MOBILE, _PLAYWRIGHT_DESKTOP, _UNLOCKER,
    ],
    STRATEGY_PLAYWRIGHT_THEN_UNLOCKER: [
        _PLAYWRIGHT_DESKTOP, _UNLOCKER,
    ],
    STRATEGY_UNLOCKER_ONLY: [
        # Single rung is acceptable here because:
        #   1. The boot-time smoke test in main.py confirms BD is
        #      authenticating before the API even starts serving;
        #   2. ``unlocker_service.is_available()`` flips off the rung
        #      after auth-style failures so we don't keep paying for
        #      guaranteed errors;
        #   3. ``host_policy_service`` will promote out of this strategy
        #      to ``unreachable`` after PROMOTE_THRESHOLD failures.
        _UNLOCKER,
    ],
    STRATEGY_UNREACHABLE: [
        # Still try once so the report has visual evidence; the
        # recording layer is responsible for not promoting past this
        # rung.
        _UNLOCKER,
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
        the attempt that ran latest on the ladder.
      * A rung whose ``is_screenshot_capture`` flag is True and which
        produced an ``evidence_url`` short-circuits the ladder (a second
        screenshot-only rung wouldn't add information). The current
        unlocker rung is NOT a screenshot capture — it returns real
        images — so this short-circuit doesn't apply to it. Kept for
        forward compat with future evidence-only providers.
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

        # Once an evidence-only rung produces a screenshot, stop. Trying
        # a second evidence-only rung would only add cost without
        # changing what we know about the page. The current unlocker
        # rung is NOT marked as a screenshot capture (it returns real
        # images) so this branch is dormant today, but the protocol
        # supports it for any future provider that returns
        # evidence-only.
        if (
            getattr(attempt, "is_screenshot_capture", False)
            and res.evidence_url is not None
        ):
            log.info(
                "Ladder strategy=%s short-circuit after %s captured evidence",
                strategy, attempt.name,
            )
            return LadderResult(
                final=res,
                attempts=log_attempts,
                succeeded_attempt=None,
            )

    return LadderResult(
        final=best if best is not None else extraction_service.ExtractionResult(),
        attempts=log_attempts,
        succeeded_attempt=None,
    )
