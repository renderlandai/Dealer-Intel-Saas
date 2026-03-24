"""Application configuration."""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import Dict


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
    
    # Error Tracking
    sentry_dsn: str = ""
    
    # Redis / Celery
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis/Valkey URL for Celery broker")
    
    # App
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    enable_dangerous_endpoints: bool = False
    
    # ===========================================
    # AI Analysis Thresholds (Fine-Tuning) - STRICT MODE
    # ===========================================
    
    # Match type thresholds (0-100 scale) - RAISED for accuracy
    exact_match_threshold: int = Field(default=90, description="Score for exact match classification")
    strong_match_threshold: int = Field(default=75, description="Score for strong match classification")
    partial_match_threshold: int = Field(default=55, description="Score for partial match classification")
    weak_match_threshold: int = Field(default=40, description="Score for weak match classification")
    
    # Minimum thresholds to create a match - ONLY Partial+ matches shown
    regular_image_match_threshold: int = Field(default=55, description="Min score for regular images")
    screenshot_match_threshold: int = Field(default=55, description="Min score for screenshots")
    
    # Filtering thresholds
    filter_relevance_threshold: float = Field(default=0.7, description="Min relevance score to pass filter")
    
    # Verification thresholds - wider range for more verification
    borderline_match_lower: int = Field(default=50, description="Lower bound for borderline verification")
    borderline_match_upper: int = Field(default=75, description="Upper bound for borderline verification")
    
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
    hash_prefilter_max_diff: int = Field(default=30, description="Max avg hash diff to pass pre-filter (0-64 scale)")
    
    # Stage 2: CLIP embedding gate — skip images with no semantic similarity to any asset
    clip_similarity_threshold: float = Field(default=0.25, description="Min CLIP cosine similarity to proceed to Claude")
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
    
    # Page Discovery
    enable_page_discovery: bool = Field(default=True, description="Auto-discover subpages on dealer sites")
    max_pages_per_site: int = Field(default=15, description="Max pages to scan per dealer website")
    max_concurrent_pages: int = Field(default=4, description="Max pages to extract in parallel per site")
    
    # ===========================================
    # Reports
    # ===========================================
    
    report_logo_path: str = Field(default="", description="Absolute path to logo image for PDF reports (PNG/JPEG). Leave empty for text-only header.")
    
    # ===========================================
    # Notifications (Resend)
    # ===========================================
    
    resend_api_key: str = Field(default="", description="Resend API key for transactional emails")
    resend_from_email: str = Field(default="Dealer Intel <notifications@resend.dev>", description="From address for notification emails")
    
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










