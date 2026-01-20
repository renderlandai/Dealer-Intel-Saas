"""Pydantic models for API requests and responses."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from uuid import UUID
from enum import Enum


# ============================================
# ENUMS
# ============================================

class CampaignStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class DistributorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MatchType(str, Enum):
    EXACT = "exact"
    STRONG = "strong"
    PARTIAL = "partial"
    WEAK = "weak"


class ComplianceStatus(str, Enum):
    PENDING = "pending"
    COMPLIANT = "compliant"
    VIOLATION = "violation"
    REVIEW = "review"


class ScanSource(str, Enum):
    GOOGLE_ADS = "google_ads"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    WEBSITE = "website"


class ScanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================
# ORGANIZATION
# ============================================

class OrganizationBase(BaseModel):
    name: str
    slug: str


class OrganizationCreate(OrganizationBase):
    pass


class Organization(OrganizationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# CAMPAIGN
# ============================================

class CampaignBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: CampaignStatus = CampaignStatus.ACTIVE
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class CampaignCreate(CampaignBase):
    organization_id: UUID


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[CampaignStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class Campaign(CampaignBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
    asset_count: Optional[int] = 0

    class Config:
        from_attributes = True


# ============================================
# ASSET
# ============================================

class AssetBase(BaseModel):
    name: str
    file_url: str
    file_type: Optional[str] = None
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AssetCreate(AssetBase):
    campaign_id: UUID


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Asset(AssetBase):
    id: UUID
    campaign_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================
# DISTRIBUTOR
# ============================================

class DistributorBase(BaseModel):
    name: str
    code: Optional[str] = None
    website_url: Optional[str] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    google_ads_advertiser_id: Optional[str] = None
    region: Optional[str] = None
    status: DistributorStatus = DistributorStatus.ACTIVE
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DistributorCreate(DistributorBase):
    organization_id: UUID


class DistributorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    website_url: Optional[str] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    google_ads_advertiser_id: Optional[str] = None
    region: Optional[str] = None
    status: Optional[DistributorStatus] = None
    metadata: Optional[Dict[str, Any]] = None


class Distributor(DistributorBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
    match_count: Optional[int] = 0
    has_violation: Optional[bool] = False
    violation_count: Optional[int] = 0

    class Config:
        from_attributes = True


# ============================================
# SCAN JOB
# ============================================

class ScanJobCreate(BaseModel):
    organization_id: UUID
    campaign_id: Optional[UUID] = None
    source: ScanSource
    distributor_ids: Optional[List[UUID]] = None


class ScanJob(BaseModel):
    id: UUID
    organization_id: UUID
    campaign_id: Optional[UUID]
    status: ScanStatus
    source: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_items: int
    processed_items: int
    matches_count: int = 0  # Actual matches found against campaign assets
    error_message: Optional[str]
    apify_run_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================
# MATCH
# ============================================

class MatchBase(BaseModel):
    asset_id: UUID
    discovered_image_id: UUID
    distributor_id: Optional[UUID] = None
    confidence_score: float
    match_type: MatchType
    is_modified: bool = False
    modifications: List[str] = Field(default_factory=list)
    channel: Optional[str] = None
    source_url: Optional[str] = None
    screenshot_url: Optional[str] = None
    compliance_status: ComplianceStatus = ComplianceStatus.PENDING
    compliance_issues: List[Dict[str, Any]] = Field(default_factory=list)
    ai_analysis: Dict[str, Any] = Field(default_factory=dict)


class Match(MatchBase):
    id: UUID
    discovered_at: Optional[datetime]
    created_at: datetime
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[UUID]
    
    # Joined fields
    asset_name: Optional[str] = None
    asset_url: Optional[str] = None
    distributor_name: Optional[str] = None
    campaign_name: Optional[str] = None

    class Config:
        from_attributes = True


class MatchUpdate(BaseModel):
    compliance_status: Optional[ComplianceStatus] = None
    compliance_issues: Optional[List[Dict[str, Any]]] = None


# ============================================
# DASHBOARD STATS
# ============================================

class DashboardStats(BaseModel):
    active_campaigns: int = 0
    total_assets: int = 0
    active_distributors: int = 0
    total_matches: int = 0
    unread_alerts: int = 0
    compliance_rate: float = 0.0
    matches_today: int = 0
    violations_count: int = 0


# ============================================
# AI ANALYSIS
# ============================================

class ImageFilterResult(BaseModel):
    is_relevant: bool
    confidence: float
    reason: str


class ComplianceCheckResult(BaseModel):
    is_compliant: bool
    issues: List[Dict[str, Any]]
    brand_elements: Dict[str, bool]
    zombie_ad: bool = False
    zombie_days: Optional[int] = None
    analysis_summary: str


class ImageMatchResult(BaseModel):
    matched: bool
    asset_id: Optional[UUID] = None
    confidence_score: float
    match_type: MatchType
    modifications: List[str]


# ============================================
# MATCH FEEDBACK (for continuous learning)
# ============================================

class FeedbackVerdict(str, Enum):
    TRUE_POSITIVE = "true_positive"      # Correctly identified as match
    FALSE_POSITIVE = "false_positive"    # Incorrectly identified as match
    TRUE_NEGATIVE = "true_negative"      # Correctly identified as non-match
    FALSE_NEGATIVE = "false_negative"    # Missed a real match


class FeedbackStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    DISPUTED = "disputed"


class MatchFeedbackCreate(BaseModel):
    match_id: UUID
    was_correct: bool
    actual_verdict: FeedbackVerdict
    review_notes: Optional[str] = None


class MatchFeedback(BaseModel):
    id: UUID
    match_id: UUID
    was_correct: bool
    actual_verdict: FeedbackVerdict
    ai_confidence: Optional[float] = None
    source_type: Optional[str] = None
    channel: Optional[str] = None
    match_type: Optional[str] = None
    reviewed_by: Optional[UUID] = None
    review_notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackAccuracyStats(BaseModel):
    source_type: Optional[str] = None
    channel: Optional[str] = None
    match_type: Optional[str] = None
    total_reviews: int = 0
    correct_count: int = 0
    incorrect_count: int = 0
    accuracy_percentage: float = 0.0
    avg_confidence: Optional[float] = None
    avg_confidence_correct: Optional[float] = None
    avg_confidence_incorrect: Optional[float] = None


class ThresholdRecommendation(BaseModel):
    source_type: str
    channel: str
    current_threshold: int
    recommended_threshold: int
    sample_count: int
    false_positive_rate: float
    false_negative_rate: float
    confidence: str  # "high", "medium", "low" based on sample count


# ============================================
# ANALYSIS SETTINGS (for fine-tuning)
# ============================================

class AnalysisSettingsResponse(BaseModel):
    """Current analysis threshold settings."""
    exact_match_threshold: int
    strong_match_threshold: int
    partial_match_threshold: int
    weak_match_threshold: int
    regular_image_match_threshold: int
    screenshot_match_threshold: int
    filter_relevance_threshold: float
    borderline_match_lower: int
    borderline_match_upper: int
    calibration_factors: Dict[str, float]
    ensemble_weights: Dict[str, float]









