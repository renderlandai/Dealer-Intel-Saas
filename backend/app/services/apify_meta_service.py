"""
Apify Meta Ad Library integration for Facebook & Instagram ad scraping.

Two actor paths, selected at scan time via ``settings.apify_meta_actor_id``:

  * ``whoareyouanas~meta-ad-scraper`` (default — original production path):
    accepts a single search per run (one ``targetUrl``, one ``pageId``, or
    one ``searchQuery``), so we fan out — one actor run per dealer page.
    Requires a slug→numeric-pageId resolver (the four-tier dance below)
    because the actor's input shape demands it. Pricing: $10/1000 ads.

  * ``curious_coder~facebook-ads-library-scraper`` (feature-flagged 2026-05-07
    after the cost / recall problems with the above became apparent):
    accepts a bulk ``urls: [{url}, {url}, …]`` array of dealer Facebook
    page URLs DIRECTLY, scrapes them in one run, and reports each ad
    with its own ``pageID`` / ``pageName``. Pricing: $0.75/1000 ads
    (~13× cheaper at the rate card). No slug resolver required — the
    page-URL → ad-list mapping is the actor's whole job.

The public ``scan_meta_ads`` entrypoint dispatches to the right path
based on the configured actor id; both paths feed the same downstream
``discovered_images`` insert so the matcher pipeline sees identical
shapes regardless of which actor produced the ads.

Pipeline overview (whoareyouanas path):

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

Pipeline overview (curious_coder path):

    1. ``_curious_coder_run_bulk`` fires ONE actor invocation with the
       full list of dealer Facebook URLs as input. No resolver. No
       fan-out. The actor returns a flat array of ads spanning every
       input URL.
    2. ``_curious_coder_normalize`` remaps each raw ad into the same
       canonical shape the whoareyouanas downstream loop already
       expects (``adId``, ``imageUrls: [{url}]``, ``pageName``, etc.).
    3. ``_curious_coder_attribute_ads`` maps each canonical ad to one
       of the input page URLs by ``pageID`` / ``pageName`` matching,
       producing the same ``[(source_page_url, ad), …]`` list shape
       as the whoareyouanas fan-out.
    4. Same downstream insert path — image URL fallback, distributor
       resolution, and ``discovered_images`` writes are shared.

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

# Default (= "current production") actor. The original swap from
# nourishing_courier landed on this one (see log.md 2026-05-06 entry).
WHOAREYOUANAS_ACTOR_ID = "whoareyouanas~meta-ad-scraper"

# Alternative actor — bulk URL input, ~13× cheaper at the rate card,
# no slug→pageId resolver required. Wired 2026-05-07 (Ask-mode review)
# behind ``settings.apify_meta_actor_id`` so an A/B trial can run
# without ripping out the whoareyouanas code path. See log.md entry
# of the same date for the full cost / reliability comparison.
CURIOUS_CODER_ACTOR_ID = "curious_coder~facebook-ads-library-scraper"

# ``ACTOR_ID`` is kept as a module-level alias for the active actor so
# legacy log lines and metadata fields ("apify_actor": ACTOR_ID) keep
# working; the dispatcher in ``scan_meta_ads`` reads
# ``settings.apify_meta_actor_id`` directly when it needs to branch.
ACTOR_ID = WHOAREYOUANAS_ACTOR_ID


def _active_actor_id() -> str:
    """Return the actor slug currently configured for this process.

    Read fresh on every call so test fixtures that monkey-patch the
    cached settings instance see the override immediately. (Also
    defensive against future code that reloads ``Settings``.)
    """
    return getattr(settings, "apify_meta_actor_id", "") or WHOAREYOUANAS_ACTOR_ID


def _is_curious_coder_active() -> bool:
    """Convenience predicate for the dispatcher.

    Tolerates both the canonical Apify slug form
    (``curious_coder~facebook-ads-library-scraper``) and the
    publication form (``curious_coder/facebook-ads-library-scraper``)
    so an operator copy/pasting from the Apify UI doesn't get a silent
    no-op fallback to the whoareyouanas path.
    """
    raw = _active_actor_id().strip().lower()
    return raw.replace("/", "~") == CURIOUS_CODER_ACTOR_ID

def _outcome_key(url: str) -> str:
    """Normalize a dealer page URL into the coverage key used by reuse.

    Must match ``scanning._coverage_key``'s normalization (strip →
    lower → drop trailing slash) so per-dealer outcomes recorded here
    line up with the keys ``find_reusable_scan`` derives from the
    distributor's stored ``facebook_url``.
    """
    return (url or "").strip().lower().rstrip("/")


def _merge_scan_metadata(scan_job_id: UUID, patch: Dict[str, Any]) -> None:
    """Shallow-merge ``patch`` into a scan job's JSONB ``metadata``.

    Supabase updates replace the whole column, so we read-modify-write
    to preserve sibling keys (e.g. the dispatch record). Best-effort:
    metadata is diagnostic, so a failure here must never abort a scan.
    """
    try:
        cur = supabase.table("scan_jobs").select("metadata")\
            .eq("id", str(scan_job_id)).single().execute()
        md = (cur.data or {}).get("metadata") or {}
        if not isinstance(md, dict):
            md = {}
        md.update(patch)
        supabase.table("scan_jobs").update({"metadata": md})\
            .eq("id", str(scan_job_id)).execute()
    except Exception as e:  # pragma: no cover - diagnostic only
        log.warning("Failed to merge scan metadata for %s: %s", scan_job_id, e)


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


def _ad_advertiser_name(ad: Dict[str, Any]) -> str:
    """Best-effort advertiser-name lookup across the actor's known
    field-name variants.

    The ``whoareyouanas/meta-ad-scraper`` actor inconsistently
    populates which advertiser-name field it emits per ad — the
    extractor depends on which Ad Library layout Facebook serves
    at request time, and we've observed in production:

      * ``pageName`` populated, others empty
      * ``brand`` populated, ``pageName`` empty
      * all three empty (full extraction failure for the run)

    Returning the first non-empty hit (or ``""``) lets the
    post-filter make a per-ad decision on whatever signal the actor
    happened to surface this run, and lets the run-wide fail-open
    detection count "ads with any name signal" reliably.
    """
    return (
        ad.get("pageName")
        or ad.get("pageNameKnown")
        or ad.get("brand")
        or ""
    )


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
) -> Tuple[str, List[Dict[str, Any]], Optional[float], Optional[str], str]:
    """Run one actor invocation for one dealer using keyword search.

    The search query is the page's display name (preferred) or its
    URL slug (fallback). Slug fallback is decent because Facebook
    tokenises camelCase names ("YanceyRents" → "yancey rents"), and
    the post-filter step drops keyword-collision noise either way.

    Returns ``(page_url, ads, usage_total_usd, run_id, outcome)``.
    Always returns — actor / network failures degrade to an empty ad
    list and a logged WARNING rather than raising, so one dealer's
    outage doesn't fail the whole multi-dealer scan.

    ``outcome`` records WHY the ad list is whatever it is, so callers
    can tell a clean "this dealer simply has no live ads" result
    (``"succeeded"`` with 0 ads) apart from a transient failure
    (``"timeout"`` / ``"error"`` / ``"failed"`` / ``"no_dataset"`` /
    ``"fetch_error"``) or an unscannable dealer (``"skipped"``). This
    distinction powers reuse: a cleanly-scanned-empty dealer can be
    reused (no re-scrape) while a timed-out one must be re-scanned.

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
        return page_url, [], None, None, "skipped"

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
        return page_url, [], None, None, "timeout"
    except Exception as e:
        log.warning("Apify run for %s failed to start/poll: %s", page_url, e)
        return page_url, [], None, None, "error"

    if completed.get("status") != "SUCCEEDED":
        log.warning(
            "Apify run for %s ended with status %s (run_id=%s)",
            page_url, completed.get("status"), completed.get("id"),
        )
        return page_url, [], completed.get("usageTotalUsd"), completed.get("id"), "failed"

    dataset_id = completed.get("defaultDatasetId")
    if not dataset_id:
        log.warning("Run for %s succeeded but no dataset id returned", page_url)
        return page_url, [], completed.get("usageTotalUsd"), completed.get("id"), "no_dataset"

    try:
        ads = await _fetch_dataset_items(dataset_id)
    except Exception as e:
        log.warning("Dataset fetch for %s failed: %s", page_url, e)
        return page_url, [], completed.get("usageTotalUsd"), completed.get("id"), "fetch_error"

    # Post-filter: drop keyword-collision noise. We compare each ad's
    # advertiser-name field against the dealer's resolved name AND
    # slug — either has to match for the ad to count as ours.
    #
    # Resilience design (added 2026-05-07 after the actor was observed
    # returning 6 valid Yancey Rents ads with EMPTY pageName for every
    # row, which caused the prior strict-only filter to drop all 6
    # and emit "0 images analyzed → 100% compliance"):
    #
    #   1. **Widened name lookup.** The actor inconsistently populates
    #      pageName / pageNameKnown / brand across runs (different Ad
    #      Library layouts at request time produce different selector
    #      hits). Try all three before giving up on a given ad.
    #
    #   2. **Run-wide fail-open.** If the actor returned ads but
    #      populated NO advertiser-name field on ANY of them, the
    #      filter has zero signal to act on. Dropping every ad is
    #      strictly worse than keeping every ad in this case — the
    #      matcher safety overhaul (2026-05-06) will correctly score
    #      any genuinely-foreign ads as "no match" anyway, while
    #      false-negative drops produce the misleading
    #      "100% compliance" email.
    #
    #   3. **Per-ad strictness preserved when the actor IS providing
    #      names.** If at least one ad has a populated name, we run
    #      the per-ad filter on every ad — this is the path that
    #      drops the 1Hood Media collision row from yesterday's
    #      transcript while keeping the 3 Yancey rows.
    raw_count = len(ads)
    ads_with_any_name = sum(
        1 for a in ads if _ad_advertiser_name(a).strip()
    )

    if raw_count > 0 and ads_with_any_name == 0:
        log.warning(
            "Apify Meta run for %s: actor returned %d ad(s) but "
            "populated no advertiser-name metadata on any of them; "
            "skipping pageName post-filter (fail-open) — every ad "
            "will flow downstream and the matcher will reject any "
            "that are truly foreign",
            page_url, raw_count,
        )
        filtered_ads: List[Dict[str, Any]] = list(ads)
    else:
        filtered_ads = []
        dropped_examples: List[str] = []
        for ad in ads:
            actor_name = _ad_advertiser_name(ad)
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
        "succeeded",
    )


