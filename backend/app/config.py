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
    
    # Anthropic AI (Claude Sonnet for all image analysis)
    anthropic_api_key: str
    
    # Apify
    apify_api_token: str
    
    # App
    debug: bool = True
    api_prefix: str = "/api/v1"
    
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
    
    # Confidence calibration factors - MORE CONSERVATIVE (reduce scores)
    calibration_page_screenshot: float = Field(default=0.75, description="Screenshots over-match, reduce more")
    calibration_website_banner: float = Field(default=0.9, description="Banners slightly reduced")
    calibration_ad: float = Field(default=0.95, description="Ads slightly reduced")
    calibration_organic_post: float = Field(default=0.8, description="Organic posts have noise")
    
    # Channel calibration factors - MORE CONSERVATIVE
    calibration_google_ads: float = Field(default=1.0, description="Google Ads baseline")
    calibration_facebook: float = Field(default=0.85, description="Facebook has more noise")
    calibration_website: float = Field(default=0.9, description="Website slightly reduced")
    
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










