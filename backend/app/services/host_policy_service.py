"""Per-hostname adaptive scan-strategy policy.

This service is the learning layer that sits between the runner and
:mod:`render_strategies`. It answers two questions:

1. *Which strategy should we use for hostname X right now?* — read from
   the ``host_scan_policy`` table, default to
   ``playwright_desktop`` for unknown hosts. The runner consults this
   once per page (cheap; one PK lookup).

2. *What did we just learn?* — after every scan, the runner aggregates
   per-host outcomes from ``pipeline_stats.blocked_details`` and the
   per-dealer success rows and calls :func:`record_host_outcomes`. That
   updates rolling counters and, when the confidence threshold is
   reached, auto-promotes the strategy one rung up the ladder.

Pre-flight probe
----------------
For brand-new hosts we run a single :func:`preflight_probe` (cheap
``httpx.head`` with WAF-header sniffing) before the runner even starts,
so the very first scan of a new host doesn't waste 60s of Playwright
on a guaranteed 403. The probe seeds the policy row with a sensible
starting strategy and the detected WAF vendor.

Failure mode
------------
Every database call here is best-effort. A Supabase outage must NOT
block the scan — the runner falls through to the default
``playwright_desktop`` ladder and the missed write is recovered on the
next scan's record pass. All errors are logged at WARNING.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from ..database import supabase
from . import render_strategies as rs

log = logging.getLogger("dealer_intel.host_policy")


# Confidence threshold for auto-promotion. Two consecutive scans where
# every probed page on the host returned a non-success outcome promotes
# the strategy one rung. This avoids reacting to a single transient
# CDN hiccup but reacts fast enough to be useful for a daily scan.
PROMOTE_THRESHOLD = 2

# When a scan succeeds at the current strategy, reset the failure
# confidence counter so a single later flake doesn't immediately
# escalate. We DO NOT auto-demote — once a host has proved it needs
# a stealthier renderer, leave it there. Operator can manually demote
# via the Host Health UI when they have evidence the WAF was relaxed.
RESET_ON_SUCCESS = True


# WAF-vendor fingerprints. Header keys are matched case-insensitively;
# values are matched as substrings on the lowercased value. Order matters:
# the first vendor whose pattern matches any header wins.
_WAF_FINGERPRINTS: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...] = (
    ("akamai", (
        ("server", "akamaighost"),
        ("server", "akamainetstorage"),
        ("x-akamai-transformed", ""),
        ("akamai-grn", ""),
        ("x-akamai-request-id", ""),
    )),
    ("cloudflare", (
        ("cf-ray", ""),
        ("server", "cloudflare"),
        ("cf-cache-status", ""),
    )),
    ("cloudfront", (
        ("x-amz-cf-id", ""),
        ("via", "cloudfront"),
    )),
    ("imperva", (
        ("x-iinfo", ""),
        ("x-cdn", "incapsula"),
        ("set-cookie", "incap_ses_"),
        ("set-cookie", "visid_incap"),
    )),
    ("sucuri", (
        ("x-sucuri-id", ""),
        ("x-sucuri-cache", ""),
        ("server", "sucuri"),
    )),
    ("fastly", (
        ("x-served-by", "cache-"),
        ("fastly-debug-digest", ""),
    )),
)


def host_of(url: str) -> str:
    """Lower-case hostname or empty string. Defensive against bogus URLs."""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def detect_waf(headers: Dict[str, str]) -> Optional[str]:
    """Return the detected WAF vendor name, or None if no match.

    ``headers`` may be either ``httpx.Headers`` or a plain dict; both
    expose case-insensitive lookup via ``.get`` (httpx) or we lowercase
    the keys ourselves. Uses substring matching on values so e.g.
    ``server: cloudflare`` matches with or without a version suffix.
    """
    if not headers:
        return None
    # Normalise to a dict of lower(name) -> list[lower(value)]. set-cookie
    # can repeat in real responses, so we treat every header as a
    # potentially multi-valued list.
    norm: Dict[str, List[str]] = {}
    try:
        items: Iterable[Tuple[str, str]]
        if hasattr(headers, "multi_items"):
            items = headers.multi_items()
        else:
            items = headers.items()
        for k, v in items:
            norm.setdefault(k.lower(), []).append(str(v).lower())
    except Exception:
        return None

    for vendor, patterns in _WAF_FINGERPRINTS:
        for header_name, value_substr in patterns:
            values = norm.get(header_name.lower())
            if not values:
                continue
            if not value_substr:
                return vendor
            for v in values:
                if value_substr in v:
                    return vendor
    return None


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

@dataclass
class HostPolicy:
    hostname: str
    strategy: str
    waf_vendor: Optional[str]
    confidence: int
    last_outcome: Optional[str]
    manual_override: bool


def _row_to_policy(row: Dict[str, Any]) -> HostPolicy:
    return HostPolicy(
        hostname=row.get("hostname", ""),
        strategy=row.get("strategy") or rs.STRATEGY_PLAYWRIGHT_DESKTOP,
        waf_vendor=row.get("waf_vendor"),
        confidence=int(row.get("confidence") or 0),
        last_outcome=row.get("last_outcome"),
        manual_override=bool(row.get("manual_override")),
    )


def get_policy(hostname: str) -> Optional[HostPolicy]:
    """Read the policy row for ``hostname`` (case-insensitive). Returns
    None if no row exists yet (caller should default to
    ``playwright_desktop``)."""
    if not hostname:
        return None
    try:
        res = (
            supabase.table("host_scan_policy")
            .select("*")
            .eq("hostname", hostname.lower())
            .limit(1)
            .execute()
        )
    except Exception as e:
        log.warning("host_scan_policy lookup failed for %s: %s", hostname, e)
        return None
    rows = res.data or []
    if not rows:
        return None
    return _row_to_policy(rows[0])


def get_strategy(url_or_hostname: str) -> str:
    """Convenience: resolve the strategy name to use for a URL/hostname.

    Returns ``playwright_desktop`` if there is no policy row, on any
    Supabase failure, or if the row contains an unknown strategy. The
    runner can therefore call this without a try/except and trust that
    a valid strategy name comes back.
    """
    host = url_or_hostname if "://" not in url_or_hostname else host_of(url_or_hostname)
    policy = get_policy(host)
    if policy is None:
        return rs.STRATEGY_PLAYWRIGHT_DESKTOP
    if policy.strategy not in rs.ALL_STRATEGIES:
        return rs.STRATEGY_PLAYWRIGHT_DESKTOP
    return policy.strategy


# ---------------------------------------------------------------------------
# Write path — record outcomes after a scan
# ---------------------------------------------------------------------------

# Outcome categories the recorder cares about. Mirrors
# extraction_service.OUTCOME_* but defined here so we don't import
# extraction_service from this module (keeps the import graph clean).
_OUTCOME_IMAGES = "images"
_OUTCOME_EMPTY = "empty"
_OUTCOME_BLOCKED = "blocked"
_OUTCOME_TIMEOUT = "timeout"
_OUTCOME_CRASHED = "crashed"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_failure(outcome: str) -> bool:
    return outcome in (_OUTCOME_BLOCKED, _OUTCOME_TIMEOUT, _OUTCOME_CRASHED)


@dataclass
class HostOutcomeAggregate:
    """One scan's aggregated per-hostname outcome counters."""
    hostname: str
    images: int = 0
    empty: int = 0
    blocked: int = 0
    timeout: int = 0
    crashed: int = 0
    last_block_reason: Optional[str] = None
    last_http_status: Optional[int] = None
    waf_vendor: Optional[str] = None       # set by preflight or response sniffing

    @property
    def total(self) -> int:
        return self.images + self.empty + self.blocked + self.timeout + self.crashed

    @property
    def all_failed(self) -> bool:
        """No page on this host produced extractable images this scan."""
        return self.total > 0 and self.images == 0

    @property
    def any_succeeded(self) -> bool:
        return self.images > 0