# ---------------------------------------------------------------------------
# curious_coder/facebook-ads-library-scraper path
# ---------------------------------------------------------------------------
#
# This actor accepts dealer Facebook URLs DIRECTLY in a single bulk
# run (``urls: [{url}, …]``) and returns a flat dataset of ads, each
# ad carrying its own ``pageID`` / ``pageName`` so we can attribute
# back to the source dealer. None of the slug→pageId resolution code
# above is needed for this path.
#
# Output shape (verified against the actor's published README + the
# field table; the actor has been live since 2024 with consistent
# field names). Defensive multi-key reads below in case Apify ships
# a future schema bump:
#
#   {
#     "adArchiveID": "1234567890",     # primary identifier
#     "adID": "...",                   # sometimes present
#     "pageID": "108047...",
#     "pageName": "Yancey Rents",
#     "isActive": true,
#     "startDate": 1705320000,         # unix seconds
#     "endDate": null,
#     "publisherPlatform": ["FACEBOOK", "INSTAGRAM"],
#     "snapshot": {
#       "body": {"text": "..."} | "...",
#       "title": "...",
#       "link_url": "https://...",
#       "cta_text": "Shop Now",
#       "cta_type": "SHOP_NOW",
#       "images": [
#         {"original_image_url": "...", "resized_image_url": "..."}
#       ],
#       "videos": [
#         {"video_hd_url": "...", "video_sd_url": "...",
#          "video_preview_image_url": "..."}
#       ],
#       "cards": [
#         {"image_url": "...", "video_hd_url": "...", "title": "...",
#          "body": "...", "link_url": "..."}
#       ]
#     },
#     "currency": "USD",
#     "spend": {"lower_bound": 1000, "upper_bound": 5000}
#   }
#
# We normalise this to the same canonical ad shape the whoareyouanas
# downstream loop already consumes — primarily ``adId``,
# ``imageUrls: [{"url"}]``, ``pageName``, ``brand``, ``active``,
# ``platforms``, ``adUrl`` — so the rest of ``scan_meta_ads`` doesn't
# need to know which actor produced the data.

