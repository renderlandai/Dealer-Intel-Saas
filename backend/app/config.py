"""Application configuration."""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import Any, Dict, List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str = ""
    
    # Anthropic AI (Claude for all image analysis)
    anthropic_api_key: str
    
    # ScreenshotOne (website & ad page capture)
    screenshotone_access_key: str
    screenshotone_secret_key: str = ""
    
    # SerpApi (Google Ads Transparency Center)
    serpapi_api_key: str = ""
    
    # Apify (Meta Ad Library — Facebook & Instagram)
    apify_api_key: str = ""
    # Max seconds we'll poll an Apify run before giving up. Large multi-dealer
    # scans (50+ pages) can legitimately take 15-30 minutes inside Apify, so
    # the default ceiling is generous. The Apify run itself keeps executing
    # regardless — this only bounds how long *our* worker waits.
    apify_max_poll_seconds: int = Field(default=2400, description="Max seconds to poll an Apify run before timing out (default 40 min)")
    apify_poll_interval_seconds: int = Field(default=10, description="Seconds between Apify run status polls")
    # Optional Apify Residential proxy URL passed through to the meta-ad-scraper
    # actor. Without it the actor returns a heavily limited subset of ads (Meta
    # rate-limits unauthenticated Ad Library traffic aggressively). Format:
    #   http://groups-RESIDENTIAL:<APIFY_TOKEN>@proxy.apify.com:8000
    # Leave empty to skip — the scraper falls back to its built-in proxy
    # rotation, which is enough for small-volume scans but not for nightly
    # full-distributor sweeps.
    apify_meta_proxy_url: str = Field(default="", description="Apify residential proxy URL forwarded to whoareyouanas/meta-ad-scraper (recommended)")
    # Max parallel actor runs when fanning out across multiple dealer pages.
    # Each run charges $10/1000 ads — keep this low to bound burst spend.
    apify_meta_max_parallel_runs: int = Field(default=4, description="Max simultaneous Apify Meta actor runs across dealers")
    # Which Apify actor to use for Meta Ad Library scraping. Two known
    # values today (2026-05-07 onward):
    #
    #   * ``whoareyouanas~meta-ad-scraper`` (default — current production)
    #     - $10 / 1,000 ads
    #     - One actor run per dealer (we fan out)
    #     - Requires numeric pageId resolution (slug → ID)
    #     - DOM scroll-and-extract; brittle to Meta UI churn
    #
    #   * ``curious_coder~facebook-ads-library-scraper`` (alternative)
    #     - $0.75 / 1,000 ads (~13× cheaper at the rate card; the actor
    #       README cites a historical ~$0.20/1k average)
    #     - ONE bulk actor run for the whole scan (urls: [{url}, …])
    #     - Accepts page URLs directly — slug resolver is not needed
    #     - 24,730 total users, 100% success rate, GraphQL-based
    #
    # Wire this through env to A/B compare without touching code. The
    # underlying ``scan_meta_ads`` dispatcher in ``apify_meta_service``
    # selects the right code path based on this setting; the public
    # function signature is the same either way.
    apify_meta_actor_id: str = Field(
        default="whoareyouanas~meta-ad-scraper",
        description="Apify actor slug used by scan_meta_ads (whoareyouanas~meta-ad-scraper or curious_coder~facebook-ads-library-scraper)",
    )
    # Optional cap on ads scraped per dealer URL when using the
    # curious_coder actor. Leave at 0 to scrape ALL active ads (the
    # actor's ``limitPerSource`` blank semantics — and the whole reason
    # we'd consider this actor in the first place). Set a positive
    # integer to bound spend during pilot trials.
    apify_meta_curious_coder_limit_per_source: int = Field(
        default=0,
        description="Per-dealer ad cap for curious_coder actor (0 = scrape all available)",
    )
    
    # Stripe (billing)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_professional: str = ""
    stripe_price_business: str = ""
    stripe_price_extra_dealer_starter: str = ""
    stripe_price_extra_dealer_professional: str = ""
    stripe_price_extra_dealer_business: str = ""
    frontend_url: str = "http://localhost:3000"
    
    # Error Tracking
    sentry_dsn: str = ""
    
    # Redis (scheduler lock)
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis/Valkey URL for scheduler lock")
    
    # App
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    enable_dangerous_endpoints: bool = False
    
    # ===========================================
    # AI Analysis Thresholds (Fine-Tuning) - STRICT MODE
    # ===========================================
    
    # Match type thresholds (0-100 scale)
    exact_match_threshold: int = Field(default=90, description="Score for exact match classification")
    strong_match_threshold: int = Field(default=75, description="Score for strong match classification")
    partial_match_threshold: int = Field(default=65, description="Score for partial match classification")
    weak_match_threshold: int = Field(default=50, description="Score for weak match classification")
    
    # Minimum thresholds to create a match — reject ambiguous scores
    regular_image_match_threshold: int = Field(default=60, description="Min score for regular images")
    screenshot_match_threshold: int = Field(default=65, description="Min score for screenshots")
    
    # Filtering thresholds
    filter_relevance_threshold: float = Field(default=0.75, description="Min relevance score to pass filter")
    
    # Verification thresholds — wider range catches more borderline false positives
    borderline_match_lower: int = Field(default=60, description="Lower bound for borderline verification")
    borderline_match_upper: int = Field(default=80, description="Upper bound for borderline verification")
    
    # Confidence calibration factors — neutral until adaptive thresholds have
    # enough feedback data to calibrate automatically.  Previous values
    # (0.75 / 0.9 / etc.) were silently dropping valid matches.
    calibration_page_screenshot: float = Field(default=1.0, description="Neutral until feedback-driven")
    calibration_website_banner: float = Field(default=1.0, description="Neutral until feedback-driven")
    calibration_ad: float = Field(default=1.0, description="Neutral until feedback-driven")
    calibration_organic_post: float = Field(default=1.0, description="Neutral until feedback-driven")
    
    # Channel calibration factors — neutral until feedback-driven
    calibration_google_ads: float = Field(default=1.0, description="Neutral until feedback-driven")
    calibration_facebook: float = Field(default=1.0, description="Neutral until feedback-driven")
    calibration_website: float = Field(default=1.0, description="Neutral until feedback-driven")
    
    # ===========================================
    # AI Retry & Performance Settings
    # ===========================================
    
    max_retries: int = Field(default=5, description="Max API retry attempts")
    initial_backoff: float = Field(default=2.0, description="Initial retry backoff in seconds")
    batch_size: int = Field(default=5, description="Images to process in parallel")
    batch_delay: float = Field(default=0.5, description="Delay between batches in seconds")
    # Per-request hard cap applied to the Anthropic SDK constructor. The SDK's
    # built-in default is 600s, which combined with `max_retries=5` produced
    # the 2026-05-07 evening incident: a single connection that opened but
    # never returned a body burned 50 minutes of wall-clock and starved the
    # heartbeat into auto-failure. 120s × 5 retries gives a worst-case 10 min
    # budget per image, which the page-level `page_hard_timeout_seconds`
    # backstop then bounds further. Lower if Anthropic is healthy and you want
    # faster fail-fast; raise if you legitimately need long-context responses.
    anthropic_request_timeout_seconds: float = Field(default=120.0, description="Per-request timeout passed to anthropic.Anthropic(timeout=...)")
    
    # Image optimization
    max_image_width: int = Field(default=1024, description="Max image width for API")
    max_image_height: int = Field(default=1024, description="Max image height for API")
    max_image_bytes: int = Field(default=1048576, description="Max image size (1MB)")
    screenshot_max_width: int = Field(default=1920, description="Max screenshot width")
    screenshot_max_height: int = Field(default=1080, description="Max screenshot height")
    
    # ===========================================
    # Ensemble Matching Weights - CONSERVATIVE
    # ===========================================
    
    ensemble_visual_weight: float = Field(default=0.5, description="Weight for visual similarity - primary")
    ensemble_detection_weight: float = Field(default=0.35, description="Weight for asset detection")
    ensemble_hash_weight: float = Field(default=0.15, description="Weight for perceptual hash - lower weight")
    ensemble_agreement_bonus: int = Field(default=5, description="Small bonus when methods agree - reduced")
    
    # ===========================================
    # Pre-Filter Pipeline (scale optimization)
    # ===========================================
    
    # Stage 1: Perceptual hash gate — skip images with no hash resemblance to any asset
    hash_prefilter_max_diff: int = Field(default=28, description="Max avg hash diff to pass pre-filter (0-64 scale)")
    # Strict variant for inputs that already passed an upstream asset-likeness
    # selector (currently: CV-localized crops from blocked-page screenshots).
    # Default 16 keeps real renders through (mild compression/resize stays
    # well under 16 bits across the 4-hash mean) while rejecting the dark
    # nav-bar / footer-strip crops that the CV path used to mint at scale.
    hash_prefilter_strict_max_diff: int = Field(default=16, description="Max avg hash diff for CV-localized crops (tighter than the generic gate)")
    
    # Stage 2: CLIP embedding gate — skip images with no semantic similarity to any asset
    clip_similarity_threshold: float = Field(default=0.40, description="Min CLIP cosine similarity to proceed to Claude")
    # Strict variant — see hash_prefilter_strict_max_diff for rationale.
    clip_similarity_strict_threshold: float = Field(default=0.55, description="Min CLIP cosine similarity for CV-localized crops")
    clip_model_name: str = Field(default="clip-ViT-B-32", description="SentenceTransformers CLIP model")

    # Phase-9 follow-up #3 (2026-05-11): full-page-screenshot containment
    # fallback. The per-image matcher walks raw `<img>` elements and the
    # CV-localized crop helper looks for pixel-precise asset rectangles
    # inside the page screenshot. Both miss the case where the asset is
    # itself a screenshot of a hero banner that the page composes from
    # CSS background + an isolated equipment PNG + HTML text — none of
    # those layers individually resembles the asset, but the rendered
    # result clearly does. This fallback fires AFTER per-image matching
    # has produced 0 hits for a page: it sends the (asset, full-page
    # screenshot) pair to Opus 4-6 with a containment prompt and writes
    # a synthetic match if the model says the asset appears anywhere in
    # the screenshot. Cost is one extra Opus call per (asset, page-with-
    # 0-matches) pair; expected to be cheap because most pages with
    # promotional content already match at the per-image stage.
    enable_containment_fallback: bool = Field(default=True, description="Run a full-page screenshot containment check on pages with 0 per-image matches")
    containment_fallback_threshold: int = Field(default=70, description="Min Opus confidence (0-100) to count as a containment match")
    containment_fallback_max_assets: int = Field(default=10, description="Skip the containment fallback when a campaign has more than this many assets (cost guardrail)")
    
    # Filter model — use a fast/cheap model for the relevance yes/no check
    filter_model: str = Field(default="claude-haiku-4-5-20251001", description="Cheap model for image relevance filtering")
    
    # ===========================================
    # Image Extraction (Playwright)
    # ===========================================
    
    min_extracted_image_width: int = Field(default=300, description="Min width to consider an extracted image")
    min_extracted_image_height: int = Field(default=150, description="Min height to consider an extracted image")
    max_images_per_page: int = Field(default=50, description="Max images to extract per page")
    playwright_timeout: int = Field(default=60000, description="Page load timeout in ms")
    playwright_scroll_delay: float = Field(default=0.5, description="Delay between scroll steps in seconds")
    enable_tiling_fallback: bool = Field(default=True, description="Tile screenshots when extraction fails")
    tile_height: int = Field(default=1080, description="Height of each screenshot tile in pixels")
    tile_overlap: int = Field(default=200, description="Overlap between adjacent tiles in pixels")
    # When Playwright is consistently blocked (anti-bot WAF), fall back to
    # ScreenshotOne's hosted renderer so the user at least has visual
    # evidence and the page is counted as "blocked, captured externally"
    # rather than silently lost.
    screenshotone_fallback_enabled: bool = Field(default=True, description="Use ScreenshotOne to capture pages that Playwright cannot load")
    # When True, blocked pages whose evidence screenshot was captured by
    # ScreenshotOne are run through OpenCV template matching and any
    # detected asset region is cropped out, uploaded as a separate
    # discovered_image, and fed back into the matcher. This is the
    # confirmation-bias loop that produced "STRONG MATCH on a navigation
    # bar" failures: CV pre-selects a region that "looks like" the
    # asset, then the matcher receives that region and is asked whether
    # it is the asset it was already pre-selected to look like.
    #
    # Disabled by default after the 2026-05-06 incident. Re-enable only
    # after CV thresholds are validated against held-out fixtures
    # (eval/) and the operator has manually inspected at least 50
    # crop-derived matches without finding a false positive.
    cv_localize_screenshot_crops_enabled: bool = Field(default=False, description="Crop campaign assets out of blocked-page screenshots via CV and re-feed them through the matcher (DANGEROUS — produces confirmation-bias false positives)")
    # 2026-06-05: per-page CV localization (`_localize_and_crop_assets`) runs
    # synchronous OpenCV (multi-scale matchTemplate + ORB) for every campaign
    # asset against the page's full-page screenshot. On tall rental/catalog
    # pages the screenshot is enormous (e.g. 1920x20000) and matchTemplate cost
    # scales with screenshot AREA × asset-scale-steps, so a single page could
    # burn minutes of CPU. Worse, the call was made inline on the event loop,
    # so it (a) overran the per-page extract sub-cap (the cancel can't preempt a
    # blocking C call — pages ran ~186s under a 120s cap) and (b) froze every
    # other concurrent dealer. These two knobs bound the worst case; the call is
    # now also offloaded to a worker thread so the cap can actually cancel it.
    cv_localize_max_assets_per_page: int = Field(default=12, description="Cap on how many campaign assets are CV-matched against a single page screenshot (cost guardrail)")
    cv_localize_max_screenshot_dim: int = Field(default=4000, description="Downscale the page screenshot so its longest side is at most this many px before OpenCV matching; bbox coords are scaled back to full-page space (0 disables the cap)")
    
    # Page Discovery
    enable_page_discovery: bool = Field(default=True, description="Auto-discover subpages on dealer sites")
    # 2026-06-05: dropped 15 → 8. Campaign creative lives on the homepage
    # and a handful of promo/landing pages (/specials, /deals, /offers,
    # /promotions); it does NOT live on deep catalog / fleet / inventory
    # listing pages. Since `discover_pages` fills promo paths FIRST and
    # truncates to this cap, a smaller budget biases the scan toward the
    # ad-bearing pages and drops the heavy catalog tail — which also slashes
    # the per-scan CPU load on the 2-vCPU worker (those catalog pages were
    # the ones blowing past `page_extract_timeout_seconds`).
    max_pages_per_site: int = Field(default=8, description="Max pages to scan per dealer website")
    # Phase-9 follow-up (2026-05-11): the previous design ran
    # `discover_pages` for every dealer SERIALLY in a single loop with
    # no heartbeat inside it. A single hung dealer (e.g. generaldeequipos.com
    # on 2026-05-11 11:42 EDT — homepage HTML never finished loading via
    # httpx) wedged the whole 45-dealer fan-out before a single extraction
    # ever started, and 20 min later the cleanup job auto-failed the scan.
    # These two knobs bound that risk:
    #   * `page_discovery_concurrency` parallelises discovery (HTTP-bound,
    #     independent per-dealer, perfect candidate for `asyncio.gather`).
    #   * `page_discovery_per_dealer_timeout_seconds` caps a single bad
    #     dealer's discovery so it can never block the rest. On timeout
    #     we fall back to scanning just the dealer's homepage.
    page_discovery_concurrency: int = Field(default=8, description="Max dealers having pages discovered in parallel")
    page_discovery_per_dealer_timeout_seconds: int = Field(default=60, description="Cancel one dealer's page discovery after this many seconds (0 = no cap)")
    max_concurrent_pages: int = Field(default=4, description="Max pages to extract in parallel per site (legacy scan_dealer_websites only)")
    # Phase 5-minimal: how many dealers `run_website_scan` processes in
    # parallel. Each dealer owns its own MatchBuffer / ProcessedImageBuffer
    # and a per-dealer pipeline_stats dict; the runner aggregates after the
    # gather.
    #
    # 2026-06-05: dropped 4 → 2. The REAL ceiling is CPU, not RAM. Playwright
    # extraction (render + scroll + full-page screenshot + image decode) is
    # CPU-bound, and the production worker has only 2 dedicated vCPUs. The
    # extract semaphore is sized `max_concurrent_dealers * pages_per_dealer`,
    # so 4×4=16 simultaneous Chromium renders on 2 cores = 8× oversubscription,
    # which stretched ~25s pages past the 120s extract sub-cap and got them
    # discarded with zero images. 2×2=4 keeps it at a sane 2× and lets pages
    # finish under the cap. Bump these back up only on a worker with more
    # dedicated vCPUs (rule of thumb: keep extract_sem ≲ 2 × vCPUs).
    max_concurrent_dealers: int = Field(default=2, description="Max dealers processed in parallel inside run_website_scan")
    # Inner-loop concurrency added in the Phase-7 throughput pass:
    # within each dealer task we now fan pages out instead of walking them
    # serially, and within each page we fan the per-image AI pipeline out
    # instead of awaiting one image at a time. The two semaphores are
    # multiplicative — at default (2 dealers × 2 pages × 5 images) you'll
    # see at most ~20 in-flight image-analysis coroutines per worker, which
    # comfortably stays under Anthropic tier-2 limits (50 concurrent Opus
    # calls + ample Haiku headroom). Drop these if you ever see 429 storms.
    # 2026-06-05: dropped 4 → 2 alongside `max_concurrent_dealers` so the
    # extract semaphore (max_concurrent_dealers × this) stays at 4 on the
    # 2-vCPU worker instead of 16. See the note on `max_concurrent_dealers`.
    pages_per_dealer_concurrency: int = Field(default=2, description="Max pages scanned in parallel within a single dealer")
    images_per_page_concurrency: int = Field(default=5, description="Max images analysed in parallel within a single extracted page")
    # Concurrency for the post-scan analyse pass that Facebook / Google /
    # Instagram / manual analyse paths use. Previously sequential, which
    # meant 500 images @ 1-2s each = 8-16 min minimum AND a single hung
    # Claude call stalled the whole loop and starved the heartbeat. With
    # this fan-out the same scan finishes in ~2 min and one wedged image
    # only blocks one slot.
    post_analysis_concurrency: int = Field(default=5, description="Max images analysed in parallel inside run_image_analysis (FB / Google / IG)")
    # Minimum interval between heartbeat writes. The website runner now
    # stamps a heartbeat from inside the per-image fan-out (Phase 8 fix
    # for the 2026-05-07 evening incident) — without this debounce a
    # 100-image page would fire 100 UPDATEs in tight succession.
    heartbeat_min_interval_seconds: float = Field(default=10.0, description="Throttle inside-loop heartbeat writes to at most one per this many seconds per scan")
    # When True, run_website_scan writes incremental matches_count /
    # processed_items / total_items to scan_jobs as each dealer finishes,
    # instead of only at the end. Lets the operator UI show real progress
    # and ensures partial results survive a watchdog kill.
    enable_progress_streaming: bool = Field(default=True, description="Stream per-dealer counters to scan_jobs while scan is running")
    # Phase-8.2: how often the website runner flushes
    # `pipeline_stats.dealer_outcomes` to scan_jobs while dealers are
    # finishing. Set to 0 to write on every dealer completion; bump
    # higher if a 100-dealer scan is generating too many JSONB rewrites.
    # 3.0 s comfortably keeps the UI badge fresh without thrashing the
    # row.
    dealer_outcome_stream_interval_seconds: float = Field(default=3.0, description="Throttle live writes of pipeline_stats.dealer_outcomes to at most one per this many seconds")
    # Hard wall-clock the dispatch wrapper enforces via asyncio.wait_for.
    # 0 disables the wrapper entirely (idle-detection in the cleanup job
    # becomes the only kill signal — see scheduler_service._cleanup_stale_scans).
    # Default 0: trust the heartbeat-based cleanup, which won't kill an
    # actively-writing scan no matter how long it runs.
    scan_hard_timeout_seconds: int = Field(default=0, description="Hard asyncio wall-clock timeout for one scan (0 = use heartbeat-based cleanup only)")
    # Hard cap on a single page (extract + analyse). Phase-8 backstop: a
    # wedged page now self-cancels at this limit so the dealer's other
    # pages keep running and the heartbeat keeps advancing. 0 disables.
    #
    # Phase-9 (2026-05-11): dropped from 900 → 480 because the previous
    # value was the *only* in-flight guard inside `_process_one_page`,
    # so a 60-image page hitting one slow Anthropic socket could burn
    # the full 15 minutes before yielding the dealer slot. The new
    # sub-caps (`page_extract_timeout_seconds` /
    # `page_analyze_timeout_seconds`) bound each phase independently;
    # this outer cap is a belt-and-suspenders backstop for any code
    # path the sub-caps don't cover.
    page_hard_timeout_seconds: int = Field(default=480, description="Cancel a single page after this many seconds (0 = no cap)")
    # Phase-9 sub-caps. The previous design only wrapped the entire
    # `_process_one_page` in a single 900s `wait_for`, which made it
    # impossible to tell whether Playwright extraction or Anthropic
    # analysis was the slow phase when a page timed out. Splitting the
    # budget gives us:
    #   * fail-fast extraction (most healthy pages finish in <30s; a
    #     stalled Playwright nav has no business burning 15 minutes),
    #   * a separate cap for the per-image AI fan-out so Anthropic
    #     hiccups can't poison the extraction budget,
    #   * structured `outcome` values (`extract_timeout` /
    #     `analyze_timeout`) in `blocked_details` so post-mortems
    #     don't have to read worker logs.
    # 0 disables the corresponding sub-cap (legacy behaviour — falls
    # back to the outer `page_hard_timeout_seconds`).
    # 2026-06-05: raised 120 → 240. Tall rental/catalog pages (the sector the
    # client explicitly wants scanned) legitimately need more than 120s to load,
    # scroll, screenshot, and CV-localize. Combined with the same-day CV fix
    # (OpenCV offloaded off the event loop + screenshot downscaled before
    # matching), 240s gives heavy pages room to finish and return images instead
    # of being abandoned at 0. Stays under `page_hard_timeout_seconds` (480) so
    # the per-dealer budget math is unchanged.
    page_extract_timeout_seconds: int = Field(default=240, description="Cancel a single page's Playwright extraction after this many seconds (0 = no inner cap)")
    page_analyze_timeout_seconds: int = Field(default=300, description="Cancel a single page's per-image AI analysis after this many seconds (0 = no inner cap)")
    # Hard cap on a single dealer (all its pages, plus prep / teardown).
    # The `_process_one_dealer` task is wrapped in `asyncio.wait_for` so a
    # pathological dealer cannot starve the rest of the scan. 0 disables.
    #
    # Phase-9 (2026-05-11): dropped from 2700 → 1500 once the per-page
    # sub-caps lowered the worst-case page time. New math at default
    # settings (`max_pages_per_site=8`, `pages_per_dealer_concurrency=2`,
    # worst-case page = `page_hard_timeout_seconds=480`):
    #     ceil(8/2) * 480s = 4 * 480s = 1920s   (theoretical max)
    # Real dealers don't run worst-case pages back to back — typical
    # mix is 3-4 fast pages per slow one, so 1500s gives the typical
    # dealer huge headroom and kills only the truly pathological one.
    # That is exactly the desired behaviour for 40-dealer batches:
    # one bad dealer can't eat the heartbeat budget and starve the
    # other 39.
    dealer_hard_timeout_seconds: int = Field(default=1500, description="Cancel a single dealer after this many seconds (0 = no cap)")
    # Heartbeat freshness threshold the cleanup job uses to decide a scan
    # is truly stuck. Was hard-coded to 4h; making it configurable so a
    # tenant scanning hundreds of dealers can give scans more leash.
    scan_idle_timeout_minutes: int = Field(default=20, description="Mark a running scan failed if its heartbeat is older than this many minutes")
    
    # ===========================================
    # Reports
    # ===========================================
    
    report_logo_path: str = Field(default="", description="Absolute path to logo image for PDF reports (PNG/JPEG). Leave empty for text-only header.")
    
    # ===========================================
    # Notifications (Resend)
    # ===========================================
    
    resend_api_key: str = Field(default="", description="Resend API key for transactional emails")
    resend_from_email: str = Field(default="Dealer Intel <notifications@resend.dev>", description="From address for notification emails")
    
    # ===========================================
    # Slack Integration (OAuth)
    # ===========================================
    
    slack_client_id: str = Field(default="", description="Slack App OAuth Client ID")
    slack_client_secret: str = Field(default="", description="Slack App OAuth Client Secret")
    slack_signing_secret: str = Field(default="", description="Slack App Signing Secret")
    
    # ===========================================
    # Salesforce Integration (OAuth)
    # ===========================================
    
    salesforce_client_id: str = Field(default="", description="Salesforce Connected App Consumer Key")
    salesforce_client_secret: str = Field(default="", description="Salesforce Connected App Consumer Secret")
    
    # ===========================================
    # Dropbox Integration (OAuth)
    # ===========================================
    
    dropbox_client_id: str = Field(default="", description="Dropbox App Key")
    dropbox_client_secret: str = Field(default="", description="Dropbox App Secret")
    
    # ===========================================
    # Jira Integration (OAuth 2.0 3LO)
    # ===========================================
    
    jira_client_id: str = Field(default="", description="Atlassian OAuth Client ID")
    jira_client_secret: str = Field(default="", description="Atlassian OAuth Client Secret")
    
    # ===========================================
    # HubSpot Integration (OAuth 2.0)
    # ===========================================
    
    hubspot_client_id: str = Field(default="", description="HubSpot App Client ID")
    hubspot_client_secret: str = Field(default="", description="HubSpot App Client Secret")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore extra environment variables


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def get_calibration_factor(source_type: str, channel: str, settings: Settings = None) -> float:
    """
    Get combined calibration factor for a source type and channel.
    Used to adjust confidence scores based on historical accuracy patterns.
    """
    if settings is None:
        settings = get_settings()
    
    # Source type calibration
    source_factors = {
        "page_screenshot": settings.calibration_page_screenshot,
        "website_banner": settings.calibration_website_banner,
        "ad": settings.calibration_ad,
        "organic_post": settings.calibration_organic_post,
    }
    source_factor = source_factors.get(source_type, 1.0)
    
    # Channel calibration
    channel_factors = {
        "google_ads": settings.calibration_google_ads,
        "facebook": settings.calibration_facebook,
        "instagram": settings.calibration_facebook,  # Same as Facebook
        "website": settings.calibration_website,
    }
    channel_factor = channel_factors.get(channel, 1.0)
    
    return source_factor * channel_factor


