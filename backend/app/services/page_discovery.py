"""
Page discovery service — finds promotional pages on dealer websites.

Three strategies, in priority order:
  1. Common promotional paths — probe /specials, /deals, /offers, etc.
     These get guaranteed slots because they are the most likely
     locations for campaign creatives.
  2. Sitemap parsing — fetch /sitemap.xml, fill remaining slots with
     promotional URLs first, then other pages.
  3. Link crawling — extract internal links from the homepage to fill
     any remaining slots.

WAF-protected hosts (Akamai/Cloudflare/Imperva/...) have a fourth path:
the same direct-httpx strategies are silently 0-result on these sites
because the WAF closes the TCP/TLS connection before responding. When
``host_policy_service`` reports the host on an unlocker-grade strategy,
or when the three direct strategies returned only the base URL, we
issue ONE Bright Data request for the homepage and parse its post-render
DOM for ``<a href>`` links. That gives discovery the same WAF bypass
that page extraction already has — without it, every WAF dealer scans
exactly 1 page (the base URL) regardless of the per-site page budget.

Cost impact: roughly ~$0.0015 per WAF-protected dealer per scan
(one extra Bright Data request). Negligible relative to the ~$0.03 per
dealer the per-page extraction unlocks already cost.

The result is a deduplicated list of page URLs most likely to contain
campaign creatives, capped at a configurable maximum.
"""
import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from ..config import get_settings

log = logging.getLogger("dealer_intel.page_discovery")

settings = get_settings()


# Strategies for which we should skip the direct httpx probes entirely
# and go straight to the unlocker. These are the strategies that
# host_policy_service has already learned indicate a WAF that drops
# anonymous probes — sending 24 HEAD requests there just wastes 100ms.
# Imported lazily inside discover_pages() to avoid a top-level cycle
# (host_policy_service -> render_strategies -> nothing here yet, but
# keeping the late-import lets the module load even if the policy
# table is being migrated).
_WAF_GRADE_STRATEGIES = frozenset({
    "playwright_then_unlocker",
    "unlocker_only",
    "unreachable",
})

_CLIENT_MAX_AGE_SECONDS = 300  # recycle httpx client every 5 minutes

PROMO_KEYWORDS = {
    "promo", "promotion", "promotions", "deal", "deals", "offer", "offers",
    "special", "specials", "sale", "sales", "shop", "store", "buy",
    "campaign", "featured", "new", "latest", "clearance",
    "rebate", "rebates", "incentive", "incentives", "savings",
    "financing", "coupon", "coupons", "discount", "discounts",
    "inventory", "products", "services", "catalog",
    "events", "seasonal", "limited", "exclusive",
}

COMMON_PROMO_PATHS = [
    "/",
    "/specials",
    "/specials/",
    "/promotions",
    "/promotions/",
    "/deals",
    "/deals/",
    "/offers",
    "/offers/",
    "/sale",
    "/sales",
    "/shop",
    "/shop/",
    "/featured",
    "/new",
    "/inventory",
    "/products",
    "/services",
    "/events",
    "/rebates",
    "/incentives",
    "/financing",
    "/clearance",
    "/catalog",
]

_http_client: Optional[httpx.AsyncClient] = None
_http_client_created_at: float = 0.0


async def _get_client() -> httpx.AsyncClient:
    global _http_client, _http_client_created_at
    stale = (time.monotonic() - _http_client_created_at) > _CLIENT_MAX_AGE_SECONDS
    if _http_client is None or _http_client.is_closed or stale:
        if _http_client is not None and not _http_client.is_closed:
            try:
                await _http_client.aclose()
            except Exception:
                pass
        _http_client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        _http_client_created_at = time.monotonic()
        log.debug("Created fresh httpx client for page discovery")
    return _http_client