def _curious_coder_first(ad: Dict[str, Any], *keys: str) -> Optional[Any]:
    """Return the first non-empty value in ``ad`` for any of ``keys``.

    Used so each field-name alias the curious_coder actor has shipped
    historically (``pageID`` vs ``pageId``, ``adArchiveID`` vs ``adID``)
    is tolerated in one place. Empty strings count as missing —
    matches the broader downstream contract that "" means absent.
    """
    for k in keys:
        v = ad.get(k)
        if v is not None and v != "":
            return v
    return None


def _curious_coder_unix_to_iso(value: Any) -> str:
    """Normalise a curious_coder date field to an ISO-8601 string.

    The actor emits start/end dates as unix seconds (occasionally
    milliseconds for newer ads). We don't parse this downstream — it
    flows verbatim into ``discovered_images.metadata.start_date`` —
    so a string conversion is enough. Returns "" for any input we
    can't make sense of, matching the whoareyouanas-side contract
    where ``startDate`` is a free-form string.
    """
    if value is None or value == "":
        return ""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return str(value)
    # Treat very-large numbers as milliseconds (post-Y2038 unix
    # seconds wouldn't reasonably show up here).
    if ts > 10_000_000_000:
        ts = ts / 1000.0
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return str(value)


def _curious_coder_collect_creative_urls(
    snapshot: Dict[str, Any],
) -> Tuple[List[str], List[str], str]:
    """Pull image/video URLs out of a curious_coder ``snapshot`` block.

    Returns ``(image_urls, video_urls, format)`` where ``format`` is
    one of ``"image"``, ``"video"``, ``"carousel"``, or ``""``. The
    format string matches what the downstream code expects for the
    ``media_format`` metadata field.

    Field-name preferences (most preferred first):
      images:  ``original_image_url`` → ``resized_image_url``
      videos:  ``video_hd_url`` → ``video_sd_url`` → ``video_preview_image_url``

    Carousel cards (``snapshot.cards``) are flattened into the same
    image / video lists; ``format`` is set to ``"carousel"`` whenever
    cards are present so the downstream metadata accurately reflects
    the ad type.
    """
    if not isinstance(snapshot, dict):
        return [], [], ""

    images: List[str] = []
    videos: List[str] = []

    for img in (snapshot.get("images") or []):
        if not isinstance(img, dict):
            continue
        url = (
            img.get("original_image_url")
            or img.get("resized_image_url")
            or img.get("url")
        )
        if isinstance(url, str) and url.startswith("http"):
            images.append(url)

    for vid in (snapshot.get("videos") or []):
        if not isinstance(vid, dict):
            continue
        url = (
            vid.get("video_hd_url")
            or vid.get("video_sd_url")
            or vid.get("video_preview_image_url")
            or vid.get("url")
        )
        if isinstance(url, str) and url.startswith("http"):
            videos.append(url)

    cards = snapshot.get("cards") or []
    has_cards = False
    for card in cards:
        if not isinstance(card, dict):
            continue
        has_cards = True
        cimg = card.get("original_image_url") or card.get("image_url")
        if isinstance(cimg, str) and cimg.startswith("http"):
            images.append(cimg)
        cvid = (
            card.get("video_hd_url")
            or card.get("video_sd_url")
            or card.get("video_preview_image_url")
        )
        if isinstance(cvid, str) and cvid.startswith("http"):
            videos.append(cvid)

    if has_cards:
        media_format = "carousel"
    elif videos and not images:
        media_format = "video"
    elif images:
        media_format = "image"
    else:
        media_format = ""

    return images, videos, media_format


