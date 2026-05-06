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
    
    # Stage 2: CLIP embedding gate — skip images with no semantic similarity to any asset
    clip_similarity_threshold: float = Field(default=0.40, description="Min CLIP cosine similarity to proceed to Claude")
    clip_model_name: str = Field(default="clip-ViT-B-32", description="SentenceTransformers CLIP model")
    
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
    
    # Page Discovery
    enable_page_discovery: bool = Field(default=True, description="Auto-discover subpages on dealer sites")
    max_pages_per_site: int = Field(default=15, description="Max pages to scan per dealer website")
    max_concurrent_pages: int = Field(default=4, description="Max pages to extract in parallel per site (legacy scan_dealer_websites only)")
    # Phase 5-minimal: how many dealers `run_website_scan` processes in
    # parallel. Each dealer owns its own MatchBuffer / ProcessedImageBuffer
    # and a per-dealer pipeline_stats dict; the runner aggregates after the
    # gather. Browser memory is the practical ceiling — Chromium contexts
    # are cheap, but each concurrent dealer also keeps a hash + embedding
    # working set in flight. 4 fits comfortably on a 4 GB worker; bump to
    # 6–8 if you move the worker to professional-l (8 GB).
    max_concurrent_dealers: int = Field(default=4, description="Max dealers processed in parallel inside run_website_scan")
    
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