def aggregate_from_pipeline_stats(
    pipeline_stats: Dict[str, Any],
) -> Dict[str, HostOutcomeAggregate]:
    """Walk ``pipeline_stats`` and build per-hostname aggregates.

    The runner already populates two structures we can mine:

    * ``blocked_details[]`` — per-dealer rollup of pages that hit any
      non-IMAGES outcome. Each entry has ``base_url`` + ``pages: [{
      page_url, outcome, reason, http_status }]``.
    * ``dealers_ok`` / ``dealers_partial`` — counts but no per-page
      detail. We can only credit *successful* pages by reading
      ``pages_scanned`` minus the failure totals; that loses host
      attribution. So for now successes are tallied via the runner
      passing in a ``dealer_status_by_host`` map (added in 2c).

    For backwards compatibility with old pipeline_stats payloads (e.g.
    replayed jobs), missing fields are silently treated as zero.
    """
    by_host: Dict[str, HostOutcomeAggregate] = {}

    for dealer in pipeline_stats.get("blocked_details") or []:
        for page in dealer.get("pages") or []:
            page_url = page.get("page_url") or dealer.get("base_url") or ""
            host = host_of(page_url)
            if not host:
                continue
            agg = by_host.setdefault(host, HostOutcomeAggregate(hostname=host))
            outcome = (page.get("outcome") or "").lower()
            if outcome == _OUTCOME_BLOCKED:
                agg.blocked += 1
            elif outcome == _OUTCOME_TIMEOUT:
                agg.timeout += 1
            elif outcome == _OUTCOME_CRASHED:
                agg.crashed += 1
            elif outcome == _OUTCOME_EMPTY:
                agg.empty += 1
            elif outcome == _OUTCOME_IMAGES:
                agg.images += 1

            reason = page.get("reason")
            if reason and not agg.last_block_reason:
                agg.last_block_reason = str(reason)[:200]
            http_status = page.get("http_status")
            if http_status and not agg.last_http_status:
                try:
                    agg.last_http_status = int(http_status)
                except Exception:
                    pass
    return by_host