def _curious_coder_normalize(ad: Dict[str, Any]) -> Dict[str, Any]:
    """Map a raw curious_coder ad object → canonical ad shape.

    The canonical shape mirrors what the whoareyouanas path produces
    after its own internal mapping, so the downstream insertion loop
    in ``scan_meta_ads`` works uniformly across both actors:

        adId            : str
        pageName        : str
        brand           : str   (alias of pageName, kept for the
                                 _resolve_distributor_by_brand fallback)
        pageID          : str   (numeric — needed for attribution)
        active          : bool
        startDate       : str   (ISO-8601 if we can parse, else verbatim)
        platforms       : list[str]  (normalised lowercase)
        format          : str   ("image" / "video" / "carousel" / "")
        imageUrls       : list[{"url": str}]
        videoUrls       : list[{"url": str}]
        body            : str
        linkTitle       : str
        linkUrl         : str
        ctaText         : str
        ctaUrl          : str
        adUrl           : str   (Ad Library permalink — synthesised
                                 from adArchiveID since curious_coder
                                 doesn't return one directly)
        _curious_coder  : True  (origin marker for metadata + tests)

    Snapshot-shape details handled defensively: ``snapshot.body`` can
    be either a string (older builds) or ``{"text": "..."}`` (current).
    Both work.
    """
    snapshot = ad.get("snapshot") if isinstance(ad.get("snapshot"), dict) else {}

    image_urls, video_urls, media_format = (
        _curious_coder_collect_creative_urls(snapshot)
    )

    body_field = snapshot.get("body") if snapshot else None
    if isinstance(body_field, dict):
        body_text = str(body_field.get("text") or "")
    else:
        body_text = str(body_field or "")

    page_id = str(_curious_coder_first(ad, "pageID", "pageId", "page_id") or "")
    page_name = str(_curious_coder_first(ad, "pageName", "page_name") or "")
    library_id = str(
        _curious_coder_first(ad, "adArchiveID", "adArchiveId", "adID", "adId") or ""
    )

    is_active = bool(_curious_coder_first(ad, "isActive", "is_active", "active"))

    raw_platforms = ad.get("publisherPlatform") or ad.get("platforms") or []
    platforms = [
        str(p).lower() for p in raw_platforms
        if isinstance(p, str) and p.strip()
    ]

    canonical: Dict[str, Any] = {
        "adId": library_id,
        "pageName": page_name,
        "brand": page_name,  # mirror so brand-fallback still works
        "pageID": page_id,
        "active": is_active,
        "startDate": _curious_coder_unix_to_iso(
            _curious_coder_first(ad, "startDate", "start_date")
        ),
        "platforms": platforms,
        "format": media_format,
        "imageUrls": [{"url": u} for u in image_urls],
        "videoUrls": [{"url": u} for u in video_urls],
        "body": body_text,
        "linkTitle": str(snapshot.get("title") or "") if snapshot else "",
        "linkUrl": str(snapshot.get("link_url") or "") if snapshot else "",
        "ctaText": str(snapshot.get("cta_text") or "") if snapshot else "",
        "ctaUrl": str(
            snapshot.get("cta_url")
            or snapshot.get("link_url")
            or ""
        ) if snapshot else "",
        "adUrl": _ad_library_url_for(library_id) if library_id else "",
        "_curious_coder": True,
    }
    return canonical