# ===========================================
# Plan Limits — enforced by billing middleware
# ===========================================

PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    "free": {
        "max_dealers": 2,
        "max_campaigns": 1,
        "max_scans_total": 5,
        "max_scans_per_month": None,
        "max_concurrent_scans": 1,
        "max_pages_per_site": 8,
        "max_compliance_rules": 0,
        "max_user_seats": 1,
        "max_pdf_reports": 1,
        "allowed_channels": ["website"],
        "allowed_frequencies": [],
        "max_schedules_per_campaign": 0,
        "pdf_reports": True,
        "report_branding": False,
        "email_notifications": False,
        "slack_notifications": False,
        "salesforce_notifications": False,
        "jira_notifications": False,
        "hubspot_notifications": False,
        "compliance_trends": False,
        "adaptive_calibration_active": False,
        "api_access": False,
        "data_retention_days": 21,
        "trial_duration_days": 14,
        "included_dealers": 2,
        "extra_dealer_price": 0,
    },
    "starter": {
        "max_dealers": 10,
        "max_campaigns": 3,
        "max_scans_total": None,
        "max_scans_per_month": 15,
        "max_concurrent_scans": 1,
        "max_pages_per_site": 8,
        "max_compliance_rules": 0,
        "max_user_seats": 1,
        "max_pdf_reports": None,
        "allowed_channels": ["website"],
        "allowed_frequencies": ["biweekly", "monthly"],
        "max_schedules_per_campaign": 1,
        "pdf_reports": False,
        "report_branding": False,
        "email_notifications": False,
        "slack_notifications": False,
        "salesforce_notifications": False,
        "jira_notifications": False,
        "hubspot_notifications": False,
        "compliance_trends": False,
        "adaptive_calibration_active": False,
        "api_access": False,
        "data_retention_days": 90,
        "trial_duration_days": None,
        "included_dealers": 10,
        "extra_dealer_price": 99,
    },
    "professional": {
        "max_dealers": 40,
        "max_campaigns": 10,
        "max_scans_total": None,
        "max_scans_per_month": 40,
        "max_concurrent_scans": 2,
        "max_pages_per_site": 15,
        "max_compliance_rules": 10,
        "max_user_seats": 3,
        "max_pdf_reports": None,
        "allowed_channels": ["website", "google_ads", "facebook", "instagram"],
        "allowed_frequencies": ["weekly", "biweekly", "monthly"],
        "max_schedules_per_campaign": 1,
        "pdf_reports": True,
        "report_branding": True,
        "email_notifications": True,
        "slack_notifications": False,
        "salesforce_notifications": False,
        "jira_notifications": False,
        "hubspot_notifications": False,
        "compliance_trends": False,
        "adaptive_calibration_active": True,
        "api_access": False,
        "data_retention_days": 180,
        "trial_duration_days": None,
        "included_dealers": 40,
        "extra_dealer_price": 90,
    },
    "business": {
        "max_dealers": 100,
        "max_campaigns": None,
        "max_scans_total": None,
        "max_scans_per_month": 150,
        "max_concurrent_scans": 5,
        "max_pages_per_site": 20,
        "max_compliance_rules": None,
        "max_user_seats": 10,
        "max_pdf_reports": None,
        "allowed_channels": ["website", "google_ads", "facebook", "instagram"],
        "allowed_frequencies": ["daily", "weekly", "biweekly", "monthly"],
        "max_schedules_per_campaign": None,
        "pdf_reports": True,
        "report_branding": True,
        "email_notifications": True,
        "slack_notifications": False,
        "salesforce_notifications": False,
        "jira_notifications": False,
        "hubspot_notifications": False,
        "compliance_trends": True,
        "adaptive_calibration_active": True,
        "api_access": False,
        "data_retention_days": 365,
        "trial_duration_days": None,
        "included_dealers": 100,
        "extra_dealer_price": 70,
    },
    "enterprise": {
        "max_dealers": None,
        "max_campaigns": None,
        "max_scans_total": None,
        "max_scans_per_month": None,
        "max_concurrent_scans": 10,
        "max_pages_per_site": 50,
        "max_compliance_rules": None,
        "max_user_seats": None,
        "max_pdf_reports": None,
        "allowed_channels": ["website", "google_ads", "facebook", "instagram"],
        "allowed_frequencies": ["daily", "weekly", "biweekly", "monthly"],
        "max_schedules_per_campaign": None,
        "pdf_reports": True,
        "report_branding": True,
        "email_notifications": True,
        "slack_notifications": True,
        "salesforce_notifications": True,
        "jira_notifications": True,
        "hubspot_notifications": True,
        "compliance_trends": True,
        "adaptive_calibration_active": True,
        "api_access": True,
        "data_retention_days": 730,
        "trial_duration_days": None,
        "included_dealers": None,
        "extra_dealer_price": 49,
    },
}


def get_plan_limits(plan: str) -> Dict[str, Any]:
    """Return the limits dict for a plan, defaulting to 'free'."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def get_stripe_price_id(plan: str, settings: Optional["Settings"] = None) -> Optional[str]:
    """Map a plan name to its Stripe Price ID."""
    if settings is None:
        settings = get_settings()
    return {
        "starter": settings.stripe_price_starter,
        "professional": settings.stripe_price_professional,
        "business": settings.stripe_price_business,
    }.get(plan)


def get_extra_dealer_price_id(plan: str, settings: Optional["Settings"] = None) -> Optional[str]:
    """Map a plan name to its extra-dealer Stripe Price ID."""
    if settings is None:
        settings = get_settings()
    return {
        "starter": settings.stripe_price_extra_dealer_starter,
        "professional": settings.stripe_price_extra_dealer_professional,
        "business": settings.stripe_price_extra_dealer_business,
    }.get(plan)