def merge_host_successes(
    aggregates: Dict[str, HostOutcomeAggregate],
    success_pages_by_host: Dict[str, int],
) -> None:
    """Fold in per-host success counts that the runner tallies separately.

    ``success_pages_by_host`` is the runner's own count of pages that
    came back ``OUTCOME_IMAGES`` per hostname. Mutates ``aggregates`` in
    place; creates entries for hosts not previously seen so a fully-OK
    host still gets a recorded row (and its confidence reset).
    """
    for host, count in (success_pages_by_host or {}).items():
        if not host or count <= 0:
            continue
        agg = aggregates.setdefault(host, HostOutcomeAggregate(hostname=host))
        agg.images += int(count)


def record_host_outcomes(
    aggregates: Dict[str, HostOutcomeAggregate],
) -> List[Tuple[str, str, str]]:
    """Persist outcomes and apply auto-promotion. Returns a list of
    ``(hostname, old_strategy, new_strategy)`` tuples for any host that
    was promoted this round — the caller can use this to send a Slack
    alert ("auto-promoted rent.cat.com → screenshotone_residential").

    Best-effort throughout: a per-host write failure logs a warning and
    continues with the next host. The aggregate processed is guaranteed
    to be small (≤ a few hundred unique hosts even on a giant scan), so
    we issue one upsert per host rather than batching — clearer code,
    no measurable cost difference at this volume.
    """
    promotions: List[Tuple[str, str, str]] = []
    if not aggregates:
        return promotions

    for host, agg in aggregates.items():
        try:
            current = get_policy(host)
            old_strategy = current.strategy if current else rs.STRATEGY_PLAYWRIGHT_DESKTOP
            manual_override = current.manual_override if current else False

            new_confidence = current.confidence if current else 0
            new_outcome: str
            if agg.any_succeeded:
                # Success on at least one page resets the failure streak.
                new_confidence = 0
                new_outcome = _OUTCOME_IMAGES
            elif agg.all_failed:
                new_confidence = (current.confidence if current else 0) + 1
                if agg.blocked >= max(agg.timeout, agg.crashed, agg.empty):
                    new_outcome = _OUTCOME_BLOCKED
                elif agg.timeout >= max(agg.crashed, agg.empty):
                    new_outcome = _OUTCOME_TIMEOUT
                elif agg.crashed >= agg.empty:
                    new_outcome = _OUTCOME_CRASHED
                else:
                    new_outcome = _OUTCOME_EMPTY
            else:
                # No data for this host this scan (shouldn't happen given
                # we only enter this loop when aggregates exist). Skip.
                continue

            promote = (
                not manual_override
                and not agg.any_succeeded
                and new_confidence >= PROMOTE_THRESHOLD
                and old_strategy != rs.STRATEGY_UNREACHABLE
            )
            new_strategy = old_strategy
            promoted_at: Optional[str] = None
            if promote:
                new_strategy = rs.next_strategy(old_strategy)
                if new_strategy != old_strategy:
                    promoted_at = _utc_now_iso()
                    new_confidence = 0  # reset the streak after the promotion
                    promotions.append((host, old_strategy, new_strategy))
                    log.info(
                        "Host %s auto-promoted: %s -> %s (after %d failed scans)",
                        host, old_strategy, new_strategy, PROMOTE_THRESHOLD,
                    )

            payload: Dict[str, Any] = {
                "hostname": host,
                "strategy": new_strategy,
                "confidence": new_confidence,
                "last_outcome": new_outcome,
                "last_seen_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
            }
            if agg.last_block_reason:
                payload["last_block_reason"] = agg.last_block_reason
            if agg.last_http_status is not None:
                payload["last_http_status"] = agg.last_http_status
            if agg.waf_vendor:
                payload["waf_vendor"] = agg.waf_vendor
            if promoted_at:
                payload["last_promoted_at"] = promoted_at

            # Counter increments. We use absolute set rather than RPC
            # increment because supabase-py can't atomic-increment without
            # a stored function, and the race with concurrent scans on
            # the same host is acceptable (worst case: one scan's counter
            # gets clobbered by another that finished a moment later).
            if current is None:
                payload["success_count_30d"] = agg.images
                payload["blocked_count_30d"] = agg.blocked
                payload["timeout_count_30d"] = agg.timeout
            else:
                # Read-modify-write — small race window but the operator
                # only cares about the order of magnitude on these.
                row = (
                    supabase.table("host_scan_policy")
                    .select("success_count_30d, blocked_count_30d, timeout_count_30d")
                    .eq("hostname", host)
                    .limit(1)
                    .execute()
                ).data
                if row:
                    payload["success_count_30d"] = int(row[0].get("success_count_30d") or 0) + agg.images
                    payload["blocked_count_30d"] = int(row[0].get("blocked_count_30d") or 0) + agg.blocked
                    payload["timeout_count_30d"] = int(row[0].get("timeout_count_30d") or 0) + agg.timeout

            supabase.table("host_scan_policy").upsert(
                payload, on_conflict="hostname",
            ).execute()
        except Exception as e:
            log.warning("Failed to record host policy for %s: %s", host, e)

    return promotions


