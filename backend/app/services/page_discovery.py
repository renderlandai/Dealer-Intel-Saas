"""
Page discovery service — finds promotional pages on dealer websites.

Three strategies, tried in order:
  1. Sitemap parsing — fetch /sitemap.xml, filter for promotional URLs
  2. Link crawling — extract internal links from the homepage
  3. Common path heuristics — try well-known promotional paths

The result is a deduplicated list of page URLs most likely to contain
campaign creatives, capped at a configurable maximum.
"""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import List, Set, Optional
from urllib.parse import urljoin, urlparse

import httpx

from ..config import get_settings

log = logging.getLogger("dealer_intel.page_discovery")

settings = get_settings()

PROMO_KEYWORDS = {
    "promo", "promotion", "promotions", "deal", "deals", "offer", "offers",
    "special", "specials", "sale", "sales", "shop", "store", "buy",
    "campaign", "samsung", "galaxy", "iphone", "apple", "pixel", "motorola",
    "device", "devices", "phone", "phones", "smartphone", "trade-in",
    "tradein", "upgrade", "plan", "plans", "wireless", "5g", "unlimited",
    "accessories", "tablet", "watch", "fios", "internet", "bundle",
    "featured", "new", "latest", "hot", "best", "top",
}

COMMON_PROMO_PATHS = [
    "/",
    "/promotions",
    "/promotions/",
    "/deals",
    "/deals/",
    "/offers",
    "/offers/",
    "/specials",
    "/specials/",
    "/shop",
    "/shop/",
    "/devices",
    "/devices/",
    "/phones",
    "/phones/",
    "/plans",
    "/plans/",
    "/samsung",
    "/samsung/",
    "/apple",
    "/apple/",
    "/smartphones",
    "/smartphones/",
    "/trade-in",
    "/accessories",
    "/new",
    "/featured",
]

_http_client: Optional[httpx.AsyncClient] = None


async def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
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


def _is_scannable_page(url: str) -> bool:
    """Filter out non-page resources (images, PDFs, etc)."""
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
        for href in raw_links:
            if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            if href.startswith("javascript:"):
                continue

            full_url = urljoin(base_url, href)
            if _is_same_domain(full_url, base_domain) and _is_scannable_page(full_url):
                urls.add(_normalize_url(full_url))

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

    async def _probe(path: str):
        url = f"{origin}{path}"
        try:
            resp = await client.head(url)
            if resp.status_code == 200:
                valid.append(_normalize_url(url))
        except Exception:
            pass

    tasks = [_probe(p) for p in COMMON_PROMO_PATHS]
    await asyncio.gather(*tasks)

    log.info("Probed %d common paths: %d valid", len(COMMON_PROMO_PATHS), len(valid))
    return valid


async def discover_pages(
    base_url: str,
    max_pages: int = 15,
) -> List[str]:
    """
    Discover pages on a dealer website that are likely to contain
    campaign creatives.

    Tries sitemap first, then homepage link crawling, then common
    path heuristics. Returns a deduplicated list capped at max_pages.
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

    # Strategy 1: Sitemap
    sitemap_urls = await _fetch_sitemap_urls(base_url)
    if sitemap_urls:
        filtered = _filter_sitemap_urls(sitemap_urls, base_domain, max_pages * 2)
        for url in filtered:
            _add(url)
        log.debug("After sitemap: %d pages", len(result))

    # Strategy 2: Homepage link crawl
    if len(result) < max_pages:
        crawled = await _crawl_homepage_links(base_url, base_domain)
        promo_links = [u for u in crawled if _url_looks_promotional(u)]
        other_links = [u for u in crawled if not _url_looks_promotional(u)]
        for url in promo_links:
            _add(url)
        for url in other_links:
            if len(result) >= max_pages:
                break
            _add(url)
        log.debug("After link crawl: %d pages", len(result))

    # Strategy 3: Common paths (only if we still have very few)
    if len(result) < 5:
        probed = await _probe_common_paths(base_url)
        for url in probed:
            _add(url)
        log.debug("After common paths: %d pages", len(result))

    final = result[:max_pages]
    log.info("Final: %d pages to scan for %s", len(final), base_domain)
    for i, url in enumerate(final):
        log.debug("  [%d] %s", i + 1, url)

    return final