def _curious_coder_attribute_ads(
    canonical_ads: List[Dict[str, Any]],
    page_urls: List[str],
    distributor_mapping: Dict[str, UUID],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Map each canonical ad to one of the input dealer URLs.

    Whoareyouanas uses a fan-out-per-dealer model so each ad is
    implicitly tagged with its source URL by which actor invocation
    produced it. curious_coder is bulk: ads come back interleaved,
    each carrying its own ``pageID`` + ``pageName``. We map back via:

      1. **Slug-by-name index.** Build a slug→page_url map from the
         input list (``yanceyrents`` → ``https://facebook.com/YanceyRents/``).
      2. **Per-ad attribution**, in priority order:
           a) Exact slug match on the ad's ``pageName`` → page_url
              (lowercase, alphanumeric-only normalised both sides).
           b) Substring match on ``pageName`` against any input slug
              (or vice versa) — handles Yancey Rents → yanceyrents
              and "Yancey Rents - The Cat Rental Store" → yancey.bros.co
              edge cases.
           c) Fall through to the first input page_url. Last-resort
              attribution; downstream brand-fallback and matcher
              veto handle the case where the ad genuinely doesn't
              belong to any dealer in the scan.

    Returns the same ``[(source_page_url, ad), …]`` shape produced by
    the whoareyouanas fan-out aggregator, so the downstream
    distributor-resolution + image-insert loop handles both paths
    identically.
    """
    if not canonical_ads or not page_urls:
        return []

    # Build slug → page_url and a normalised-name → page_url index
    # from the dealer URLs supplied to the scan.
    slug_to_url: Dict[str, str] = {}
    for url in page_urls:
        slug = _extract_page_slug(url)
        if slug:
            slug_to_url.setdefault(_normalize_for_match(slug), url)

    out: List[Tuple[str, Dict[str, Any]]] = []
    fallback_url = page_urls[0]

    for ad in canonical_ads:
        page_name = ad.get("pageName") or ""
        page_name_norm = _normalize_for_match(page_name)
        matched: Optional[str] = None

        # (a) exact slug == normalised-name.
        if page_name_norm and page_name_norm in slug_to_url:
            matched = slug_to_url[page_name_norm]

        # (b) substring either direction.
        if not matched and page_name_norm:
            for slug_norm, url in slug_to_url.items():
                if slug_norm and (
                    slug_norm in page_name_norm or page_name_norm in slug_norm
                ):
                    matched = url
                    break

        # (c) fallback.
        out.append((matched or fallback_url, ad))

    return out


def _curious_coder_build_input(
    page_urls: List[str],
    *,
    country: str = "US",
    active_status: str = "active",
    limit_per_source: int = 0,
) -> Dict[str, Any]:
    """Build the JSON body for one bulk curious_coder actor run.

    The actor accepts plain Facebook page URLs in the ``urls`` array
    and figures out the per-page Ad Library URL on its own — that's
    the whole architectural advantage we're trying to validate. We
    just pass the dealer URLs through unchanged.

    ``limit_per_source`` left at 0 → omitted entirely → actor scrapes
    ALL ads per dealer, which is the recall behaviour we want for
    compliance scanning. Set a positive integer during pilot trials
    to bound spend.
    """
    body: Dict[str, Any] = {
        "urls": [{"url": _normalize_fb_url(u)} for u in page_urls],
        "scrapeAdDetails": True,
        "scrapePageAds.activeStatus": active_status,
        "scrapePageAds.countryCode": country,
        "scrapePageAds.sortBy": "most_recent",
    }
    if limit_per_source and limit_per_source > 0:
        body["limitPerSource"] = int(limit_per_source)
    return body


async def _curious_coder_run_bulk(
    page_urls: List[str],
    *,
    country: str = "US",
    active_status: str = "active",
    limit_per_source: int = 0,
) -> Tuple[List[Dict[str, Any]], Optional[float], Optional[str]]:
    """Fire one bulk curious_coder run and return the raw dataset.

    Failure modes (network error, actor failure, dataset fetch error)
    degrade to ``([], None, run_id_or_None)`` and a logged WARNING —
    same contract as ``_run_actor_for_page`` in the whoareyouanas
    path so the caller doesn't have to special-case this.
    """
    actor_input = _curious_coder_build_input(
        page_urls,
        country=country,
        active_status=active_status,
        limit_per_source=limit_per_source,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{APIFY_BASE}/acts/{CURIOUS_CODER_ACTOR_ID}/runs",
                params={"token": settings.apify_api_key},
                json=actor_input,
            )
            resp.raise_for_status()
            run_info = resp.json()["data"]
        run_id = run_info["id"]
        log.info(
            "curious_coder bulk run started for %d dealer(s): %s",
            len(page_urls), run_id,
        )
        completed = await _poll_run(run_id)
    except TimeoutError:
        log.error("curious_coder bulk run timed out")
        return [], None, None
    except Exception as e:
        log.warning("curious_coder bulk run failed to start/poll: %s", e)
        return [], None, None

    if completed.get("status") != "SUCCEEDED":
        log.warning(
            "curious_coder bulk run ended with status %s (run_id=%s)",
            completed.get("status"), completed.get("id"),
        )
        return [], completed.get("usageTotalUsd"), completed.get("id")

    dataset_id = completed.get("defaultDatasetId")
    if not dataset_id:
        log.warning("curious_coder bulk run succeeded but no dataset id returned")
        return [], completed.get("usageTotalUsd"), completed.get("id")

    try:
        ads = await _fetch_dataset_items(dataset_id)
    except Exception as e:
        log.warning("curious_coder dataset fetch failed: %s", e)
        ads = []

    return ads, completed.get("usageTotalUsd"), completed.get("id")


# ---------------------------------------------------------------------------
# Shared persistence helper (used by both actor paths)
# ---------------------------------------------------------------------------

async def _persist_meta_ads_by_source(
    ads_by_source: List[Tuple[str, Dict[str, Any]]],
    *,
    page_urls: List[str],
    distributor_mapping: Dict[str, UUID],
    scan_job_id: UUID,
    channel: str,
    actor_id: str,
) -> int:
    """Resolve images, attribute distributors, and insert
    ``discovered_images`` rows for a list of canonical-shape ads.

    Both the whoareyouanas (fan-out) and curious_coder (bulk) paths
    converge on this function with the same ``[(page_url, ad), …]``
    shape after their own normalisation steps. Centralising this
    logic ensures field-name fixes, image fallback rules, and metadata
    schema changes apply uniformly to both code paths without
    duplication.

    The caller is responsible for:

      * Setting ``scan_jobs.status='running'`` BEFORE calling.
      * Handling the empty-input case (this helper assumes
        ``ads_by_source`` is non-empty; it would set status to
        ``analyzing`` with ``total_items=0`` if called with zero
        ads, which is harmless but the caller usually wants to set
        ``status='completed'`` instead).

    Returns the total number of ``discovered_images`` rows inserted.
    """
    # Sample payload log — shape verification on the wire format.
    sample = ads_by_source[0][1]
    log.info(
        "Sample ad payload (actor=%s) keys: %s | imageUrls=%d, "
        "videoUrls=%d, pageName=%s, adId=%s",
        actor_id,
        list(sample.keys()),
        len(sample.get("imageUrls") or sample.get("images") or []),
        len(sample.get("videoUrls") or sample.get("videos") or []),
        sample.get("pageName") or sample.get("brand"),
        _ad_id(sample),
    )
    log.debug("Full sample ad payload: %s", json.dumps(sample, default=str)[:2000])

    # Image fallback (Playwright Ad Library DOM extraction).
    raw_ads = [ad for _, ad in ads_by_source]
    pw_resolved = await _resolve_images_for_ads(raw_ads)

    # Distributor resolution + insertion.
    slug_map = _build_url_to_distributor_map(page_urls, distributor_mapping)
    img_buffer = DiscoveredImageBuffer()
    ads_with_images = 0
    ads_skipped = 0

    for source_page_url, ad in ads_by_source:
        library_id = _ad_id(ad)
        if not library_id:
            ads_skipped += 1
            continue

        ad_url = ad.get("adUrl") or _ad_library_url_for(library_id)
        brand = ad.get("pageName") or ad.get("brand") or ""
        platforms = ad.get("platforms") or []
        active = ad.get("active")
        ad_status = "active" if active else ("inactive" if active is False else "")
        start_date = ad.get("startDate")
        media_format = ad.get("format") or ""

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
                    "apify_actor": actor_id,
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
        "Apify Meta Ads scan complete (actor=%s): %d images from %d ads "
        "(%d skipped, %d resolved via Playwright)",
        actor_id, total_inserted, ads_with_images, ads_skipped,
        len(pw_resolved),
    )
    return total_inserted


# ---------------------------------------------------------------------------
# curious_coder bulk-run pipeline
# ---------------------------------------------------------------------------

async def _scan_meta_ads_curious_coder(
    page_urls: List[str],
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID],
    *,
    channel: str = "facebook",
) -> int:
    """End-to-end scan via the curious_coder bulk actor.

    Differences from the whoareyouanas path:

      * ONE bulk Apify run, not N fan-out runs. Cost difference at
        the rate card is $0.75/1k ads vs $10/1k.
      * No slug→pageId resolver is needed — the actor accepts plain
        Facebook page URLs and figures out the per-page Ad Library
        URLs internally.
      * Per-ad attribution is via ``pageName`` matching against the
        input URL slugs (``_curious_coder_attribute_ads``) since the
        bulk dataset interleaves ads from every dealer.

    Same downstream insertion path as whoareyouanas — the matcher
    pipeline can't tell which actor produced any given row.
    """
    log.info(
        "Starting Apify Meta Ads scan (channel=%s, actor=%s, MODE=BULK) "
        "for %d page(s)",
        channel, CURIOUS_CODER_ACTOR_ID, len(page_urls),
    )

    supabase.table("scan_jobs").update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", str(scan_job_id)).execute()

    raw_ads, cost_usd, run_id = await _curious_coder_run_bulk(
        page_urls,
        active_status="active",
        limit_per_source=settings.apify_meta_curious_coder_limit_per_source,
    )

    if run_id:
        try:
            from . import cost_tracker
            cost_tracker.record_apify_run(
                actor_or_task=CURIOUS_CODER_ACTOR_ID,
                run_id=run_id,
                usage_total_usd=cost_usd,
                items_returned=len(raw_ads),
            )
        except Exception as cost_err:
            log.debug("Cost capture skipped (curious_coder): %s", cost_err)

    log.info(
        "curious_coder bulk run complete: %d raw ad(s) returned, "
        "$%.4f reported cost",
        len(raw_ads), float(cost_usd or 0.0),
    )

    if not raw_ads:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        log.warning(
            "curious_coder returned 0 ads for %d dealer URL(s) — "
            "scan complete with no creatives", len(page_urls),
        )
        return 0

    canonical_ads = [_curious_coder_normalize(ad) for ad in raw_ads]
    ads_by_source = _curious_coder_attribute_ads(
        canonical_ads, page_urls, distributor_mapping,
    )

    if not ads_by_source:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        return 0

    return await _persist_meta_ads_by_source(
        ads_by_source,
        page_urls=page_urls,
        distributor_mapping=distributor_mapping,
        scan_job_id=scan_job_id,
        channel=channel,
        actor_id=CURIOUS_CODER_ACTOR_ID,
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
    """Scan Meta Ad Library for Facebook/Instagram ad creatives.

    Dispatches to the configured Apify actor:

      * ``whoareyouanas~meta-ad-scraper`` (default, $10/1k ads, fan-out
        per dealer with slug→pageId resolver) — original production
        path. See module docstring + log.md 2026-05-06 entry.

      * ``curious_coder~facebook-ads-library-scraper`` ($0.75/1k ads,
        bulk URL input, no resolver) — feature-flagged 2026-05-07
        for A/B trials. See log.md same date for the full cost /
        reliability comparison and trial plan.

    Public signature is identical for both paths — callers don't
    have to know which actor is active.

    Returns the total number of discovered images inserted.
    """
    if not settings.apify_api_key:
        raise ValueError(
            "APIFY_API_KEY is not configured. "
            "Set it in your .env file to enable Meta Ads scanning."
        )

    if not page_urls:
        raise ValueError("No Facebook page URLs provided for Meta Ads scan.")

    # Dispatch to the curious_coder bulk path when the operator has
    # opted into it via env. Default actor remains whoareyouanas, so
    # the deployed behaviour does NOT change unless APIFY_META_ACTOR_ID
    # is explicitly set.
    if _is_curious_coder_active():
        return await _scan_meta_ads_curious_coder(
            page_urls, scan_job_id, distributor_mapping, channel=channel,
        )

    log.info(
        "Starting Apify Meta Ads scan (%s, actor=%s) for %d page(s) "
        "[fan-out parallelism=%d]",
        channel, WHOAREYOUANAS_ACTOR_ID, len(page_urls),
        settings.apify_meta_max_parallel_runs,
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
    # Per-dealer outcome, keyed by normalized page URL (the same key
    # reuse-coverage compares against). Lets the reuse flow tell a
    # cleanly-scanned-empty dealer ("succeeded", 0 ads) apart from a
    # transient failure, so we never re-scrape the former or wrongly
    # skip the latter.
    dealer_outcomes: Dict[str, Dict[str, Any]] = {}
    for result in fan_results:
        if isinstance(result, BaseException):
            log.warning("Fan-out task crashed: %s", result)
            continue
        page_url, ads, cost_usd, run_id, outcome = result
        dealer_outcomes[_outcome_key(page_url)] = {
            "status": outcome,
            "ad_count": len(ads),
        }
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

    _merge_scan_metadata(scan_job_id, {"dealer_outcomes": dealer_outcomes})

    if not ads_by_source:
        supabase.table("scan_jobs").update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
        }).eq("id", str(scan_job_id)).execute()
        log.warning("No ads found for any provided Facebook pages")
        return 0

    return await _persist_meta_ads_by_source(
        ads_by_source,
        page_urls=page_urls,
        distributor_mapping=distributor_mapping,
        scan_job_id=scan_job_id,
        channel=channel,
        actor_id=WHOAREYOUANAS_ACTOR_ID,
    )