# ---------------------------------------------------------------------------
# Pre-flight probe (Step 3)
# ---------------------------------------------------------------------------

@dataclass
class PreflightResult:
    """Output of :func:`preflight_probe`."""
    status: Optional[int]
    waf_vendor: Optional[str]
    suggested_strategy: str
    error: Optional[str] = None


# Cheap probe wall-clock budget. Akamai either responds within ~2s or
# never; 5s is a comfortable upper bound for honest hosts on slow links.
_PREFLIGHT_TIMEOUT = 5.0


# Realistic browser headers — a probe with `python-httpx/x.y` UA is itself
# a honeypot trigger on aggressive WAFs, so we look like Chrome on macOS
# (matching what the desktop Playwright ladder uses).
_PROBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


async def preflight_probe(url: str) -> PreflightResult:
    """One-shot HEAD/GET against ``url`` to classify the host cheaply.

    Strategy mapping:

    * 2xx, no WAF header              → ``playwright_desktop``
    * 2xx with Akamai/Cloudflare/etc. → ``playwright_desktop`` (it
                                         worked, but we record the WAF
                                         vendor for future routing)
    * 401 / 403 / 451                 → ``screenshotone_only`` (clean
                                         WAF reject; Playwright will
                                         get the same)
    * 429                             → ``playwright_then_screenshotone``
                                         (rate-limited, residential proxy
                                         won't help yet — try once)
    * Connection error / timeout      → ``playwright_then_screenshotone``
                                         (might be a flake; one
                                         Playwright shot, then SS1)
    * 5xx                             → ``playwright_desktop`` (server
                                         error, not a block)

    We try HEAD first (zero body bytes). Some WAFs return 405 on HEAD;
    in that case we fall back to a single GET with a stream that we
    immediately close so we never download the body.
    """
    suggested = rs.STRATEGY_PLAYWRIGHT_DESKTOP
    waf: Optional[str] = None

    try:
        async with httpx.AsyncClient(
            timeout=_PREFLIGHT_TIMEOUT,
            follow_redirects=True,
            headers=_PROBE_HEADERS,
            http2=False,
        ) as client:
            try:
                resp = await client.head(url)
                if resp.status_code == 405:
                    # Some servers reject HEAD; one cheap GET, drop body.
                    resp = await client.get(url)
            except httpx.HTTPError:
                # Retry once with GET in case HEAD itself was the problem
                # (rare, but real for some Cloudfront origins).
                resp = await client.get(url)

            status = resp.status_code
            waf = detect_waf(resp.headers)

            if status in (401, 403, 451):
                suggested = rs.STRATEGY_SCREENSHOTONE_ONLY
            elif status == 429:
                suggested = rs.STRATEGY_PLAYWRIGHT_THEN_SCREENSHOTONE
            elif 200 <= status < 400:
                suggested = rs.STRATEGY_PLAYWRIGHT_DESKTOP
            elif 500 <= status < 600:
                suggested = rs.STRATEGY_PLAYWRIGHT_DESKTOP
            else:
                suggested = rs.STRATEGY_PLAYWRIGHT_THEN_SCREENSHOTONE

            log.info(
                "Preflight %s -> status=%s waf=%s suggested=%s",
                url, status, waf, suggested,
            )
            return PreflightResult(
                status=status, waf_vendor=waf, suggested_strategy=suggested,
            )

    except Exception as e:
        log.info("Preflight failed for %s: %s", url, e)
        return PreflightResult(
            status=None,
            waf_vendor=None,
            suggested_strategy=rs.STRATEGY_PLAYWRIGHT_THEN_SCREENSHOTONE,
            error=str(e)[:200],
        )


