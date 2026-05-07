"""
Apify Meta Ad Library integration for Facebook & Instagram ad scraping.

Backed by the ``whoareyouanas/meta-ad-scraper`` actor. That actor only
accepts a single search per run (one ``targetUrl``, one ``pageId``, or
one ``searchQuery``), so we fan out — one actor run per dealer page —
and merge the results before handing them to the matcher.

Pipeline overview:

    1. ``_resolve_facebook_page_ids_batch`` turns each dealer's stored
       Facebook URL (slug form, e.g. ``facebook.com/somedealer``) into
       the numeric page ID the actor needs. Four tiers, in priority
       order:
         a) In-process cache (``_PAGE_ID_CACHE``).
         b) Persisted ``distributors.facebook_page_id`` column
            (steady state — see migration ``032``).
         c) Anonymous httpx probe of ``m.facebook.com/<slug>``.
         d) Headless Playwright render of ``m.facebook.com/<slug>``,
            extracting the numeric ID from JS-rendered meta tags +
            inline JSON. Used only when (a)-(c) all miss; results
            are persisted back to the distributor row so the next
            scan hits tier (b) and pays nothing.
    2. ``_run_actor_for_page`` starts one actor run per resolved
       dealer, polls until it finishes, and pulls the dataset items.
    3. Each ad is annotated with the source ``page_url`` so the
       distributor mapping is exact (no fuzzy brand-string matching
       across multiple dealers running in the same scan).
    4. Image URL resolution has a 3-tier fallback:
         a) ``imageUrls: [{"url": ...}]`` from the actor (preferred)
         b) ``videoUrls: [{"url": ..., "duration": ...}]`` (poster/thumb)
         c) Playwright visits the ad's ``adUrl`` (or a synthesised
            ``facebook.com/ads/library/?id=<adId>``) and extracts the
            rendered creative

Each discovered ad image is inserted as a ``discovered_images`` row so
the existing matching pipeline (hash → CLIP → Haiku → Opus) processes
it like any other discovered image.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlparse, parse_qs
from uuid import UUID

import httpx

from ..config import get_settings
from ..database import supabase
from .bulk_writers import DiscoveredImageBuffer

log = logging.getLogger("dealer_intel.apify_meta")

settings = get_settings()

APIFY_BASE = "https://api.apify.com/v2"
ACTOR_ID = "whoareyouanas~meta-ad-scraper"

# Apify run statuses we treat as terminal (the run will not progress
# further, regardless of whether it succeeded).
_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
# Poll cadence and ceiling are configurable via settings — Meta Ad
# Library runs for high-ad-volume dealers can take 10-15 minutes.
_POLL_INTERVAL_SEC = settings.apify_poll_interval_seconds
_MAX_POLL_TIME_SEC = settings.apify_max_poll_seconds

# Playwright fallback settings (shared with the slug→pageId resolver).
_PW_AD_LIBRARY_TIMEOUT = 20_000  # 20s page load timeout
_PW_CONCURRENCY = 3  # max parallel browser pages for fallback

# ---------------------------------------------------------------------------
# Slug → numeric page ID resolution
# ---------------------------------------------------------------------------
#
# The ``whoareyouanas/meta-ad-scraper`` actor accepts only one
# search per run, identified by ``pageId`` (numeric), ``targetUrl``
# (already-formed Ad Library URL containing ``view_all_page_id``), or
# a free-text ``searchQuery``. Our distributor table only stores the
# slug form (``facebook.com/somedealer``), so we resolve slug → pageId
# at scan time.
#
# Only patterns that are PAGE-typed by Facebook itself are kept.
# Looser patterns (``"actorID"``, ``"entity_id"``, ``"page_id"``,
# ``"profile_id"``, ``/profile.php?id=...``) were tried in the
# 2026-05-07 morning deploy and produced false positives — they
# match user IDs, viewer session IDs, and unrelated entities embedded
# in Facebook's logged-out shell. Verified in production by feeding
# a resolved 15-digit ID to the meta-ad-scraper, which surfaced an
# Ad Library page where the transparency block read literally
# ``ID: undefined`` (Meta's signal that the supplied
# ``view_all_page_id`` is not a Page entity in their graph).
#
# These four patterns are documented page deep-link / page-keyed
# JSON fields. If none of them match, we treat the dealer as
# unresolvable (skip-with-warning) rather than fall through to a
# guess, which is the failure mode that produced the bad cache.

_PAGE_ID_PATTERNS = [
    re.compile(r'al:android:url"\s*content="fb://page/\?id=(\d+)"'),
    re.compile(r'android-app://com\.facebook\.katana/fb/page/\?id=(\d+)'),
    re.compile(r'"pageID"\s*:\s*"(\d+)"'),
    re.compile(r'al:ios:url"\s*content="fb://profile/(\d+)"'),
]

# og:url canonical extraction. Facebook stamps this on every
# server-rendered page with the page's CANONICAL vanity slug, so it
# acts as ground truth for "what page did Playwright actually load".
# We use it to verify the rendered DOM corresponds to the dealer
# slug we asked for (not a login redirect, a logged-out wall pointing
# at /people, an interstitial, or an entirely different page).
_OG_URL_PATTERN = re.compile(
    r'<meta[^>]+property="og:url"[^>]+content="https?://[^/]*facebook\.com/([^/?"#]+)',
    re.IGNORECASE,
)

# og:title extraction. Facebook stamps the page's display name on every
# server-rendered page; we capture it during the same render that does
# the og:url identity check, then feed it as the search query for the
# meta-ad-scraper actor's keyword-search URL form. This is the path
# that side-steps the Ad-Library-vs-profile-graph namespace mismatch
# (see migration 034 for the full diagnosis).
_OG_TITLE_PATTERN = re.compile(
    r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
    re.IGNORECASE,
)

# Lightweight in-process caches for a single scan run. Resolving the
# same dealer twice within seconds is wasteful and slightly increases
# the chance of triggering Meta's bot heuristics. Cleared at process
# restart; persisted equivalents live on the distributors row
# (``facebook_page_id`` per migration 032, ``facebook_page_name`` per
# migration 034).
_PAGE_ID_CACHE: Dict[str, str] = {}
_PAGE_NAME_CACHE: Dict[str, str] = {}


# Pattern used to strip a trailing " | <Location>" or " - <Location>"
# from an og:title. Facebook formats business-page titles as
# "<Page Name> | <City State>" or "<Page Name> - <Tagline> | <City>".
# We want just "<Page Name>" / "<Page Name> - <Tagline>" for the search
# query — including the city makes the keyword search miss when the
# advertiser is searched for at the country level (which is how Ad
# Library scopes our scans).
_TITLE_LOCATION_SUFFIX = re.compile(
    r"\s*\|\s*[^|]+$",  # everything from the LAST " | " onward
)


def _extract_og_title(html: str) -> Optional[str]:
    """Return the value of ``<meta property="og:title">`` if present.

    HTML-decoded for the few entities Facebook actually emits in
    titles (``&#xb7;`` and ``&amp;`` are the common ones). Returns
    ``None`` for any input where the meta tag isn't present (login
    walls, interstitials, etc.).
    """
    m = _OG_TITLE_PATTERN.search(html)
    if not m:
        return None
    raw = m.group(1)
    return (
        raw.replace("&amp;", "&")
        .replace("&#xb7;", "·")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .strip()
    )


def _clean_page_name(title: str) -> str:
    """Strip the trailing location suffix Facebook appends to og:title.

    Examples:
        "Yancey Rents - The Cat Rental Store | Austell GA"
            → "Yancey Rents - The Cat Rental Store"
        "Carolina Cat | Charlotte, NC"
            → "Carolina Cat"
        "Holt CAT"
            → "Holt CAT"  (no change — no suffix to strip)

    The dash-separated pattern ("Name - Tagline") is left intact
    because the dash is part of the page's display name, not a
    location separator. Facebook only appends the city in the form
    " | …" so that's the only suffix we strip.
    """
    if not title:
        return ""
    cleaned = _TITLE_LOCATION_SUFFIX.sub("", title).strip()
    # Defensive: if the strip would have eaten everything, fall back
    # to the raw title rather than an empty string.
    return cleaned or title.strip()


# Characters dropped before fuzzy-comparing a dealer's expected name
# against the actor's reported pageName for post-filter purposes.
# Spaces and most punctuation differ across renderings of the same
# brand (e.g. "YanceyRents" slug vs. "Yancey Rents - The Cat Rental
# Store" og:title); normalising to lowercase alphanumerics before
# substring comparison keeps the filter robust without resorting to
# heavyweight fuzzy-string libraries.
_NAME_NORMALIZE = re.compile(r"[^a-z0-9]+")


def _normalize_for_match(value: str) -> str:
    """Lowercase + alphanumeric-only, for cross-rendering name comparison."""
    if not value:
        return ""
    return _NAME_NORMALIZE.sub("", value.lower())


def _name_matches_dealer(
    actor_page_name: Optional[str],
    expected_name: Optional[str],
    expected_slug: Optional[str],
) -> bool:
    """Return True if the actor's reported ``pageName`` plausibly
    belongs to the dealer we asked about.

    Used as a post-filter on actor results when we ran in keyword-
    search mode — the keyword query can return ads from any advertiser
    whose name contains the search string (e.g. searching "Yancey
    Rents" can also return an unrelated "Yancey Rentals LLC" ad).
    Because the actor returns ``pageName`` on every ad, we drop ads
    whose page name doesn't match either the expected display name
    or the slug.

    Match rule (any one is sufficient):
        1. Normalised expected_name is a substring of normalised
           actor_page_name (or vice versa).
        2. Normalised expected_slug is a substring of normalised
           actor_page_name.
        3. Both inputs are missing/empty (no filter possible — fail
           open so we don't drop every ad on a metadata gap).

    Matching is case- and punctuation-insensitive; strings are
    normalised to lowercase alphanumerics first. This handles the
    common variations: "Yancey Rents" vs. "yanceyrents" vs.
    "Yancey Rents - The Cat Rental Store".
    """
    if not actor_page_name:
        return False

    actor_norm = _normalize_for_match(actor_page_name)
    if not actor_norm:
        return False

    expected_name_norm = _normalize_for_match(expected_name or "")
    expected_slug_norm = _normalize_for_match(expected_slug or "")

    if not expected_name_norm and not expected_slug_norm:
        return True  # no signal to filter on; fail open

    if expected_name_norm and (
        expected_name_norm in actor_norm or actor_norm in expected_name_norm
    ):
        return True
    if expected_slug_norm and expected_slug_norm in actor_norm:
        return True
    return False


async def _http_resolve_page_meta(
    slug: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Free first-pass resolver: a plain GET against facebook.com/<slug>
    and m.facebook.com/<slug>, returning ``(page_id, page_name)``.

    Either or both can be ``None``. The page_id (numeric, page-keyed)
    comes from ``_PAGE_ID_PATTERNS``; the page_name (display-string)
    comes from ``og:title`` with the location suffix stripped.

    Why both in one call? Because Meta walls anonymous traffic
    (see 2026-05-06 22:00 UTC log entry) and the page_id misses on
    most modern dealer pages — but ``og:title`` is rendered into the
    same logged-out shell and is essentially never blocked. Capturing
    it for free here lets the keyword-search actor URL form work
    without falling through to Playwright.

    Uses a desktop user-agent because Meta returns slightly different
    markup to "modern" UAs and the mobile UA path occasionally
    redirects to a barebones logged-out wall with no metadata
    embedded.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    candidate_urls = [
        f"https://www.facebook.com/{slug}",
        f"https://m.facebook.com/{slug}",
    ]
    found_id: Optional[str] = None
    found_name: Optional[str] = None
    async with httpx.AsyncClient(
        timeout=15.0, follow_redirects=True, headers=headers,
    ) as client:
        for url in candidate_urls:
            try:
                resp = await client.get(url)
            except Exception as e:
                log.debug("HTTP page-meta probe failed for %s: %s", url, e)
                continue
            if resp.status_code >= 400:
                continue
            body = resp.text

            # Identity check first — make sure the body we got back
            # actually corresponds to the slug we asked for. The
            # logged-out wall sometimes serves an interstitial whose
            # og:url points elsewhere.
            if not _is_authentic_page_render(body, str(resp.url), slug):
                continue

            if found_id is None:
                for pattern in _PAGE_ID_PATTERNS:
                    m = pattern.search(body)
                    if m:
                        candidate = m.group(1)
                        if (
                            candidate
                            and candidate.isdigit()
                            and int(candidate) > 0
                        ):
                            found_id = candidate
                            break

            if found_name is None:
                title = _extract_og_title(body)
                if title:
                    found_name = _clean_page_name(title)

            if found_id and found_name:
                break
    return found_id, found_name


def _extract_id_from_url(url: str) -> Optional[str]:
    """Fast-path resolver for URLs that are already in numeric form.

    Examples we can short-circuit without hitting the network:

      * ``facebook.com/profile.php?id=108047081396228``
      * ``facebook.com/108047081396228``  (rare but valid)
      * ``m.facebook.com/profile.php?id=...``

    Returns the numeric ID as a string, or ``None`` if the URL needs
    full resolution. Cheap enough to call unconditionally before
    spinning up Playwright.
    """
    parsed = urlparse(_normalize_fb_url(url))
    qs = parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        candidate = qs["id"][0]
        if candidate.isdigit() and int(candidate) > 0:
            return candidate
    slug = parsed.path.strip("/").split("/")[0] if parsed.path else ""
    if slug.isdigit() and int(slug) > 0:
        return slug
    return None


def _extract_canonical_slug(html: str) -> Optional[str]:
    """Pull the canonical slug out of the rendered DOM's ``og:url``
    meta tag. Returns ``None`` if no ``og:url`` is present (logged-
    out shell, login redirect, error page, etc.).

    Lower-cased to make slug comparison case-insensitive — Facebook
    canonicalises ``AltorferCAT`` to ``altorfercat`` (and back to the
    operator-specified casing only on display), so matching has to
    be insensitive to round-trip safely.
    """
    m = _OG_URL_PATTERN.search(html)
    if m:
        return m.group(1).lower()
    return None


def _is_authentic_page_render(
    html: str, final_url: str, expected_slug: str,
) -> bool:
    """Identity check: does the rendered DOM actually correspond to
    the dealer page we asked Playwright to load?

    Two signals, either of which is sufficient:

      1. ``og:url`` canonical slug matches ``expected_slug``.
      2. Final post-redirect URL path starts with ``/<expected_slug>``.

    Both signals missing or mismatching → fail closed (return
    ``False``); the caller skips this candidate, tries the next, or
    falls through to a per-dealer skip warning. Better to skip a
    dealer for one scan than to poison ``distributors.facebook_page_id``
    with a wrong ID that gets treated as authoritative forever.

    Without this check, the page-id regex iteration could match
    against a logged-out wall (login page, /people directory, error
    page) which contains assorted numeric IDs unrelated to the
    intended dealer — that's exactly the false-positive class the
    2026-05-07 morning deploy produced.
    """
    expected = expected_slug.lower()

    canonical = _extract_canonical_slug(html)
    if canonical is not None:
        return canonical == expected

    # No og:url found — fall back to the post-redirect URL path.
    final_path = urlparse(final_url).path.strip("/")
    final_slug = (
        final_path.split("/")[0].lower() if final_path else ""
    )
    return final_slug == expected


async def _playwright_resolve_one(
    url: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a single dealer URL to ``(page_id, page_name)`` by
    rendering the page in headless Chromium and extracting metadata
    from the verified DOM.

    Either or both return values can be ``None`` — name resolution
    succeeds independently of ID resolution because they come from
    different meta tags (``og:title`` vs. the deep-link / inline-JSON
    page-keyed regexes). For Ad Library searching we now actually
    prefer the name (see migration 034 for why), so a (None, "Yancey
    Rents - …") return is fully usable downstream.

    Strategy:

      1. Fast-path: if the URL already encodes a numeric ID
         (``profile.php?id=`` or ``facebook.com/<digits>``), return
         that ID directly with no name (the actor URL builder will
         fall back to the slug as the search query).
      2. Try ``m.facebook.com/<slug>`` with the mobile UA, then
         ``www.facebook.com/<slug>`` with the desktop UA. For each:
           a) Render and wait for ``domcontentloaded`` + short settle.
           b) **Identity check**: confirm ``og:url`` canonical
              slug == input slug, OR final post-redirect URL path
              == ``/<input slug>``. If neither matches, skip this
              candidate — Facebook served us something other than
              the dealer's page (login wall, redirect, etc.) and
              any metadata in the DOM is about something else.
           c) Run page-keyed regexes for the numeric ID and grab
              ``og:title`` for the name. Return as soon as we have
              a name (the ID is best-effort — many of our dealers
              are profile-backed business accounts where Ad Library
              doesn't accept the slug-canonical numeric anyway, so
              the name is the load-bearing signal).
      3. If both candidates fail identity verification, return
         ``(None, None)`` — caller logs a per-dealer skip warning.

    The identity check is the difference between "drop in correct
    metadata" vs. "drop in metadata from a login wall". Without it,
    earlier resolvers picked up viewer/session IDs from logged-out
    walls and fed them to the meta-ad-scraper, which then loaded an
    Ad Library page where the transparency block read
    ``ID: undefined`` and returned 0 ads. See log.md 2026-05-07
    entries for the full debug trace.

    Network / browser errors are swallowed at debug level so a
    single bad dealer doesn't crash the whole batch resolver.
    """
    direct = _extract_id_from_url(url)
    if direct:
        return direct, None

    slug = _extract_page_slug(url)
    if not slug:
        return None, None

    # Mobile first (less aggressive logged-out wall), desktop second.
    candidates: List[Tuple[str, bool]] = [
        (f"https://m.facebook.com/{slug}", True),
        (f"https://www.facebook.com/{slug}", False),
    ]

    from .extraction_service import _get_browser, _new_page

    try:
        browser = await _get_browser()
    except Exception as e:
        log.warning("Playwright resolver could not get browser: %s", e)
        return None, None

    found_id: Optional[str] = None
    found_name: Optional[str] = None

    for candidate_url, mobile in candidates:
        page = None
        try:
            page = await _new_page(browser, mobile=mobile)
            await page.goto(
                candidate_url,
                wait_until="domcontentloaded",
                timeout=20_000,
            )
            # Brief settle so deferred meta tags / inline JSON are
            # present in the DOM before we scrape it.
            await asyncio.sleep(2)

            content = await page.content()
            final_url = page.url or ""

            if not _is_authentic_page_render(content, final_url, slug):
                log.debug(
                    "Playwright resolver: %s did not render an "
                    "authentic page for slug=%r (og:url canonical "
                    "and final URL both miss); skipping candidate",
                    candidate_url, slug,
                )
                continue

            if found_id is None:
                for pattern in _PAGE_ID_PATTERNS:
                    m = pattern.search(content)
                    if m:
                        pid = m.group(1)
                        if pid and pid.isdigit() and int(pid) > 0:
                            found_id = pid
                            break

            if found_name is None:
                title = _extract_og_title(content)
                if title:
                    found_name = _clean_page_name(title)

            if found_name:
                log.debug(
                    "Playwright resolver got pageName=%r (pageId=%r) "
                    "for %s via %s (verified)",
                    found_name, found_id, slug, candidate_url,
                )
                return found_id, found_name

            log.debug(
                "Playwright resolver: %s rendered authentic page "
                "for slug=%r but extracted no og:title; trying "
                "next candidate",
                candidate_url, slug,
            )
        except Exception as e:
            log.debug(
                "Playwright resolver failed on %s: %s",
                candidate_url, e,
            )
        finally:
            if page is not None:
                try:
                    await page.context.close()
                except Exception:
                    pass

    return found_id, found_name


async def _playwright_resolve_page_ids(
    page_urls: List[str],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Tier-4 resolver via headless Chromium.

    Replaces the previous ``apify/facebook-pages-scraper`` dependency,
    which required a separate Apify rental and consistently 400'd in
    production (see log.md 2026-05-06 22:23 UTC). Playwright is in-
    process, free, and gives us page metadata by extracting it from
    the JS-rendered DOM rather than asking a third-party actor to do
    it for us.

    Returns a ``(id_map, name_map)`` tuple. Either map can be empty;
    they are not symmetric because name resolution succeeds for many
    profile-backed business accounts where ID resolution doesn't
    (the Ad-Library namespace mismatch — see migration 034). For
    keyword-search Ad Library URLs the name map is the important
    output; the id map is kept as a best-effort cache for any future
    code path that still needs the numeric.

    Concurrency is bounded by ``_PW_CONCURRENCY`` so we don't open
    50 browser contexts in parallel and trip Meta's bot heuristics.
    Each successful resolution gets persisted back to the
    distributors row by the caller, so this path is only exercised
    once per dealer-lifetime — every subsequent scan hits Tier 2
    (DB) and returns instantly.
    """
    if not page_urls:
        return {}, {}

    sem = asyncio.Semaphore(_PW_CONCURRENCY)
    id_out: Dict[str, str] = {}
    name_out: Dict[str, str] = {}

    async def _bounded(url: str):
        async with sem:
            try:
                pid, pname = await _playwright_resolve_one(url)
            except Exception as e:
                log.debug(
                    "Playwright resolver crashed on %s: %s", url, e,
                )
                return
            if pid:
                id_out[url] = pid
            if pname:
                name_out[url] = pname

    await asyncio.gather(
        *[_bounded(u) for u in page_urls], return_exceptions=True,
    )

    log.info(
        "Playwright resolver returned metadata for %d/%d dealer(s) "
        "(pageIds=%d, pageNames=%d)",
        max(len(id_out), len(name_out)), len(page_urls),
        len(id_out), len(name_out),
    )
    return id_out, name_out


async def _resolve_facebook_page_ids_batch(
    page_urls: List[str],
    distributor_mapping: Optional[Dict[str, UUID]] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Tiered resolver — the public entrypoint used by ``scan_meta_ads``.

    Returns ``(id_map, name_map)`` for the batch. Either map can be
    sparse; they're not symmetric. The actor URL builder downstream
    prefers the name map (keyword-search Ad Library URL) and falls
    back to the slug only if both are empty for a given dealer.

    Resolution priority (each tier looks up both ID and name):

        1. In-process caches (``_PAGE_ID_CACHE``, ``_PAGE_NAME_CACHE``).
        2. Persisted ``distributors.facebook_page_id`` and
           ``distributors.facebook_page_name`` columns (set by a
           previous successful scan — see migrations 032 + 034).
        3. Anonymous HTTP probe of facebook.com/<slug> + m.facebook.com/<slug>
           (returns whichever metadata is in the logged-out HTML —
           usually og:title, sometimes also a page-keyed numeric ID).
        4. Headless Playwright render of the same page — the JS
           executes and any deferred metadata becomes visible.

    Tier-3+4 successes are written back to the distributors row
    (best-effort) so future scans don't re-resolve. URLs for which
    BOTH outputs miss after all four tiers are absent from both
    return maps; caller logs a per-dealer skip warning.
    """
    if not page_urls:
        return {}, {}
    distributor_mapping = distributor_mapping or {}
    id_result: Dict[str, str] = {}
    name_result: Dict[str, str] = {}

    # Tier 1: in-process caches.
    for url in page_urls:
        slug = _extract_page_slug(url)
        if not slug:
            continue
        if slug in _PAGE_ID_CACHE:
            id_result[url] = _PAGE_ID_CACHE[slug]
        if slug in _PAGE_NAME_CACHE:
            name_result[url] = _PAGE_NAME_CACHE[slug]

    def _is_resolved(u: str) -> bool:
        # A dealer is considered resolved as long as we have *either*
        # a name or an ID — the actor URL builder needs only one.
        return u in name_result or u in id_result

    # Tier 2: persisted columns on distributors. Single batched select.
    pending = [u for u in page_urls if not _is_resolved(u)]
    if pending:
        slug_to_dist = _build_url_to_distributor_map(pending, distributor_mapping)
        dist_ids = list({
            slug_to_dist[s] for s in (
                _extract_page_slug(u) for u in pending
            ) if s and s in slug_to_dist
        })
        if dist_ids:
            try:
                resp = (
                    supabase.table("distributors")
                    .select("id, facebook_page_id, facebook_page_name")
                    .in_("id", [str(i) for i in dist_ids])
                    .execute()
                )
                dist_id_to_page_id: Dict[str, str] = {}
                dist_id_to_page_name: Dict[str, str] = {}
                for row in (resp.data or []):
                    pid = row.get("facebook_page_id")
                    if pid and str(pid).isdigit() and int(str(pid)) > 0:
                        dist_id_to_page_id[str(row["id"])] = str(pid)
                    pname = row.get("facebook_page_name")
                    if pname and isinstance(pname, str) and pname.strip():
                        dist_id_to_page_name[str(row["id"])] = pname.strip()

                for url in pending:
                    slug = _extract_page_slug(url)
                    dist_id = slug_to_dist.get(slug) if slug else None
                    if not dist_id:
                        continue
                    dist_key = str(dist_id)
                    if dist_key in dist_id_to_page_id and url not in id_result:
                        id_result[url] = dist_id_to_page_id[dist_key]
                        if slug:
                            _PAGE_ID_CACHE[slug] = id_result[url]
                    if dist_key in dist_id_to_page_name and url not in name_result:
                        name_result[url] = dist_id_to_page_name[dist_key]
                        if slug:
                            _PAGE_NAME_CACHE[slug] = name_result[url]
            except Exception as e:
                # Migration 032 / 034 may not have applied yet;
                # degrade gracefully to the live-resolution path.
                log.debug(
                    "DB lookup of distributors.facebook_page_id / "
                    "facebook_page_name failed (migrations 032/034 "
                    "may be pending): %s", e,
                )

    # Tier 3: anonymous HTTP probe (now also captures og:title).
    pending = [u for u in page_urls if not _is_resolved(u)]
    http_resolved_urls: set = set()
    if pending:
        for url in pending:
            slug = _extract_page_slug(url)
            if not slug:
                continue
            pid, pname = await _http_resolve_page_meta(slug)
            wrote_anything = False
            if pid and url not in id_result:
                id_result[url] = pid
                _PAGE_ID_CACHE[slug] = pid
                wrote_anything = True
            if pname and url not in name_result:
                name_result[url] = pname
                _PAGE_NAME_CACHE[slug] = pname
                wrote_anything = True
            if wrote_anything:
                http_resolved_urls.add(url)

    # Tier 4: headless Playwright render. Free, in-process, no Apify
    # dependency.
    needs_pw = [u for u in page_urls if not _is_resolved(u)]
    pw_id_resolved: Dict[str, str] = {}
    pw_name_resolved: Dict[str, str] = {}
    if needs_pw:
        log.info(
            "Tier-4 (Playwright render) resolving %d dealer(s) the "
            "anonymous HTTP probe could not crack", len(needs_pw),
        )
        pw_id_resolved, pw_name_resolved = await _playwright_resolve_page_ids(
            needs_pw,
        )
        for url, pid in pw_id_resolved.items():
            if url not in id_result:
                id_result[url] = pid
                slug = _extract_page_slug(url)
                if slug:
                    _PAGE_ID_CACHE[slug] = pid
        for url, pname in pw_name_resolved.items():
            if url not in name_result:
                name_result[url] = pname
                slug = _extract_page_slug(url)
                if slug:
                    _PAGE_NAME_CACHE[slug] = pname

    pw_resolved_urls = set(pw_id_resolved.keys()) | set(pw_name_resolved.keys())

    # Tally the four tier outcomes for the operator log line below.
    resolved_urls = set(id_result.keys()) | set(name_result.keys())
    cache_or_db_hits = len(resolved_urls - http_resolved_urls - pw_resolved_urls)
    missed = [u for u in page_urls if u not in resolved_urls]

    # Persist Tier 3 + Tier 4 results back to the DB so the next scan
    # finds them at Tier 2 and pays no resolver cost. Best-effort —
    # missing columns / RLS blocks just log at debug.
    fresh_writes = http_resolved_urls | pw_resolved_urls
    if distributor_mapping and fresh_writes:
        slug_to_dist_full = _build_url_to_distributor_map(
            page_urls, distributor_mapping,
        )
        now = datetime.now(timezone.utc).isoformat()
        for url in fresh_writes:
            slug = _extract_page_slug(url)
            dist_id = slug_to_dist_full.get(slug) if slug else None
            if not dist_id:
                continue
            update_payload: Dict[str, Any] = {}
            if url in id_result:
                update_payload["facebook_page_id"] = id_result[url]
                update_payload["facebook_page_id_resolved_at"] = now
            if url in name_result:
                update_payload["facebook_page_name"] = name_result[url]
            if not update_payload:
                continue
            try:
                supabase.table("distributors").update(update_payload).eq(
                    "id", str(dist_id),
                ).execute()
            except Exception as e:
                log.debug(
                    "Could not persist facebook_page_* for %s: %s "
                    "(migrations 032/034 pending?)", slug, e,
                )

    log.info(
        "Facebook page metadata resolution: %d/%d dealers resolved "
        "(cache+DB hit %d, HTTP probe added %d, Playwright added %d, "
        "%d missed) — id_map=%d, name_map=%d",
        len(resolved_urls), len(page_urls),
        cache_or_db_hits, len(http_resolved_urls), len(pw_resolved_urls),
        len(missed),
        len(id_result), len(name_result),
    )
    for url in missed:
        log.warning(
            "Could not resolve any Facebook page metadata for %s. "
            "Skipping this dealer for the current scan (no name "
            "and no pageId — Facebook served us nothing usable).",
            _extract_page_slug(url) or url,
        )
    return id_result, name_result


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _normalize_fb_url(url: str) -> str:
    """Ensure a Facebook URL is well-formed."""
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://www.facebook.com/{url}"
    return url


def _extract_page_slug(url: str) -> str:
    """Extract the Facebook page slug/ID from a URL for matching purposes."""
    parsed = urlparse(_normalize_fb_url(url))
    path = parsed.path.strip("/").split("/")[0] if parsed.path else ""
    return path.lower()


def _ad_library_url_for(library_id: str) -> str:
    """Construct a permalink Ad Library URL from a libraryID. The new
    actor doesn't return one directly; we synthesise the canonical
    form used by Meta itself."""
    return f"https://www.facebook.com/ads/library/?id={library_id}"


# ---------------------------------------------------------------------------
# Apify run wrappers
# ---------------------------------------------------------------------------

async def _start_actor_run(
    *,
    search_query: str,
    country: str = "US",
    active_status: str = "all",
    max_concurrency: int = 1,
    request_timeout_secs: int = 900,
) -> dict:
    """Start a single actor run for a single dealer.

    Uses Ad Library's keyword-search URL form
    (``q=<search_query>&search_type=keyword_unordered``) rather than
    the page-ID form (``view_all_page_id=NNN``). Two reasons:

      1. **Namespace mismatch on profile-backed accounts.** Many of
         our dealers (Yancey Rents, Carolina CAT, Altorfer, …) have
         Facebook accounts whose slug-canonical numeric ID lives in
         the *profile* graph namespace, not the *advertiser*
         namespace Ad Library uses. Pasting the profile ID into a
         ``view_all_page_id=`` URL returns "no ads match your search
         criteria" even when the dealer has confirmed active ads —
         verified 2026-05-07 against multiple dealers.

      2. **Same actor, no input-builder gotchas.** The actor's
         parameters-mode URL builder adds extra query params that
         break Ad Library's rendering (see 2026-05-07 morning log
         entry for the prior failure). The ``targetUrl`` mode lets
         us hand-build the URL with exactly the params we want.

    Keyword search returns ads from any advertiser whose page name
    contains the query string, so callers MUST post-filter results
    by ``pageName`` to drop name-collision noise. ``_run_actor_for_page``
    handles that filter using ``_name_matches_dealer``.
    """
    from urllib.parse import quote

    target_url = (
        "https://www.facebook.com/ads/library/"
        f"?active_status={active_status}"
        f"&ad_type=all"
        f"&country={country}"
        f"&q={quote(search_query)}"
        f"&search_type=keyword_unordered"
        f"&media_type=all"
    )
    actor_input: Dict[str, Any] = {
        "targetUrl": target_url,
        "maxConcurrency": max_concurrency,
        "requestHandlerTimeoutSecs": request_timeout_secs,
    }
    if settings.apify_meta_proxy_url:
        actor_input["proxyUrl"] = settings.apify_meta_proxy_url

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{APIFY_BASE}/acts/{ACTOR_ID}/runs",
            params={"token": settings.apify_api_key},
            json=actor_input,
        )
        resp.raise_for_status()
        return resp.json()["data"]


async def _poll_run(run_id: str) -> dict:
    """Poll until the actor run reaches a terminal status."""
    elapsed = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while elapsed < _MAX_POLL_TIME_SEC:
            resp = await client.get(
                f"{APIFY_BASE}/actor-runs/{run_id}",
                params={"token": settings.apify_api_key},
            )
            resp.raise_for_status()
            run_data = resp.json()["data"]

            status = run_data.get("status", "UNKNOWN")
            log.debug("Run %s status: %s (elapsed %ds)", run_id, status, elapsed)

            if status in _TERMINAL_STATUSES:
                return run_data

            await asyncio.sleep(_POLL_INTERVAL_SEC)
            elapsed += _POLL_INTERVAL_SEC

    raise TimeoutError(
        f"Apify run {run_id} did not complete within {_MAX_POLL_TIME_SEC}s"
    )


async def _fetch_dataset_items(dataset_id: str) -> List[Dict[str, Any]]:
    """Fetch all items from an Apify dataset."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            params={"token": settings.apify_api_key, "format": "json"},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Distributor resolution (per fan-out)
# ---------------------------------------------------------------------------

def _build_url_to_distributor_map(
    page_urls: List[str],
    distributor_mapping: Dict[str, UUID],
) -> Dict[str, UUID]:
    """Build a slug→distributor_id lookup. The router passes
    ``distributor_mapping`` keyed by lowercased dealer name; we add a
    secondary index by Facebook URL slug so the per-page fan-out path
    can resolve via the source URL with zero ambiguity."""
    slug_map: Dict[str, UUID] = {}
    slug_map.update(distributor_mapping)

    for url in page_urls:
        slug = _extract_page_slug(url)
        if slug:
            for name, dist_id in distributor_mapping.items():
                if slug in name or name in slug:
                    slug_map[slug] = dist_id
                    break

    return slug_map


def _resolve_distributor_from_source(
    source_page_url: str,
    slug_map: Dict[str, UUID],
) -> Optional[UUID]:
    """Each ad now carries the dealer page URL that triggered its
    actor run, so distributor resolution is just slug-to-id (no fuzzy
    brand-name matching across multiple dealers in one scan)."""
    slug = _extract_page_slug(source_page_url)
    if slug and slug in slug_map:
        return slug_map[slug]
    return None


def _resolve_distributor_by_brand(
    ad: Dict[str, Any],
    slug_map: Dict[str, UUID],
) -> Optional[UUID]:
    """Fallback: match the ad's ``brand`` string against the dealer
    name index. Used only if the source-URL path failed (which
    shouldn't normally happen but is worth defending against in case
    we ever change how fan-outs are dispatched)."""
    brand = (ad.get("brand") or "").lower()
    if not brand:
        return None
    if brand in slug_map:
        return slug_map[brand]
    for key, dist_id in slug_map.items():
        if key in brand or brand in key:
            return dist_id
    return None


# ---------------------------------------------------------------------------
# Media URL extraction (new actor's shape)
# ---------------------------------------------------------------------------

def _collect_media_urls(ad: Dict[str, Any]) -> List[str]:
    """Pull http(s) URLs out of an ad item produced by the actor.

    Live actor schema (verified 2026-05-07 against ``whoareyouanas/
    meta-ad-scraper`` runs that returned non-zero ad counts):

        imageUrls: [{"url": "https://..."}]
        videoUrls: [{"url": "https://...", "duration": 30}]

    Earlier code in this module read ``ad["images"]`` / ``ad["videos"]``,
    matching the field names in the actor's README — but the runtime
    output uses the ``Urls`` suffixed names. The mismatch caused every
    ad to be classified as "no images" and skipped, producing 0
    ``discovered_images`` rows even on scans where the actor returned
    rich datasets. See log.md 2026-05-07 (late afternoon) for the
    full bug-trace.

    Inner shape is unchanged — still ``[{"url": "..."}]`` objects, so
    the inner loop logic is preserved. Defensive against the value
    being a bare string in case the actor's serialiser ever changes
    its mind (mirrors the original tolerance).

    Falls back from images to videos because Meta sometimes serves the
    poster image only via the video object."""
    urls: List[str] = []

    for img in (ad.get("imageUrls") or ad.get("images") or []):
        url = (img or {}).get("url") if isinstance(img, dict) else img
        if isinstance(url, str) and url.startswith("http"):
            urls.append(url)

    if not urls:
        for vid in (ad.get("videoUrls") or ad.get("videos") or []):
            url = (vid or {}).get("url") if isinstance(vid, dict) else vid
            if isinstance(url, str) and url.startswith("http"):
                urls.append(url)

    return urls


def _ad_id(ad: Dict[str, Any]) -> str:
    """Return the ad's library identifier in a canonical string form.

    The actor emits this as ``adId`` at runtime (verified 2026-05-07);
    earlier code read ``libraryID``. We try both for resilience to
    future actor schema drift.
    """
    return str(ad.get("adId") or ad.get("libraryID") or "")


# ---------------------------------------------------------------------------
# Playwright tier-3 image extraction (kept as-is — operates on the
# permalink ad library URL, which is identical for both actors)
# ---------------------------------------------------------------------------

async def _extract_image_from_ad_library(ad_library_url: str) -> List[str]:
    """Tier 3: visit the Meta Ad Library page in Playwright and extract
    the rendered ad creative image URL(s) from the DOM."""
    from .extraction_service import _get_browser, _new_page

    extracted: List[str] = []
    browser = await _get_browser()
    page = await _new_page(browser, mobile=False)

    try:
        await page.goto(ad_library_url, wait_until="domcontentloaded", timeout=_PW_AD_LIBRARY_TIMEOUT)
        await asyncio.sleep(4)

        image_urls = await page.evaluate("""() => {
            const seen = new Set();
            const results = [];

            const adImages = document.querySelectorAll(
                'img[src*="scontent"], img[src*="fbcdn"], img[src*="facebook"]'
            );
            for (const img of adImages) {
                const src = img.currentSrc || img.src;
                if (!src || seen.has(src) || src.startsWith('data:')) continue;
                const w = img.naturalWidth || img.width;
                const h = img.naturalHeight || img.height;
                if (w < 100 || h < 100) continue;
                seen.add(src);
                results.push(src);
            }

            if (results.length === 0) {
                for (const img of document.querySelectorAll('img')) {
                    const src = img.currentSrc || img.src;
                    if (!src || seen.has(src) || src.startsWith('data:')) continue;
                    const w = img.naturalWidth || img.width;
                    const h = img.naturalHeight || img.height;
                    if (w < 150 || h < 150) continue;
                    seen.add(src);
                    results.push(src);
                }
            }

            return results;
        }""")

        extracted = [u for u in image_urls if u and u.startswith("http")]
        log.info(
            "Playwright extracted %d image(s) from Ad Library page: %s",
            len(extracted), ad_library_url[:80],
        )

    except Exception as e:
        log.warning(
            "Playwright fallback failed for %s: %s", ad_library_url[:80], e,
        )
    finally:
        try:
            await page.context.close()
        except Exception:
            pass

    return extracted


async def _resolve_images_for_ads(
    ads: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Resolve image URLs for ads where ``imageUrls`` and ``videoUrls``
    were both empty. Keyed by the ad library identifier (``adId`` at
    runtime, fallback to ``libraryID`` for forward/backward compat)."""
    sem = asyncio.Semaphore(_PW_CONCURRENCY)
    results: Dict[str, List[str]] = {}

    async def _resolve_one(ad: Dict[str, Any]):
        library_id = _ad_id(ad)
        if not library_id:
            return
        # Prefer the actor's directly-emitted Ad Library URL; fall
        # back to synthesising one from the library_id if absent.
        ad_url = ad.get("adUrl") or _ad_library_url_for(library_id)
        async with sem:
            urls = await _extract_image_from_ad_library(ad_url)
            if urls:
                results[library_id] = urls

    needs_fallback = [
        ad for ad in ads
        if not _collect_media_urls(ad) and _ad_id(ad)
    ]

    if not needs_fallback:
        return results

    log.info(
        "Playwright fallback needed for %d/%d ads with missing image URLs",
        len(needs_fallback), len(ads),
    )

    await asyncio.gather(*[_resolve_one(ad) for ad in needs_fallback])
    log.info("Playwright fallback resolved images for %d ads", len(results))
    return results


# ---------------------------------------------------------------------------
# Per-page fan-out
# ---------------------------------------------------------------------------

async def _run_actor_for_page(
    page_url: str,
    page_name: Optional[str],
    *,
    country: str = "US",
    active_status: str = "all",
) -> Tuple[str, List[Dict[str, Any]], Optional[float], Optional[str]]:
    """Run one actor invocation for one dealer using keyword search.

    The search query is the page's display name (preferred) or its
    URL slug (fallback). Slug fallback is decent because Facebook
    tokenises camelCase names ("YanceyRents" → "yancey rents"), and
    the post-filter step drops keyword-collision noise either way.

    Returns ``(page_url, ads, usage_total_usd, run_id)``. Always
    returns — actor / network failures degrade to an empty ad list
    and a logged WARNING rather than raising, so one dealer's outage
    doesn't fail the whole multi-dealer scan.

    Post-filter: actor results are dropped when the ad's
    ``pageName`` doesn't plausibly match the dealer (see
    ``_name_matches_dealer``). This is necessary because keyword
    search can return ads from any advertiser whose name contains
    the query — e.g. searching ``Yancey Rents`` could also return
    a ``Yancey Rentals LLC`` ad. Without this filter we'd attribute
    foreign-advertiser ads to our dealer.
    """
    slug = _extract_page_slug(page_url)
    # Build the search query. Prefer the resolved display name (e.g.
    # "Yancey Rents - The Cat Rental Store"); fall back to the slug
    # if name resolution missed for this dealer (e.g. all four
    # resolver tiers were blocked).
    search_query = (page_name or "").strip() or slug
    if not search_query:
        log.warning(
            "Refusing to run actor for %s: no search query "
            "(no page_name and no slug)", page_url,
        )
        return page_url, [], None, None

    try:
        run_info = await _start_actor_run(
            search_query=search_query,
            country=country,
            active_status=active_status,
        )
        run_id = run_info["id"]
        log.info(
            "Apify Meta run started for %s (q=%r, name=%r): %s",
            slug, search_query, page_name, run_id,
        )

        completed = await _poll_run(run_id)
    except TimeoutError:
        log.error("Apify run for %s timed out", page_url)
        return page_url, [], None, None
    except Exception as e:
        log.warning("Apify run for %s failed to start/poll: %s", page_url, e)
        return page_url, [], None, None

    if completed.get("status") != "SUCCEEDED":
        log.warning(
            "Apify run for %s ended with status %s (run_id=%s)",
            page_url, completed.get("status"), completed.get("id"),
        )
        return page_url, [], completed.get("usageTotalUsd"), completed.get("id")

    dataset_id = completed.get("defaultDatasetId")
    if not dataset_id:
        log.warning("Run for %s succeeded but no dataset id returned", page_url)
        return page_url, [], completed.get("usageTotalUsd"), completed.get("id")

    try:
        ads = await _fetch_dataset_items(dataset_id)
    except Exception as e:
        log.warning("Dataset fetch for %s failed: %s", page_url, e)
        ads = []

    # Post-filter: drop keyword-collision noise. We compare the
    # actor's reported pageName against the dealer's resolved name
    # AND slug — either has to match for the ad to count as ours.
    raw_count = len(ads)
    filtered_ads: List[Dict[str, Any]] = []
    dropped_examples: List[str] = []
    for ad in ads:
        actor_name = ad.get("pageName") or ad.get("pageNameKnown") or ""
        if _name_matches_dealer(actor_name, page_name, slug):
            filtered_ads.append(ad)
        else:
            if len(dropped_examples) < 3:
                dropped_examples.append(str(actor_name))
    if raw_count != len(filtered_ads):
        log.info(
            "Apify Meta run for %s: dropped %d/%d collision-noise "
            "ad(s) by pageName filter (examples=%r), kept %d",
            page_url, raw_count - len(filtered_ads), raw_count,
            dropped_examples, len(filtered_ads),
        )

    log.info(
        "Apify Meta run for %s returned %d ad(s) (raw=%d)",
        page_url, len(filtered_ads), raw_count,
    )
    return (
        page_url,
        filtered_ads,
        completed.get("usageTotalUsd"),
        completed.get("id"),
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def scan_meta_ads(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    *,
    channel: str = "facebook",
    campaign_assets: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Scan Meta Ad Library via the ``whoareyouanas/meta-ad-scraper``
    actor for Facebook/Instagram ad creatives.

    The signature is unchanged from the previous actor — callers pass a
    list of dealer Facebook URLs and we fan out internally.

    Steps:
        1. Resolve every page URL to its numeric Facebook pageId via
           the tiered resolver (cache → DB → HTTP probe → Playwright).
        2. Fan out meta-ad-scraper runs in parallel (bounded by
           ``settings.apify_meta_max_parallel_runs``) over the
           dealers whose pageId resolved successfully. Dealers that
           didn't resolve are logged as warnings and skipped.
        3. For each ad, pull image URLs (3-tier fallback).
        4. Insert each image as a ``discovered_images`` row, tagging
           the source dealer via the page_url that triggered the run.

    Returns the total number of discovered images inserted.
    """
    if not settings.apify_api_key:
        raise ValueError(
            "APIFY_API_KEY is not configured. "
            "Set it in your .env file to enable Meta Ads scanning."
        )

    if not page_urls:
        raise ValueError("No Facebook page URLs provided for Meta Ads scan.")

    log.info(
        "Starting Apify Meta Ads scan (%s, actor=%s) for %d page(s) "
        "[fan-out parallelism=%d]",
        channel, ACTOR_ID, len(page_urls), settings.apify_meta_max_parallel_runs,
    )

    supabase.table("scan_jobs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    # 1: Resolve every dealer URL to its Facebook page metadata
    # (numeric pageId where available, display name where available)
    # in one batch. Tier 1 (cache) and Tier 2 (DB columns) are free;
    # only genuinely new dealers fall through to the Playwright tier
    # (also free, just slower). After the first scan populates the
    # distributors.facebook_page_{id,name} columns for each dealer,
    # every subsequent scan resolves entirely from tier 2 in <50ms.
    #
    # The actor URL builder downstream prefers the page name (Ad
    # Library keyword search) — see migration 034 and the
    # 2026-05-07 (late afternoon) log entry for why ID-based search
    # was abandoned.
    page_id_map, page_name_map = await _resolve_facebook_page_ids_batch(
        page_urls, distributor_mapping,
    )
    # We can scan a dealer as long as we have *something* — name OR
    # id — because _run_actor_for_page falls back to the slug when
    # name is missing. The only way a dealer is truly unscannable is
    # if BOTH maps miss AND the slug is empty, which means we have
    # no information at all about how to query for them.
    scannable_urls = [
        u for u in page_urls
        if u in page_name_map or u in page_id_map or _extract_page_slug(u)
    ]
    if not scannable_urls:
        log.warning(
            "No usable Facebook page metadata for any of the %d "
            "supplied dealer URLs — meta scan cannot proceed",
            len(page_urls),
        )
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        return 0

    # 2: Fan out — bounded parallel actor runs over scannable dealers.
    fan_sem = asyncio.Semaphore(max(1, settings.apify_meta_max_parallel_runs))

    async def _bounded(page_url: str):
        async with fan_sem:
            return await _run_actor_for_page(
                page_url,
                page_name_map.get(page_url),
                active_status="all",
            )

    fan_results = await asyncio.gather(
        *[_bounded(url) for url in scannable_urls],
        return_exceptions=True,
    )

    # Aggregate ads from every fan-out, tagged with their source page.
    ads_by_source: List[Tuple[str, Dict[str, Any]]] = []
    total_actor_cost = 0.0
    successful_runs = 0
    for result in fan_results:
        if isinstance(result, BaseException):
            log.warning("Fan-out task crashed: %s", result)
            continue
        page_url, ads, cost_usd, run_id = result
        if cost_usd is not None:
            try:
                total_actor_cost += float(cost_usd)
            except Exception:
                pass
        if run_id:
            try:
                from . import cost_tracker
                cost_tracker.record_apify_run(
                    actor_or_task=ACTOR_ID,
                    run_id=run_id,
                    usage_total_usd=cost_usd,
                    items_returned=len(ads),
                )
            except Exception as cost_err:
                log.debug("Cost capture skipped (apify meta): %s", cost_err)
        if ads:
            successful_runs += 1
            for ad in ads:
                ads_by_source.append((page_url, ad))

    log.info(
        "Apify Meta fan-out complete: %d/%d dealers returned ads, "
        "%d ads total, $%.4f reported cost",
        successful_runs, len(page_urls), len(ads_by_source), total_actor_cost,
    )

    if not ads_by_source:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        log.warning("No ads found for any provided Facebook pages")
        return 0

    # Sample payload for debugging the wire format on first ad only.
    sample = ads_by_source[0][1]
    log.info(
        "Sample ad payload keys: %s | imageUrls=%d, videoUrls=%d, "
        "pageName=%s, adId=%s",
        list(sample.keys()),
        len(sample.get("imageUrls") or sample.get("images") or []),
        len(sample.get("videoUrls") or sample.get("videos") or []),
        sample.get("pageName") or sample.get("brand"),
        _ad_id(sample),
    )
    log.debug("Full sample ad payload: %s", json.dumps(sample, default=str)[:2000])

    # 3: Resolve images for ads missing imageUrls/videoUrls (Playwright tier).
    raw_ads = [ad for _, ad in ads_by_source]
    pw_resolved = await _resolve_images_for_ads(raw_ads)

    # 4: Distributor resolution + insertion.
    slug_map = _build_url_to_distributor_map(page_urls, distributor_mapping)
    img_buffer = DiscoveredImageBuffer()
    ads_with_images = 0
    ads_skipped = 0

    for source_page_url, ad in ads_by_source:
        library_id = _ad_id(ad)
        if not library_id:
            ads_skipped += 1
            continue

        # Prefer the actor's directly-emitted ad URL when present
        # (matches the Ad Library permalink the actor itself logs);
        # fall back to synthesising it from library_id otherwise.
        ad_url = ad.get("adUrl") or _ad_library_url_for(library_id)
        brand = ad.get("pageName") or ad.get("brand") or ""
        platforms = ad.get("platforms") or []
        active = ad.get("active")
        ad_status = "active" if active else ("inactive" if active is False else "")
        start_date = ad.get("startDate")
        media_format = ad.get("format") or ""

        # 3-tier image resolution.
        image_urls = _collect_media_urls(ad)
        extraction_method = "apify_meta"
        if not image_urls and library_id in pw_resolved:
            image_urls = pw_resolved[library_id]
            extraction_method = "apify_meta+playwright_fallback"

        if not image_urls:
            log.warning(
                "No images resolved for ad %s (%s) — skipping",
                library_id, brand,
            )
            ads_skipped += 1
            continue

        ads_with_images += 1

        # If the actor reports the ad ran ONLY on Instagram, surface
        # that — keeps the existing `instagram` channel split working.
        ad_channel = channel
        platforms_lc = [str(p).lower() for p in platforms]
        if "instagram" in platforms_lc and "facebook" not in platforms_lc:
            ad_channel = "instagram"

        distributor_id = (
            _resolve_distributor_from_source(source_page_url, slug_map)
            or _resolve_distributor_by_brand(ad, slug_map)
        )

        for img_url in image_urls:
            img_buffer.add({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": ad_url,
                "image_url": img_url,
                "source_type": "extracted_image",
                "channel": ad_channel,
                "metadata": {
                    "extraction_method": extraction_method,
                    "apify_actor": ACTOR_ID,
                    "library_id": library_id,
                    "brand": brand,
                    "ad_status": ad_status,
                    "media_format": media_format,
                    "platforms": platforms,
                    "start_date": start_date,
                    "link_title": ad.get("linkTitle", ""),
                    "link_url": ad.get("linkUrl", ""),
                    "cta_text": ad.get("ctaText", ""),
                    "cta_url": ad.get("ctaUrl", ""),
                    "body": (ad.get("body") or "")[:500],
                    "source_page_url": source_page_url,
                },
            })

    total_inserted = img_buffer.flush_all()

    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": total_inserted,
    }).eq("id", str(scan_job_id)).execute()

    log.info(
        "Apify Meta Ads scan complete: %d images from %d ads "
        "(%d skipped, %d resolved via Playwright)",
        total_inserted, ads_with_images, ads_skipped, len(pw_resolved),
    )
    return total_inserted