def _normalize_url(url: str) -> str:
    """Strip fragments and trailing slashes for deduplication."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _is_same_domain(url: str, base_domain: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
        return host == base_domain
    except Exception:
        return False


def _url_looks_promotional(url: str) -> bool:
    """Check if a URL path contains promotional keywords."""
    path = urlparse(url).path.lower()
    segments = re.split(r"[/\-_.]", path)
    return any(seg in PROMO_KEYWORDS for seg in segments if seg)


# Hrefs containing any of these substrings are unrendered template
# placeholders that AEM / Mustache / JSP / ASP / Template Toolkit emits
# when the server-side render didn't substitute the variable. Sending
# them anywhere downstream produces guaranteed 400s (or worse, "success"
# fetches of literal placeholder text). Caught BEFORE urljoin so the
# resolved URL never enters the discovery list.
#
# Real-world sample from the 2026-04-30 production scan that motivated
# this filter: <a href="{{path}}.html"> on rent.cat.com dealer pages
# rendered 17 dealers' discovery into <dealer>/{{path}}.html, each of
# which then burned a Bright Data request returning HTTP 400.
_TEMPLATE_PLACEHOLDER_MARKERS: Tuple[str, ...] = (
    "{{", "}}",   # Mustache / Handlebars / Vue
    "${",          # ES6 template literals / JSP EL / Thymeleaf
    "<%", "%>",   # ASP / JSP / ERB scriptlets
    "[%", "%]",   # Template Toolkit
)


def _href_is_safe(href: str) -> bool:
    """Reject hrefs that would resolve to garbage URLs.

    Three failure shapes seen in production:

    1. Unrendered template placeholders ``{{path}}.html`` etc. — the
       page server-side rendered without substituting the variable.
       Resolves to a real-looking URL that 400s at Bright Data.
    2. Whitespace anywhere in the href — usually a copy/paste error in
       the page's HTML; Bright Data and most servers reject these
       with no meaningful body.
    3. Control characters — same idea, almost always a mis-escaped
       template variable on the page side.

    Returning False here drops the href silently. The caller logs at
    DEBUG only since these are very common on AEM-templated pages.
    """
    if not href or len(href) > 2048:
        return False
    for marker in _TEMPLATE_PLACEHOLDER_MARKERS:
        if marker in href:
            return False
    # Any ASCII whitespace or control character is a tell. Trailing
    # whitespace already gets stripped by the regex bounds, but inline
    # whitespace inside the URL is the actual smell.
    for ch in href:
        if ch.isspace() or ord(ch) < 0x20:
            return False
    return True


def _is_scannable_page(url: str) -> bool:
    """Filter out non-page resources (images, PDFs, etc).

    Also rejects URLs whose path or query carries an unrendered template
    placeholder — defence in depth for callers that bypassed
    :func:`_href_is_safe` (e.g. URLs from a sitemap)."""
    if not _href_is_safe(url):
        return False
    path = urlparse(url).path.lower()
    skip_extensions = {
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".gz",
        ".css", ".js", ".json", ".xml", ".txt", ".mp4", ".mp3",
        ".woff", ".woff2", ".ttf", ".eot",
    }
    for ext in skip_extensions:
        if path.endswith(ext):
            return False
    skip_patterns = [
        "/wp-content/", "/wp-admin/", "/cdn-cgi/", "/api/",
        "/cart", "/checkout", "/login", "/signin", "/account",
        "/privacy", "/terms", "/sitemap", "/feed", "/rss",
        "/tag/", "/author/", "/page/", "#",
        "/blog",
    ]
    for pattern in skip_patterns:
        if pattern in path.lower():
            return False
    return True


async def _fetch_sitemap_urls(base_url: str) -> List[str]:
    """Parse /sitemap.xml and return all page URLs."""
    parsed = urlparse(base_url)
    sitemap_urls_to_try = [
        f"{parsed.scheme}://{parsed.netloc}/sitemap.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml",
        f"{parsed.scheme}://{parsed.netloc}/sitemap1.xml",
    ]

    client = await _get_client()
    all_urls: List[str] = []

    for sitemap_url in sitemap_urls_to_try:
        try:
            resp = await client.get(sitemap_url)
            if resp.status_code != 200:
                continue

            content = resp.text
            if "<sitemapindex" in content:
                all_urls.extend(await _parse_sitemap_index(content, parsed))
            else:
                all_urls.extend(_parse_sitemap_urlset(content))

            if all_urls:
                log.info("Sitemap found at %s: %d URLs", sitemap_url, len(all_urls))
                break
        except Exception as e:
            log.debug("Sitemap fetch failed (%s): %s", sitemap_url, e)
            continue

    return all_urls


async def _parse_sitemap_index(content: str, parsed_base) -> List[str]:
    """Parse a sitemap index file and fetch child sitemaps."""
    urls: List[str] = []
    try:
        root = ET.fromstring(content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        sitemap_locs = [
            el.text for el in root.findall(".//sm:loc", ns)
            if el.text
        ]
        if not sitemap_locs:
            sitemap_locs = [
                el.text for el in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                if el.text
            ]

        client = await _get_client()
        for loc in sitemap_locs[:5]:
            try:
                resp = await client.get(loc)
                if resp.status_code == 200:
                    urls.extend(_parse_sitemap_urlset(resp.text))
            except Exception:
                continue
    except ET.ParseError:
        pass
    return urls


def _parse_sitemap_urlset(content: str) -> List[str]:
    """Parse a sitemap urlset and return all <loc> URLs."""
    urls: List[str] = []
    try:
        root = ET.fromstring(content)
        for el in root.iter():
            if el.tag.endswith("}loc") or el.tag == "loc":
                if el.text and el.text.startswith("http"):
                    urls.append(el.text.strip())
    except ET.ParseError:
        loc_pattern = re.compile(r"<loc>\s*(https?://[^<]+)\s*</loc>", re.IGNORECASE)
        urls = loc_pattern.findall(content)
    return urls


def _filter_sitemap_urls(urls: List[str], base_domain: str, max_pages: int) -> List[str]:
    """Filter sitemap URLs to those likely to have promotional content."""
    promo_urls: List[str] = []
    other_urls: List[str] = []

    for url in urls:
        if not _is_same_domain(url, base_domain):
            continue
        if not _is_scannable_page(url):
            continue
        if _url_looks_promotional(url):
            promo_urls.append(url)
        else:
            other_urls.append(url)

    result = promo_urls[:max_pages]
    remaining = max_pages - len(result)
    if remaining > 0:
        result.extend(other_urls[:remaining])

    return result


async def _crawl_homepage_links(base_url: str, base_domain: str) -> List[str]:
    """Extract internal links from the homepage HTML."""
    client = await _get_client()
    try:
        resp = await client.get(base_url)
        if resp.status_code != 200:
            return []

        html = resp.text
        link_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        raw_links = link_pattern.findall(html)

        urls: Set[str] = set()
        skipped_template = 0
        for href in raw_links:
            if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            if href.startswith("javascript:"):
                continue
            if not _href_is_safe(href):
                skipped_template += 1
                continue

            full_url = urljoin(base_url, href)
            if _is_same_domain(full_url, base_domain) and _is_scannable_page(full_url):
                urls.add(_normalize_url(full_url))

        if skipped_template:
            log.debug(
                "Crawled homepage: dropped %d unrendered template href(s)",
                skipped_template,
            )
        log.info("Crawled homepage: %d internal links", len(urls))
        return list(urls)

    except Exception as e:
        log.error("Homepage crawl failed: %s", e)
        return []


async def _probe_common_paths(base_url: str) -> List[str]:
    """Try common promotional paths and return those that respond 200."""
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    client = await _get_client()
    valid: List[str] = []

    errors = []

    async def _probe(path: str):
        url = f"{origin}{path}"
        try:
            resp = await client.head(url)
            if resp.status_code == 200:
                valid.append(_normalize_url(url))
        except Exception as e:
            errors.append((path, str(e)))

    tasks = [_probe(p) for p in COMMON_PROMO_PATHS]
    await asyncio.gather(*tasks)

    log.info("Probed %d common paths: %d valid", len(COMMON_PROMO_PATHS), len(valid))
    if not valid and errors:
        log.warning(
            "All %d path probes failed for %s — first error: %s",
            len(errors), base_url, errors[0][1][:200],
        )
    return valid


async def _crawl_homepage_links_via_unlocker(
    base_url: str,
    base_domain: str,
) -> List[str]:
    """Fetch the homepage HTML through Bright Data and extract internal
    links from it. Used when the host is on a WAF-grade strategy or
    when the direct crawl returned nothing useful.

    The link-extraction logic is deliberately a copy of
    ``_crawl_homepage_links`` rather than a refactor: we want the
    direct path to work without taking any dependency on the unlocker
    module (it must keep running on hosts that have no Bright Data
    config), and we want the unlocker path to fail soft if the
    unlocker module is unimportable for any reason. Two short copies,
    not one shared abstraction.
    """
    try:
        from . import unlocker_service  # late import: optional dep
    except Exception as e:
        log.debug("Unlocker module unavailable for discovery: %s", e)
        return []

    if not unlocker_service.is_available():
        log.info(
            "Skipping unlocker-based discovery for %s — rung disabled",
            base_url[:80],
        )
        return []

    html_text, http_status, error = await unlocker_service._post_unlocker_text(
        base_url,
    )
    if not html_text:
        log.warning(
            "Unlocker discovery failed for %s (http=%s err=%s)",
            base_url[:80], http_status, error,
        )
        return []

    # Same regex-only extraction as the direct path. We could swap to
    # BeautifulSoup for resilience against weird HTML, but the regex
    # has been stable for months and a parsing-library bump here would
    # affect every dealer scan.
    link_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    raw_links = link_pattern.findall(html_text)

    urls: Set[str] = set()
    skipped_template = 0
    for href in raw_links:
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("javascript:"):
            continue
        if not _href_is_safe(href):
            # Mustache / JSP / ASP placeholder. Resolves to a real-looking
            # URL that 400s at Bright Data and never contains content.
            # See log.md 2026-04-30 / Phase 6.5.3 for the production
            # incident that motivated this filter.
            skipped_template += 1
            continue

        full_url = urljoin(base_url, href)
        if _is_same_domain(full_url, base_domain) and _is_scannable_page(full_url):
            urls.add(_normalize_url(full_url))

    if skipped_template:
        log.debug(
            "Unlocker discovery on %s: dropped %d unrendered template href(s)",
            base_url[:80], skipped_template,
        )

    # Once the unlocker produced HTML for this host, every later asset
    # download on the same host should also go through it. We stamp
    # the unlocked-hosts registry here so the per-page extraction
    # phase doesn't have to wait for its own first unlock to happen.
    try:
        unlocker_service.mark_host_unlocked(base_url)
    except Exception:
        pass

    log.info(
        "Unlocker-discovered %d internal link(s) on %s (http=%s)",
        len(urls), base_url[:80], http_status,
    )
    return list(urls)


async def discover_pages(
    base_url: str,
    max_pages: int = 15,
) -> List[str]:
    """
    Discover pages on a dealer website that are likely to contain
    campaign creatives.

    Common promotional paths (``/specials/``, ``/deals/``, etc.) are
    probed first and given guaranteed priority slots because they are
    the most likely locations for campaign creatives.  Remaining slots
    are filled from the sitemap and homepage link crawl.

    If ``host_policy_service`` reports the host on a WAF-grade
    strategy (``unlocker_only``, ``playwright_then_unlocker``,
    ``unreachable``), the three direct strategies are skipped entirely
    — they are guaranteed to return 0 results on those hosts and
    waste ~100ms of TCP/TLS aborts. We go straight to the unlocker for
    homepage link parsing instead. As a defence-in-depth, we also fall
    back to the unlocker if the direct path returned only the base URL
    (the symptom that motivated this whole code path).
    """
    parsed = urlparse(base_url)
    base_domain = parsed.netloc.lower().replace("www.", "")
    normalized_base = _normalize_url(base_url)

    seen: Set[str] = set()
    result: List[str] = []

    def _add(url: str):
        norm = _normalize_url(url)
        if norm not in seen:
            seen.add(norm)
            result.append(norm)

    _add(normalized_base)

    log.info("Starting page discovery for %s (max %d pages)", base_url, max_pages)

    # Decide upfront whether to skip the direct probes. Failure to
    # read the policy is fine — we default to "try direct first" which
    # is the safe fallback for hosts we know nothing about.
    skip_direct = False
    try:
        from . import host_policy_service  # late import to avoid cycles
        strategy = host_policy_service.get_strategy(base_url)
        skip_direct = strategy in _WAF_GRADE_STRATEGIES
        if skip_direct:
            log.info(
                "Host %s on strategy %s — skipping direct probes, using unlocker for discovery",
                base_domain, strategy,
            )
    except Exception as e:
        log.debug("host_policy lookup failed for discovery (%s): %s", base_domain, e)

    if not skip_direct:
        # Priority: common promotional paths get slots first — these
        # are the pages most likely to contain campaign creatives.
        probed = await _probe_common_paths(base_url)
        for url in probed:
            _add(url)
        log.debug("After common promo paths: %d pages", len(result))

        # Fill remaining slots from sitemap (promo URLs first)
        if len(result) < max_pages:
            sitemap_urls = await _fetch_sitemap_urls(base_url)
            if sitemap_urls:
                remaining = max_pages - len(result)
                filtered = _filter_sitemap_urls(
                    sitemap_urls, base_domain, remaining * 2,
                )
                for url in filtered:
                    if len(result) >= max_pages:
                        break
                    _add(url)
                log.debug("After sitemap: %d pages", len(result))

        # Fill remaining slots from homepage link crawl (promo URLs first)
        if len(result) < max_pages:
            crawled = await _crawl_homepage_links(base_url, base_domain)
            promo_links = [u for u in crawled if _url_looks_promotional(u)]
            other_links = [u for u in crawled if not _url_looks_promotional(u)]
            for url in promo_links:
                if len(result) >= max_pages:
                    break
                _add(url)
            for url in other_links:
                if len(result) >= max_pages:
                    break
                _add(url)
            log.debug("After link crawl: %d pages", len(result))

    # Unlocker fallback: triggered either because we skipped direct
    # (known WAF host) or because direct returned only the base URL
    # (likely-but-unconfirmed WAF). One extra Bright Data request per
    # affected dealer per scan — see module docstring for cost notes.
    needs_unlocker_fallback = skip_direct or len(result) <= 1
    if needs_unlocker_fallback and len(result) < max_pages:
        unlocker_links = await _crawl_homepage_links_via_unlocker(
            base_url, base_domain,
        )
        promo_links = [u for u in unlocker_links if _url_looks_promotional(u)]
        other_links = [u for u in unlocker_links if not _url_looks_promotional(u)]
        for url in promo_links:
            if len(result) >= max_pages:
                break
            _add(url)
        for url in other_links:
            if len(result) >= max_pages:
                break
            _add(url)
        log.debug("After unlocker crawl: %d pages", len(result))

    final = result[:max_pages]
    log.info(
        "Final: %d pages to scan for %s (skip_direct=%s, unlocker_used=%s)",
        len(final), base_domain, skip_direct, needs_unlocker_fallback,
    )
    for i, url in enumerate(final):
        log.debug("  [%d] %s", i + 1, url)

    return final