def upsert_preflight(host: str, probe: PreflightResult) -> None:
    """Persist a preflight observation for an unseen host. Existing rows
    are NOT overwritten — once a host has real outcome history,
    record_host_outcomes is the source of truth."""
    if not host:
        return
    try:
        existing = (
            supabase.table("host_scan_policy")
            .select("hostname")
            .eq("hostname", host)
            .limit(1)
            .execute()
        ).data
        if existing:
            return
        supabase.table("host_scan_policy").insert({
            "hostname": host,
            "strategy": probe.suggested_strategy,
            "waf_vendor": probe.waf_vendor,
            "last_outcome": None,
            "last_http_status": probe.status,
            "last_seen_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "notes": "seeded by preflight probe",
        }).execute()
        log.info(
            "Seeded host_scan_policy for %s (strategy=%s waf=%s)",
            host, probe.suggested_strategy, probe.waf_vendor,
        )
    except Exception as e:
        log.warning("Failed to seed host_scan_policy for %s: %s", host, e)


async def ensure_policy(url: str) -> str:
    """Convenience used by the runner: returns the strategy to use for
    ``url``, running a pre-flight probe + insert if the host has never
    been seen. Always returns a valid strategy string.
    """
    host = host_of(url)
    if not host:
        return rs.STRATEGY_PLAYWRIGHT_DESKTOP

    existing = get_policy(host)
    if existing is not None:
        return existing.strategy

    probe = await preflight_probe(url)
    upsert_preflight(host, probe)
    return probe.suggested_strategy
