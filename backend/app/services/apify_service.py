"""Apify scraper integration service."""
from apify_client import ApifyClient
from typing import List, Dict, Any, Optional
from uuid import UUID
import asyncio
import httpx
from io import BytesIO

from ..config import get_settings
from ..database import supabase

settings = get_settings()


async def validate_screenshot_quality(screenshot_url: str) -> Dict[str, Any]:
    """
    Validate a screenshot to detect lazy/incomplete renders.
    
    Checks for:
    - Very small file size (likely placeholder or broken)
    - Mostly uniform color (blank page or loading state)
    - Missing content indicators
    
    Returns:
        Dict with 'is_valid', 'confidence', and 'issues' list
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(screenshot_url)
            if response.status_code != 200:
                return {
                    "is_valid": False,
                    "confidence": 0,
                    "issues": [f"Failed to fetch screenshot: HTTP {response.status_code}"]
                }
            
            image_bytes = response.content
            file_size = len(image_bytes)
            
            issues = []
            confidence = 100
            
            # Check 1: File size - very small screenshots are likely incomplete
            # A proper full-page screenshot should be at least 50KB
            if file_size < 10000:  # Less than 10KB
                issues.append(f"Screenshot too small ({file_size} bytes) - likely placeholder or error page")
                confidence -= 50
            elif file_size < 50000:  # Less than 50KB
                issues.append(f"Screenshot smaller than expected ({file_size} bytes) - may be incomplete")
                confidence -= 20
            
            # Check 2: Try to analyze image for blank/loading indicators
            try:
                from PIL import Image
                img = Image.open(BytesIO(image_bytes))
                width, height = img.size
                
                # Very small dimensions indicate issues
                if width < 800 or height < 600:
                    issues.append(f"Screenshot dimensions too small ({width}x{height})")
                    confidence -= 30
                
                # Check for mostly uniform color (blank page)
                # Sample pixels from different areas
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Sample 9 points across the image
                sample_points = [
                    (width // 4, height // 4),
                    (width // 2, height // 4),
                    (3 * width // 4, height // 4),
                    (width // 4, height // 2),
                    (width // 2, height // 2),
                    (3 * width // 4, height // 2),
                    (width // 4, 3 * height // 4),
                    (width // 2, 3 * height // 4),
                    (3 * width // 4, 3 * height // 4),
                ]
                
                colors = [img.getpixel(p) for p in sample_points]
                
                # Check if all sampled colors are nearly identical (blank page)
                first_color = colors[0]
                uniform_count = sum(1 for c in colors if all(abs(c[i] - first_color[i]) < 10 for i in range(3)))
                
                if uniform_count >= 8:  # 8 out of 9 samples are the same color
                    issues.append("Screenshot appears mostly blank/uniform - likely loading state")
                    confidence -= 40
                
                # Check for white/gray loading screen indicators
                avg_brightness = sum(sum(c) / 3 for c in colors) / len(colors)
                if avg_brightness > 245:  # Very bright (white loading screen)
                    issues.append("Screenshot is mostly white - may be loading state")
                    confidence -= 25
                    
            except ImportError:
                # PIL not available, skip image analysis
                pass
            except Exception as img_error:
                print(f"[Screenshot Validation] Image analysis error: {img_error}")
            
            return {
                "is_valid": confidence >= 50,
                "confidence": max(0, confidence),
                "issues": issues,
                "file_size": file_size
            }
            
    except Exception as e:
        return {
            "is_valid": False,
            "confidence": 0,
            "issues": [f"Validation error: {str(e)}"]
        }

# Initialize Apify client
apify = ApifyClient(settings.apify_api_token)


# Apify Actor IDs - use actual actor IDs, not names
ACTORS = {
    "google_ads": "3Y5oM7ystipacxama",  # Google Ads Transparency scraper
    "facebook": "curios/facebook-ads-scraper",
    "website": "apify/website-content-crawler",
    "web_scraper": "apify/web-scraper"  # For custom scraping tasks
}


async def lookup_google_ads_advertiser_id(company_name: str) -> Optional[Dict[str, Any]]:
    """
    Look up a Google Ads Advertiser ID by searching the Google Ads Transparency Center.
    
    Uses Playwright-based scraping with proper waiting for dynamic content.
    
    Args:
        company_name: The company name to search for
        
    Returns:
        Dict with advertiser_id, advertiser_name, and url if found, None otherwise
    """
    from urllib.parse import quote
    
    print(f"[Advertiser Lookup] Searching for: {company_name}")
    
    encoded_name = quote(company_name.strip())
    search_url = f"https://adstransparency.google.com/?region=anywhere&query={encoded_name}"
    
    # Use web-scraper actor with Playwright and better waiting
    run_input = {
        "startUrls": [{"url": search_url}],
        "pageFunction": """
            async function pageFunction(context) {
                const { page, request, log } = context;
                
                log.info('Starting search on: ' + request.url);
                
                // Wait longer for the page to fully load (it's a heavy JS app)
                await page.waitForTimeout(5000);
                
                // Try to wait for search results container
                try {
                    await page.waitForSelector('[role="listbox"], [role="list"], .search-results, [data-advertiser-id]', { timeout: 10000 });
                } catch (e) {
                    log.info('Could not find specific selector, continuing anyway...');
                }
                
                // Additional wait for dynamic content
                await page.waitForTimeout(3000);
                
                // Get the page HTML for debugging
                const html = await page.content();
                log.info('Page HTML length: ' + html.length);
                
                const results = [];
                
                // Method 1: Look for links with /advertiser/ in href
                const advertiserLinks = await page.$$('a[href*="/advertiser/"]');
                log.info('Found ' + advertiserLinks.length + ' advertiser links');
                
                for (const link of advertiserLinks) {
                    try {
                        const href = await link.getAttribute('href');
                        if (!href) continue;
                        
                        // Extract AR ID from the href
                        const match = href.match(/\\/advertiser\\/(AR\\d+)/);
                        if (match) {
                            // Try to get the text content
                            let text = await link.textContent();
                            if (!text || text.trim() === '') {
                                // Try to get text from parent or nearby elements
                                const parent = await link.$('xpath=..');
                                if (parent) {
                                    text = await parent.textContent();
                                }
                            }
                            
                            results.push({
                                advertiser_id: match[1],
                                advertiser_name: text ? text.trim().substring(0, 200) : '',
                                url: href.startsWith('http') ? href : 'https://adstransparency.google.com' + href
                            });
                            log.info('Found advertiser: ' + match[1]);
                        }
                    } catch (e) {
                        log.error('Error extracting link: ' + e.message);
                    }
                }
                
                // Method 2: Look for AR IDs directly in the page content
                if (results.length === 0) {
                    const arMatches = html.match(/AR\\d{15,25}/g);
                    if (arMatches) {
                        log.info('Found ' + arMatches.length + ' AR IDs in page content');
                        const uniqueIds = [...new Set(arMatches)];
                        for (const arId of uniqueIds.slice(0, 5)) {
                            results.push({
                                advertiser_id: arId,
                                advertiser_name: '',
                                url: 'https://adstransparency.google.com/advertiser/' + arId
                            });
                        }
                    }
                }
                
                log.info('Total results found: ' + results.length);
                return results;
            }
        """,
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"]
        },
        "maxConcurrency": 1,
        "maxRequestsPerCrawl": 1,
        "preNavigationHooks": """[
            async ({ page }) => {
                // Set a realistic viewport (Puppeteer API)
                await page.setViewport({ width: 1920, height: 1080 });
            }
        ]"""
    }
    
    try:
        print(f"[Advertiser Lookup] Running web scraper for: {search_url}")
        run = apify.actor(ACTORS["web_scraper"]).call(run_input=run_input, timeout_secs=120)
        
        # Get results
        dataset_id = run.get("defaultDatasetId")
        if dataset_id:
            items = list(apify.dataset(dataset_id).iterate_items())
            print(f"[Advertiser Lookup] Found {len(items)} result sets")
            
            # Flatten results and find best match
            all_results = []
            for item in items:
                if isinstance(item, list):
                    all_results.extend(item)
                elif isinstance(item, dict) and item.get("advertiser_id"):
                    all_results.append(item)
            
            if all_results:
                # Return the first/best match
                result = all_results[0]
                print(f"[Advertiser Lookup] Found advertiser: {result}")
                return result
        
        print(f"[Advertiser Lookup] No advertiser found for: {company_name}")
        return None
        
    except Exception as e:
        print(f"[Advertiser Lookup] Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def start_google_ads_scrape(
    advertiser_names: List[str],
    scan_job_id: UUID
) -> str:
    """
    Start a Google Ads transparency scrape.
    
    Args:
        advertiser_names: List of advertiser names to search
        scan_job_id: ID of the scan job record
        
    Returns:
        Apify run ID
    """
    print(f"[Google Ads Scrape] Starting scrape for {len(advertiser_names)} advertisers: {advertiser_names}")
    
    # Build URLs for each advertiser
    # NOTE: This actor only accepts direct advertiser URLs with advertiser IDs
    # Format: https://adstransparency.google.com/advertiser/AR12345678901234567?region=anywhere
    start_urls = []
    skipped_names = []
    
    for name in advertiser_names:
        if not name or not name.strip():
            continue
        
        name = name.strip()
        
        # Check if it's an advertiser ID (starts with AR followed by numbers)
        if name.startswith("AR") and len(name) > 2 and name[2:].isdigit():
            # Direct advertiser URL with ID
            url = f"https://adstransparency.google.com/advertiser/{name}?region=anywhere"
            start_urls.append({"url": url})
            print(f"[Google Ads Scrape] Added advertiser ID URL: {url}")
        else:
            # This actor doesn't support search by name - need actual advertiser IDs
            skipped_names.append(name)
            print(f"[Google Ads Scrape] SKIPPED '{name}' - not a valid advertiser ID (format: AR + numbers)")
    
    if skipped_names:
        print(f"[Google Ads Scrape] WARNING: {len(skipped_names)} distributors skipped - they need Google Ads Advertiser IDs")
        print(f"[Google Ads Scrape] To find IDs: Go to adstransparency.google.com, search the company, copy the AR... ID from the URL")
    
    # Validate we have at least one URL to scrape
    if not start_urls:
        if skipped_names:
            error_msg = f"No valid Google Ads Advertiser IDs found. Distributors need IDs like 'AR18135649662495883265'. Skipped: {', '.join(skipped_names[:3])}{'...' if len(skipped_names) > 3 else ''}"
        else:
            error_msg = "No distributors found to scan"
        print(f"[Google Ads Scrape] ERROR: {error_msg}")
        supabase.table("scan_jobs").update({
            "status": "failed",
            "error_message": error_msg
        }).eq("id", str(scan_job_id)).execute()
        raise ValueError(error_msg)
    
    run_input = {
        "startUrls": start_urls,
        "cookies": [],
        "maxItems": 100,
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyGroups": [],
        },
        "downloadMedia": True,
    }
    
    print(f"[Google Ads Scrape] Calling Apify actor {ACTORS['google_ads']} with {len(start_urls)} URLs")
    
    # Start the actor run
    run = apify.actor(ACTORS["google_ads"]).call(run_input=run_input)
    
    # Update scan job with run ID
    supabase.table("scan_jobs").update({
        "apify_run_id": run["id"],
        "status": "running",
        "started_at": "now()"
    }).eq("id", str(scan_job_id)).execute()
    
    return run["id"]


async def start_facebook_ads_scrape(
    page_urls: List[str],
    scan_job_id: UUID
) -> str:
    """
    Start a Facebook/Instagram ads scrape.
    
    Args:
        page_urls: List of Facebook page URLs
        scan_job_id: ID of the scan job record
        
    Returns:
        Apify run ID
    """
    run_input = {
        "startUrls": [{"url": url} for url in page_urls],
        "maxPosts": 1,  # Limited for testing
        "proxyConfiguration": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"]
        }
    }
    
    run = apify.actor(ACTORS["facebook"]).call(run_input=run_input)
    
    supabase.table("scan_jobs").update({
        "apify_run_id": run["id"],
        "status": "running",
        "started_at": "now()"
    }).eq("id", str(scan_job_id)).execute()
    
    return run["id"]


async def start_website_crawl(
    website_urls: List[str],
    scan_job_id: UUID
) -> str:
    """
    Start a website content crawl using the reliable website-content-crawler.
    
    Uses apify/website-content-crawler with extended wait times for lazy loading.
    
    Returns:
    - url: the crawled page URL
    - title: page title
    - markdown: page content as markdown (includes image references)
    - text: plain text content
    - screenshotUrl: screenshot of the rendered page
    
    Args:
        website_urls: List of website URLs to crawl
        scan_job_id: ID of the scan job record
        
    Returns:
        Apify run ID
    """
    print(f"[Website Scan] Starting crawl for {len(website_urls)} URLs: {website_urls}")
    
    run_input = {
        "startUrls": [{"url": url} for url in website_urls],
        "maxCrawlPages": 1,
        "maxCrawlDepth": 0,  # Only crawl the exact URLs provided
        "crawlerType": "playwright:chrome",  # Use Playwright with Chrome for best rendering
        "proxyConfiguration": {
            "useApifyProxy": True
        },
        # Content settings
        "saveMarkdown": True,
        "saveHtml": False,
        "saveScreenshots": True,
        "saveFiles": False,
        # Rendering settings - extended for lazy loading
        "removeCookieWarnings": True,
        "clickElementsCssSelector": "",  # Don't click anything
        # KEY SETTINGS FOR LAZY LOADING:
        "waitUntil": "networkidle",  # Wait for network to be idle
        "initialConcurrency": 1,  # One at a time for reliability
        "maxConcurrency": 1,
        # Extended timing for lazy-loaded content
        "requestTimeoutSecs": 120,
        "navigationTimeoutSecs": 60,
        # Use larger viewport
        "viewportWidth": 1920,
        "viewportHeight": 1080,
    }
    
    run = apify.actor(ACTORS["website"]).call(run_input=run_input, timeout_secs=300)
    
    print(f"[Website Scan] Apify run started with ID: {run['id']}")
    
    supabase.table("scan_jobs").update({
        "apify_run_id": run["id"],
        "status": "running",
        "started_at": "now()"
    }).eq("id", str(scan_job_id)).execute()
    
    return run["id"]


async def get_run_status(run_id: str) -> Dict[str, Any]:
    """Get the status of an Apify run."""
    run = apify.run(run_id).get()
    return {
        "id": run["id"],
        "status": run["status"],
        "started_at": run.get("startedAt"),
        "finished_at": run.get("finishedAt"),
        "stats": run.get("stats", {})
    }


async def get_run_results(run_id: str) -> List[Dict[str, Any]]:
    """Get the results from a completed Apify run."""
    # Get the run info to find the default dataset ID
    run_info = apify.run(run_id).get()
    dataset_id = run_info.get("defaultDatasetId")
    
    if not dataset_id:
        raise ValueError(f"No dataset found for run {run_id}")
    
    items = []
    for item in apify.dataset(dataset_id).iterate_items():
        items.append(item)
    return items


async def process_google_ads_results(
    run_id: str,
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID]
) -> int:
    """
    Process results from Google Ads scrape.
    
    Args:
        run_id: Apify run ID
        scan_job_id: Scan job ID
        distributor_mapping: Map of advertiser ID to distributor ID
        
    Returns:
        Number of images discovered
    """
    results = await get_run_results(run_id)
    discovered_count = 0
    
    print(f"[Google Ads] Processing {len(results)} ad results")
    
    for item in results:
        advertiser_id = item.get("advertiserId", "")
        advertiser_name = item.get("advertiserName", "")
        
        # Try to match by advertiser ID first (lowercase to match mapping keys), then by name
        distributor_id = (
            distributor_mapping.get(advertiser_id.lower()) or 
            distributor_mapping.get(advertiser_id) or  # Try original case as fallback
            distributor_mapping.get(advertiser_name.lower())
        )
        
        if not distributor_id:
            print(f"[Google Ads] WARNING: No distributor found for advertiser_id={advertiser_id}, name={advertiser_name}")
        
        # Collect all image URLs from the ad
        images = set()  # Use set to avoid duplicates
        
        # 1. Top-level previewUrl
        if item.get("previewUrl"):
            images.add(item["previewUrl"])
        
        # 2. Images from variants
        for variant in item.get("variants", []):
            for img_url in variant.get("images", []):
                images.add(img_url)
        
        print(f"[Google Ads] {advertiser_name}: Found {len(images)} images (format: {item.get('format')})")
        
        for img_url in images:
            supabase.table("discovered_images").insert({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": item.get("url", ""),
                "image_url": img_url,
                "source_type": "ad",
                "channel": "google_ads",
                "metadata": {
                    "advertiser_id": advertiser_id,
                    "advertiser_name": advertiser_name,
                    "creative_id": item.get("creativeId"),
                    "ad_format": item.get("format"),
                    "first_shown": item.get("firstShownAt"),
                    "last_shown": item.get("lastShownAt"),
                    "impressions": item.get("impressions"),
                    "countries": item.get("shownCountries", [])
                }
            }).execute()
            discovered_count += 1
    
    # Update scan job - set to "analyzing" so it gets marked "completed" after analysis
    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": discovered_count
    }).eq("id", str(scan_job_id)).execute()
    
    print(f"[Google Ads] Total images discovered: {discovered_count}")
    
    return discovered_count


async def process_facebook_results(
    run_id: str,
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID]
) -> int:
    """Process results from Facebook/Instagram scrape."""
    results = await get_run_results(run_id)
    discovered_count = 0
    
    for item in results:
        page_name = item.get("pageName", "").lower()
        distributor_id = None
        
        # Try to match to a distributor
        for name, dist_id in distributor_mapping.items():
            if name.lower() in page_name:
                distributor_id = dist_id
                break
        
        # Extract images
        images = item.get("images", []) or []
        if item.get("imageUrl"):
            images.append(item["imageUrl"])
        
        for img_url in images:
            supabase.table("discovered_images").insert({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": item.get("url", ""),
                "image_url": img_url,
                "source_type": "ad" if item.get("isSponsored") else "organic_post",
                "channel": "facebook",
                "metadata": {
                    "page_name": page_name,
                    "post_date": item.get("date"),
                    "likes": item.get("likes"),
                    "comments": item.get("comments")
                }
            }).execute()
            discovered_count += 1
    
    # Update scan job - set to "analyzing" so it gets marked "completed" after analysis
    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": discovered_count
    }).eq("id", str(scan_job_id)).execute()
    
    return discovered_count


async def upload_base64_screenshot(base64_data: str, scan_job_id: UUID, page_url: str) -> Optional[str]:
    """
    Upload a base64 screenshot to Supabase storage and return the public URL.
    """
    import base64
    import hashlib
    import time
    
    try:
        # Decode base64 to bytes
        image_bytes = base64.b64decode(base64_data)
        
        # Generate a unique filename based on URL and timestamp
        url_hash = hashlib.md5(page_url.encode()).hexdigest()[:8]
        timestamp = int(time.time() * 1000)
        filename = f"screenshots/{scan_job_id}/{url_hash}-{timestamp}.png"
        
        # Upload to Supabase storage
        result = supabase.storage.from_("scan-screenshots").upload(
            filename,
            image_bytes,
            {"content-type": "image/png"}
        )
        
        # Get public URL
        public_url = supabase.storage.from_("scan-screenshots").get_public_url(filename)
        print(f"[Website Scan] Uploaded screenshot: {public_url}")
        return public_url
        
    except Exception as e:
        print(f"[Website Scan] Failed to upload screenshot: {e}")
        import traceback
        traceback.print_exc()
        return None


async def process_website_results(
    run_id: str,
    scan_job_id: UUID,
    distributor_mapping: Dict[str, UUID]
) -> int:
    """
    Process results from website crawl.
    
    The website-content-crawler returns:
    - url: the crawled page URL
    - title: page title
    - markdown: page content as markdown
    - text: plain text content
    - screenshotUrl: screenshot of the page
    
    We extract images from:
    1. The screenshotUrl (full page screenshot showing assets)
    2. Image URLs embedded in the markdown content
    """
    import re
    
    results = await get_run_results(run_id)
    discovered_count = 0
    
    print(f"[Website Scan] Processing {len(results)} crawled pages for scan job {scan_job_id}")
    
    for item in results:
        page_url = item.get("url", "") or item.get("loadedUrl", "")
        page_title = item.get("title", "")
        markdown_content = item.get("markdown", "") or item.get("text", "")
        screenshot_url = item.get("screenshotUrl")
        screenshot_base64 = item.get("screenshotBase64")
        
        # Log image stats if available
        image_stats = item.get("imageStats", {})
        if image_stats:
            print(f"[Website Scan] - Image stats: {image_stats.get('loaded', 0)}/{image_stats.get('total', 0)} loaded")
        
        # If we have base64 screenshot, upload it and get URL
        if screenshot_base64 and not screenshot_url:
            print(f"[Website Scan] Uploading base64 screenshot ({len(screenshot_base64) // 1024} KB)...")
            screenshot_url = await upload_base64_screenshot(screenshot_base64, scan_job_id, page_url)
        
        print(f"[Website Scan] Processing page: {page_url}")
        print(f"[Website Scan] - Title: {page_title}")
        print(f"[Website Scan] - Screenshot URL: {screenshot_url}")
        print(f"[Website Scan] - Markdown length: {len(markdown_content)} chars")
        
        # Match to distributor by domain
        distributor_id = None
        for domain, dist_id in distributor_mapping.items():
            if domain in page_url:
                distributor_id = dist_id
                break
        
        collected_images = []
        screenshot_validation = None
        
        # 1. Use screenshot URL as primary image (shows actual rendered page with assets)
        if screenshot_url:
            # Validate screenshot to detect lazy/incomplete renders
            screenshot_validation = await validate_screenshot_quality(screenshot_url)
            
            if screenshot_validation["is_valid"]:
                collected_images.append({
                    "url": screenshot_url,
                    "type": "page_screenshot",
                    "alt": f"Screenshot of {page_title or page_url}",
                    "validation": screenshot_validation
                })
                print(f"[Website Scan] - Added screenshot (confidence: {screenshot_validation['confidence']}%)")
            else:
                # Log warning but still include the screenshot with low confidence flag
                print(f"[Website Scan] ⚠️ Screenshot may be incomplete: {screenshot_validation['issues']}")
                collected_images.append({
                    "url": screenshot_url,
                    "type": "page_screenshot",
                    "alt": f"Screenshot of {page_title or page_url}",
                    "validation": screenshot_validation,
                    "potentially_incomplete": True
                })
                print(f"[Website Scan] - Added screenshot with warning (confidence: {screenshot_validation['confidence']}%)")
        
        # 2. Extract image URLs from markdown content
        # Markdown image syntax: ![alt](url) or ![alt](url "title")
        markdown_images = re.findall(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)', markdown_content)
        for alt, img_url in markdown_images:
            # Skip data URIs and tiny icons
            if img_url.startswith('data:'):
                continue
            # Make relative URLs absolute
            if img_url.startswith('/'):
                # Extract base URL from page_url
                from urllib.parse import urlparse
                parsed = urlparse(page_url)
                img_url = f"{parsed.scheme}://{parsed.netloc}{img_url}"
            elif not img_url.startswith('http'):
                continue  # Skip invalid URLs
            
            collected_images.append({
                "url": img_url,
                "type": "embedded_image",
                "alt": alt
            })
        
        # 3. Also look for raw image URLs in the content (sometimes not in markdown format)
        raw_image_urls = re.findall(r'(https?://[^\s<>"\']+\.(?:jpg|jpeg|png|gif|webp|svg))', markdown_content, re.IGNORECASE)
        for img_url in raw_image_urls:
            if not any(i["url"] == img_url for i in collected_images):
                collected_images.append({
                    "url": img_url,
                    "type": "raw_url",
                    "alt": ""
                })
        
        print(f"[Website Scan] - Found {len(collected_images)} total images on page")
        
        # Insert all discovered images
        for img_data in collected_images:
            img_url = img_data["url"]
            if not img_url:
                continue
            
            # Build metadata including validation info for screenshots
            metadata = {
                "page_title": page_title,
                "screenshot_url": screenshot_url,
                "image_type": img_data["type"],
                "alt_text": img_data.get("alt", ""),
                "markdown_length": len(markdown_content)
            }
            
            # Add validation data for screenshots
            if img_data.get("validation"):
                metadata["screenshot_validation"] = {
                    "confidence": img_data["validation"]["confidence"],
                    "issues": img_data["validation"].get("issues", []),
                    "file_size": img_data["validation"].get("file_size")
                }
            if img_data.get("potentially_incomplete"):
                metadata["potentially_incomplete"] = True
                
            supabase.table("discovered_images").insert({
                "scan_job_id": str(scan_job_id),
                "distributor_id": str(distributor_id) if distributor_id else None,
                "source_url": page_url,
                "image_url": img_url,
                "source_type": "website_banner" if img_data["type"] != "page_screenshot" else "page_screenshot",
                "channel": "website",
                "metadata": metadata
            }).execute()
            discovered_count += 1
            print(f"[Website Scan] - Saved discovered image: {img_url[:100]}...")
    
    # Note: We set status to "analyzing" here, not "completed"
    # The scan is only "completed" after auto_analyze_scan finishes in run_website_scan
    supabase.table("scan_jobs").update({
        "status": "analyzing",
        "total_items": discovered_count
    }).eq("id", str(scan_job_id)).execute()
    
    print(f"[Website Scan] Discovered {discovered_count} images, status set to 'analyzing'")
    
    return discovered_count

