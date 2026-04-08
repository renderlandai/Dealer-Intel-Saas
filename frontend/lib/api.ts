import axios from "axios";
import { supabase } from "./supabase";
import { upgradeEvents } from "./upgrade-events";

// ── Types ──────────────────────────────────────────────────────

export type CampaignStatus = "active" | "paused" | "completed";
export type DistributorStatus = "active" | "inactive";
export type MatchType = "exact" | "strong" | "partial" | "weak";
export type ComplianceStatus = "pending" | "compliant" | "violation" | "review";
export type ScanSource = "google_ads" | "facebook" | "instagram" | "youtube" | "website";
export type ScanStatus = "pending" | "running" | "analyzing" | "completed" | "failed";
export type FeedbackVerdict = "true_positive" | "false_positive" | "true_negative" | "false_negative";

export interface Campaign {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  status: CampaignStatus;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  updated_at: string;
  asset_count: number;
}

export interface CampaignCreate {
  name: string;
  description?: string;
  status?: CampaignStatus;
  start_date?: string;
  end_date?: string;
  organization_id?: string;
}

export interface Asset {
  id: string;
  campaign_id: string;
  name: string;
  file_url: string;
  file_type: string | null;
  thumbnail_url: string | null;
  width: number | null;
  height: number | null;
  file_size: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Distributor {
  id: string;
  organization_id: string;
  name: string;
  code: string | null;
  website_url: string | null;
  facebook_url: string | null;
  instagram_url: string | null;
  youtube_url: string | null;
  google_ads_advertiser_id: string | null;
  region: string | null;
  status: DistributorStatus;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  match_count: number;
  has_violation: boolean;
  violation_count: number;
}

export interface DistributorCreate {
  name: string;
  code?: string;
  website_url?: string;
  facebook_url?: string;
  instagram_url?: string;
  youtube_url?: string;
  google_ads_advertiser_id?: string;
  region?: string;
  status?: DistributorStatus;
  metadata?: Record<string, unknown>;
  organization_id?: string;
}

export interface DistributorUpdate {
  name?: string;
  code?: string;
  website_url?: string;
  facebook_url?: string;
  instagram_url?: string;
  youtube_url?: string;
  google_ads_advertiser_id?: string;
  region?: string;
  status?: DistributorStatus;
  metadata?: Record<string, unknown>;
}

export interface Match {
  id: string;
  asset_id: string;
  discovered_image_id: string;
  distributor_id: string | null;
  confidence_score: number;
  match_type: MatchType;
  is_modified: boolean;
  modifications: string[];
  channel: string | null;
  source_url: string | null;
  screenshot_url: string | null;
  compliance_status: ComplianceStatus;
  compliance_issues: Record<string, unknown>[];
  ai_analysis: Record<string, unknown>;
  discovered_at: string | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  last_seen_at: string | null;
  scan_count: number;
  previous_compliance_status: string | null;
  asset_name: string | null;
  asset_url: string | null;
  distributor_name: string | null;
  campaign_name: string | null;
}

export interface MatchFilters {
  status?: string;
  type?: string;
  minConfidence?: string;
}

export interface ScanJob {
  id: string;
  organization_id: string;
  campaign_id: string | null;
  status: ScanStatus;
  source: string;
  started_at: string | null;
  completed_at: string | null;
  total_items: number;
  processed_items: number;
  matches_count: number;
  error_message: string | null;
  apify_run_id: string | null;
  pipeline_stats: Record<string, unknown> | null;
  created_at: string;
}

export interface ScanJobCreate {
  source: string;
  distributor_ids?: string[];
}

export interface DashboardStats {
  active_campaigns: number;
  total_assets: number;
  active_distributors: number;
  total_matches: number;
  unread_alerts: number;
  compliance_rate: number;
  matches_today: number;
  violations_count: number;
}

export interface Alert {
  id: string;
  organization_id: string;
  alert_type: string;
  severity: string;
  title: string;
  description: string | null;
  is_read: boolean;
  match_id: string | null;
  distributor_id: string | null;
  created_at: string;
  distributors?: { name: string };
  matches?: { confidence_score: number };
}

export interface FeedbackSubmission {
  was_correct: boolean;
  actual_verdict: FeedbackVerdict;
  review_notes?: string;
}

export interface FeedbackStats {
  source_type: string | null;
  channel: string | null;
  match_type: string | null;
  total_reviews: number;
  correct_count: number;
  incorrect_count: number;
  accuracy_percentage: number;
  avg_confidence: number | null;
  avg_confidence_correct: number | null;
  avg_confidence_incorrect: number | null;
}

export interface ThresholdRecommendation {
  source_type: string;
  channel: string;
  current_threshold: number;
  recommended_threshold: number;
  sample_count: number;
  false_positive_rate: number;
  false_negative_rate: number;
  confidence: string;
}

export interface UsageMeter {
  current: number;
  max: number | null;
  period?: string;
}

export interface BillingUsage {
  plan: string;
  plan_status: string;
  stripe_customer_id: string | null;
  trial_days_left: number | null;
  dealers: UsageMeter;
  campaigns: UsageMeter;
  scans: UsageMeter;
}

export interface OrgSettings {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  logo_url: string | null;
  report_brand_color: string | null;
  notify_email: string | null;
  notify_on_violation: boolean;
}

export interface OrgSettingsUpdate {
  name?: string;
  report_brand_color?: string;
  notify_email?: string;
  notify_on_violation?: boolean;
}

export interface TeamMember {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  joined_at: string;
}

export interface TeamInvite {
  id: string;
  email: string;
  role: string;
  status: string;
  invited_by: string;
  created_at: string;
  expires_at: string | null;
}

export type RuleType = "required_element" | "forbidden_element" | "date_check";
export type RuleSeverity = "info" | "warning" | "critical";

export interface ComplianceRule {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  rule_type: RuleType;
  rule_config: Record<string, unknown>;
  severity: RuleSeverity;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface ComplianceRuleCreate {
  name: string;
  description?: string;
  rule_type: RuleType;
  rule_config: Record<string, unknown>;
  severity?: RuleSeverity;
}

export interface ComplianceRuleUpdate {
  name?: string;
  description?: string;
  rule_type?: RuleType;
  rule_config?: Record<string, unknown>;
  severity?: RuleSeverity;
  is_active?: boolean;
}

export interface ComplianceTrendPoint {
  date: string;
  compliance_rate: number;
  total_matches: number;
  violations: number;
}

export interface ChannelCoverage {
  channel: string;
  match_count: number;
  compliance_rate: number;
}

export interface DistributorCoverage {
  distributor_id: string;
  distributor_name: string;
  match_count: number;
  compliance_rate: number;
}

export interface MatchStats {
  total: number;
  by_status: Record<ComplianceStatus, number>;
  by_type: Record<MatchType, number>;
  avg_confidence: number;
}

// ── Axios Instance ─────────────────────────────────────────────

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 15000,
});

// Cache the Supabase session to avoid redundant getSession() calls on parallel requests
let _sessionPromise: Promise<string | null> | null = null;
const SESSION_TTL = 30_000;
let _sessionCachedAt = 0;

async function getAccessToken(): Promise<string | null> {
  const now = Date.now();
  if (!_sessionPromise || now - _sessionCachedAt > SESSION_TTL) {
    _sessionCachedAt = now;
    _sessionPromise = supabase.auth
      .getSession()
      .then(({ data: { session } }) => session?.access_token ?? null)
      .catch(() => {
        _sessionPromise = null;
        return null;
      });
  }
  return _sessionPromise;
}

api.interceptors.request.use(async (config) => {
  const token = await getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Retry once on 401 after refreshing the Supabase session
let _isRefreshing = false;
let _refreshSubscribers: ((token: string | null) => void)[] = [];

function _onTokenRefreshed(token: string | null) {
  _refreshSubscribers.forEach((cb) => cb(token));
  _refreshSubscribers = [];
}

api.interceptors.response.use(undefined, async (error) => {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;
  const originalRequest = error.config;

  // 401 — attempt a token refresh and retry the original request once
  if (status === 401 && !originalRequest._retried) {
    originalRequest._retried = true;

    if (_isRefreshing) {
      return new Promise((resolve, reject) => {
        _refreshSubscribers.push((token) => {
          if (token) {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(api(originalRequest));
          } else {
            reject(error);
          }
        });
      });
    }

    _isRefreshing = true;
    try {
      const { data } = await supabase.auth.refreshSession();
      const newToken = data.session?.access_token ?? null;

      // Bust the cached session so subsequent requests pick up the new token
      _sessionPromise = null;
      _sessionCachedAt = 0;

      _onTokenRefreshed(newToken);

      if (newToken) {
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      }
    } catch {
      _onTokenRefreshed(null);
    } finally {
      _isRefreshing = false;
    }

    return Promise.reject(error);
  }

  // Surface plan-limit errors as upgrade prompts
  if (status === 403 && typeof detail === "string" && detail.toLowerCase().includes("plan")) {
    upgradeEvents.emit({
      title: "Plan limit reached",
      message: detail,
    });
  } else if (status === 429) {
    upgradeEvents.emit({
      title: "Usage limit reached",
      message: detail || "You've reached your plan's scan quota for this period.",
    });
  }

  return Promise.reject(error);
});

// ── Dashboard ──────────────────────────────────────────────────

export const getDashboardStats = async (): Promise<DashboardStats> => {
  const { data } = await api.get("/dashboard/stats");
  return data;
};

export const getRecentMatches = async (limit = 10): Promise<Match[]> => {
  const { data } = await api.get(`/dashboard/recent-matches?limit=${limit}`);
  return data;
};

export const getRecentAlerts = async (limit = 10): Promise<Alert[]> => {
  const { data } = await api.get(`/dashboard/recent-alerts?limit=${limit}`);
  return data;
};

export const getAlerts = async (unreadOnly = false, limit = 50, offset = 0): Promise<Alert[]> => {
  const { data } = await api.get(`/alerts?unread_only=${unreadOnly}&limit=${limit}&offset=${offset}`);
  return data;
};

export const getUnreadAlertCount = async (): Promise<{ unread_count: number }> => {
  const { data } = await api.get("/alerts/count");
  return data;
};

export const markAlertRead = async (alertId: string): Promise<Alert> => {
  const { data } = await api.patch(`/alerts/${alertId}/read`);
  return data;
};

export const markAllAlertsRead = async (): Promise<{ message: string }> => {
  const { data } = await api.post("/alerts/mark-all-read");
  return data;
};

export const deleteAlert = async (alertId: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/alerts/${alertId}`);
  return data;
};

export const getCoverageByChannel = async (): Promise<ChannelCoverage[]> => {
  const { data } = await api.get("/dashboard/coverage-by-channel");
  return data;
};

export const getCoverageByDistributor = async (limit = 10): Promise<DistributorCoverage[]> => {
  const { data } = await api.get(`/dashboard/coverage-by-distributor?limit=${limit}`);
  return data;
};

// ── Campaigns ──────────────────────────────────────────────────

export const getCampaigns = async (): Promise<Campaign[]> => {
  const { data } = await api.get("/campaigns");
  return data;
};

export const getCampaign = async (id: string): Promise<Campaign> => {
  const { data } = await api.get(`/campaigns/${id}`);
  return data;
};

export const createCampaign = async (campaign: CampaignCreate): Promise<Campaign> => {
  const { data } = await api.post("/campaigns", campaign);
  return data;
};

export const deleteCampaign = async (id: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/campaigns/${id}`);
  return data;
};

export const getCampaignAssets = async (campaignId: string): Promise<Asset[]> => {
  const { data } = await api.get(`/campaigns/${campaignId}/assets`);
  return data;
};

export const uploadAsset = async (campaignId: string, file: File, name?: string): Promise<Asset> => {
  const formData = new FormData();
  formData.append("file", file);
  if (name) formData.append("name", name);
  
  const { data } = await api.post(`/campaigns/${campaignId}/assets/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 60000,
  });
  return data;
};

export const deleteAsset = async (assetId: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/campaigns/assets/${assetId}`);
  return data;
};

// ── Distributors ───────────────────────────────────────────────

export const getDistributors = async (): Promise<Distributor[]> => {
  const { data } = await api.get("/distributors");
  return data;
};

export const getDistributor = async (id: string): Promise<Distributor> => {
  const { data } = await api.get(`/distributors/${id}`);
  return data;
};

export const createDistributor = async (distributor: DistributorCreate): Promise<Distributor> => {
  const { data } = await api.post("/distributors", distributor);
  return data;
};

export const deleteDistributor = async (id: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/distributors/${id}`);
  return data;
};

export const getDistributorMatches = async (id: string): Promise<Match[]> => {
  const { data } = await api.get(`/distributors/${id}/matches`);
  return data;
};

export const updateDistributor = async (id: string, updates: DistributorUpdate): Promise<Distributor> => {
  const { data } = await api.patch(`/distributors/${id}`, updates);
  return data;
};

export const lookupGoogleAdsId = async (distributorId: string): Promise<{ advertiser_id: string }> => {
  const { data } = await api.post(`/distributors/${distributorId}/lookup-google-ads-id`, {}, {
    timeout: 180000,
  });
  return data;
};

export const setGoogleAdsId = async (distributorId: string, advertiserId: string): Promise<Distributor> => {
  const { data } = await api.patch(`/distributors/${distributorId}/google-ads-id?advertiser_id=${advertiserId}`);
  return data;
};

// ── Matches ────────────────────────────────────────────────────

export const getMatches = async (filters?: MatchFilters): Promise<Match[]> => {
  const params = new URLSearchParams();
  if (filters?.status) params.append("compliance_status", filters.status);
  if (filters?.type) params.append("match_type", filters.type);
  if (filters?.minConfidence) params.append("min_confidence", filters.minConfidence);
  
  const { data } = await api.get(`/matches?${params.toString()}`);
  return data;
};

export const getMatch = async (id: string): Promise<Match> => {
  const { data } = await api.get(`/matches/${id}`);
  return data;
};

export const getMatchStats = async (): Promise<MatchStats> => {
  const { data } = await api.get("/matches/stats");
  return data;
};

export const approveMatch = async (id: string): Promise<Match> => {
  const { data } = await api.post(`/matches/${id}/approve`);
  return data;
};

export const flagMatch = async (id: string, reason?: string): Promise<Match> => {
  const { data } = await api.post(`/matches/${id}/flag`, { reason });
  return data;
};

export const deleteMatch = async (id: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/matches/${id}`);
  return data;
};

export const deleteAllMatches = async (): Promise<{ message: string }> => {
  const { data } = await api.delete("/matches");
  return data;
};

export const submitMatchFeedback = async (
  matchId: string,
  feedback: FeedbackSubmission
): Promise<{ message: string }> => {
  const { data } = await api.post(`/matches/${matchId}/feedback`, {
    match_id: matchId,
    ...feedback,
  });
  return data;
};

export const getFeedbackStats = async (): Promise<FeedbackStats[]> => {
  const { data } = await api.get("/matches/feedback/stats");
  return data;
};

export const getThresholdRecommendations = async (): Promise<ThresholdRecommendation[]> => {
  const { data } = await api.get("/matches/feedback/thresholds");
  return data;
};

// ── Scanning ───────────────────────────────────────────────────

export const startScan = async (source: string, distributorIds?: string[]): Promise<ScanJob> => {
  const { data } = await api.post("/scans/start", {
    source,
    distributor_ids: distributorIds,
  });
  return data;
};

export const getScanJobs = async (): Promise<ScanJob[]> => {
  const { data } = await api.get("/scans");
  return data;
};

export const getScanJob = async (id: string): Promise<ScanJob> => {
  const { data } = await api.get(`/scans/${id}`);
  return data;
};

export const deleteScan = async (id: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/scans/${id}`);
  return data;
};

export const deleteAllScans = async (): Promise<{ message: string }> => {
  const { data } = await api.delete("/scans");
  return data;
};

export const retryScan = async (jobId: string): Promise<ScanJob> => {
  const { data } = await api.post(`/scans/${jobId}/retry`);
  return data;
};

export const startBatchScan = async (): Promise<ScanJob[]> => {
  const { data } = await api.post("/scans/batch");
  return data;
};

export const getComplianceTrend = async (days: number = 30): Promise<ComplianceTrendPoint[]> => {
  const { data } = await api.get(`/dashboard/compliance-trend?days=${days}`);
  return data;
};

export const analyzeScanResults = async (jobId: string, campaignId?: string): Promise<ScanJob> => {
  const params = campaignId ? `?campaign_id=${campaignId}` : "";
  const { data } = await api.post(`/scans/${jobId}/analyze${params}`);
  return data;
};

// ── Campaign Scans ─────────────────────────────────────────────

export const startCampaignScan = async (
  campaignId: string,
  source: string,
  distributorIds?: string[]
): Promise<ScanJob> => {
  const params = new URLSearchParams();
  params.append("source", source);
  if (distributorIds && distributorIds.length > 0) {
    distributorIds.forEach((id) => params.append("distributor_ids", id));
  }
  
  const { data } = await api.post(`/campaigns/${campaignId}/scans/start?${params.toString()}`);
  return data;
};

export const getCampaignScans = async (campaignId: string, status?: string): Promise<ScanJob[]> => {
  const params = status ? `?status=${status}` : "";
  const { data } = await api.get(`/campaigns/${campaignId}/scans${params}`);
  return data;
};

export const getCampaignScan = async (campaignId: string, scanId: string): Promise<ScanJob> => {
  const { data } = await api.get(`/campaigns/${campaignId}/scans/${scanId}`);
  return data;
};

export const analyzeCampaignScan = async (campaignId: string, scanId: string): Promise<ScanJob> => {
  const { data } = await api.post(`/campaigns/${campaignId}/scans/${scanId}/analyze`);
  return data;
};

export const getCampaignMatches = async (campaignId: string, complianceStatus?: string): Promise<Match[]> => {
  const params = complianceStatus ? `?compliance_status=${complianceStatus}` : "";
  const { data } = await api.get(`/campaigns/${campaignId}/matches${params}`);
  return data;
};

export const getCampaignScanStats = async (campaignId: string): Promise<{ total_scans: number; completed_scans: number; total_matches: number }> => {
  const { data } = await api.get(`/campaigns/${campaignId}/scan-stats`);
  return data;
};

// ── Organizations ──────────────────────────────────────────────

export const getOrgSettings = async (orgId?: string): Promise<OrgSettings> => {
  const id = orgId || "me";
  const { data: meData } = await api.get("/auth/me");
  const resolvedId = orgId || meData.organization_id;
  const { data } = await api.get(`/organizations/${resolvedId}/settings`);
  return data;
};

export const updateOrgSettings = async (
  updates: OrgSettingsUpdate,
  orgId?: string
): Promise<OrgSettings> => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.patch(`/organizations/${resolvedId}/settings`, updates);
  return data;
};

export const sendTestEmail = async (orgId?: string): Promise<{ message: string }> => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.post(`/organizations/${resolvedId}/test-email`);
  return data;
};

export const getOrgLogo = async (orgId?: string): Promise<{ logo_url: string | null }> => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.get(`/organizations/${resolvedId}/logo`);
  return data;
};

export const uploadOrgLogo = async (file: File, orgId?: string): Promise<{ logo_url: string }> => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post(`/organizations/${resolvedId}/logo`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 30000,
  });
  return data;
};

export const deleteOrgLogo = async (orgId?: string): Promise<{ message: string }> => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.delete(`/organizations/${resolvedId}/logo`);
  return data;
};

// ── Integrations ───────────────────────────────────────────────

export interface SlackStatus {
  connected: boolean;
  workspace_name?: string;
  channel_name?: string;
  connected_at?: string;
}

export const getSlackStatus = async (): Promise<SlackStatus> => {
  const { data } = await api.get("/integrations/slack/status");
  return data;
};

export const startSlackInstall = async (): Promise<{ authorize_url: string }> => {
  const { data } = await api.get("/integrations/slack/install");
  return data;
};

export const disconnectSlack = async (): Promise<{ status: string }> => {
  const { data } = await api.delete("/integrations/slack");
  return data;
};

export const testSlackMessage = async (): Promise<{ success: boolean; message: string }> => {
  const { data } = await api.post("/integrations/slack/test");
  return data;
};

export interface SalesforceStatus {
  connected: boolean;
  org_name?: string;
  instance_url?: string;
  connected_at?: string;
}

export const getSalesforceStatus = async (): Promise<SalesforceStatus> => {
  const { data } = await api.get("/integrations/salesforce/status");
  return data;
};

export const startSalesforceInstall = async (): Promise<{ authorize_url: string }> => {
  const { data } = await api.get("/integrations/salesforce/install");
  return data;
};

export const disconnectSalesforce = async (): Promise<{ status: string }> => {
  const { data } = await api.delete("/integrations/salesforce");
  return data;
};

export const testSalesforceTask = async (): Promise<{ success: boolean; message: string }> => {
  const { data } = await api.post("/integrations/salesforce/test");
  return data;
};

export interface DropboxStatus {
  connected: boolean;
  account_name?: string;
  folder_path?: string | null;
  folder_name?: string | null;
  campaign_id?: string | null;
  last_synced_at?: string | null;
  connected_at?: string;
}

export interface DropboxFolder {
  name: string;
  path: string;
}

export const getDropboxStatus = async (): Promise<DropboxStatus> => {
  const { data } = await api.get("/integrations/dropbox/status");
  return data;
};

export const startDropboxInstall = async (): Promise<{ authorize_url: string }> => {
  const { data } = await api.get("/integrations/dropbox/install");
  return data;
};

export const disconnectDropbox = async (): Promise<{ status: string }> => {
  const { data } = await api.delete("/integrations/dropbox");
  return data;
};

export const listDropboxFolders = async (path = ""): Promise<{ folders: DropboxFolder[]; image_count: number; current_path: string }> => {
  const { data } = await api.get(`/integrations/dropbox/folders?path=${encodeURIComponent(path)}`);
  return data;
};

export const selectDropboxFolder = async (folderPath: string, folderName: string, campaignId: string): Promise<{ status: string }> => {
  const { data } = await api.post("/integrations/dropbox/select-folder", {
    folder_path: folderPath,
    folder_name: folderName,
    campaign_id: campaignId,
  });
  return data;
};

export const syncDropbox = async (): Promise<{ imported: number; skipped: number; errors: number; message: string }> => {
  const { data } = await api.post("/integrations/dropbox/sync", {}, { timeout: 120000 });
  return data;
};

export const autoSyncDropbox = async (): Promise<{
  success: boolean;
  campaigns_created: number;
  images_imported: number;
  images_skipped: number;
  message: string;
}> => {
  const { data } = await api.post("/integrations/dropbox/auto-sync", {}, { timeout: 120000 });
  return data;
};

// ── Billing ────────────────────────────────────────────────────

export const getBillingUsage = async (): Promise<BillingUsage> => {
  const { data } = await api.get("/billing/usage");
  return data;
};

export const createCheckoutSession = async (plan: string): Promise<{ url: string }> => {
  const { data } = await api.post("/billing/checkout-session", { plan });
  return data;
};

export const createPortalSession = async (): Promise<{ portal_url: string }> => {
  const { data } = await api.post("/billing/portal-session");
  return data;
};

// ── Team ───────────────────────────────────────────────────────

export const getTeamMembers = async (): Promise<TeamMember[]> => {
  const { data } = await api.get("/team/members");
  return data;
};

export const getTeamInvites = async (): Promise<TeamInvite[]> => {
  const { data } = await api.get("/team/invites");
  return data;
};

export const inviteTeamMember = async (email: string, role: string = "member"): Promise<TeamInvite> => {
  const { data } = await api.post("/team/invites", { email, role });
  return data;
};

export const cancelInvite = async (inviteId: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/team/invites/${inviteId}`);
  return data;
};

export const removeTeamMember = async (userId: string): Promise<{ message: string }> => {
  const { data } = await api.delete(`/team/members/${userId}`);
  return data;
};

export const acceptInvite = async (token: string): Promise<{ status: string; organization_id: string; role: string }> => {
  const { data } = await api.post(`/team/invites/${token}/accept`);
  return data;
};

// ── Reports ────────────────────────────────────────────────────

export const downloadComplianceReport = async (
  format: "pdf" | "csv" = "pdf",
  options?: {
    days?: number;
    campaign_id?: string;
    distributor_id?: string;
  }
): Promise<void> => {
  const params = new URLSearchParams();
  params.append("format", format);
  if (options?.days) params.append("days", String(options.days));
  if (options?.campaign_id) params.append("campaign_id", options.campaign_id);
  if (options?.distributor_id) params.append("distributor_id", options.distributor_id);

  const response = await api.get(`/reports/compliance?${params.toString()}`, {
    responseType: "blob",
    timeout: 60000,
  });

  const disposition = response.headers["content-disposition"] || "";
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch
    ? filenameMatch[1]
    : `compliance_report.${format}`;

  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

// ── Scan Schedules ─────────────────────────────────────────────
export interface ScanSchedule {
  id: string;
  organization_id: string;
  campaign_id: string;
  source: string;
  frequency: string;
  run_at_time: string | null;
  run_on_day: number | null;
  is_active: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export const getSchedules = async (campaignId?: string): Promise<ScanSchedule[]> => {
  const params = campaignId ? `?campaign_id=${campaignId}` : "";
  const { data } = await api.get(`/schedules${params}`);
  return data;
};

export const createSchedule = async (
  campaignId: string,
  source: string,
  frequency: string,
  runAtTime: string = "09:00",
  runOnDay?: number
): Promise<ScanSchedule> => {
  const { data } = await api.post("/schedules", {
    campaign_id: campaignId,
    source,
    frequency,
    run_at_time: runAtTime,
    run_on_day: runOnDay ?? null,
  });
  return data;
};

export const updateSchedule = async (
  scheduleId: string,
  updates: { frequency?: string; is_active?: boolean; run_at_time?: string; run_on_day?: number }
): Promise<ScanSchedule> => {
  const { data } = await api.patch(`/schedules/${scheduleId}`, updates);
  return data;
};

export const deleteSchedule = async (scheduleId: string): Promise<void> => {
  await api.delete(`/schedules/${scheduleId}`);
};

// ── Compliance Rules ──────────────────────────────────────────

export const getComplianceRules = async (activeOnly = false): Promise<ComplianceRule[]> => {
  const { data } = await api.get(`/compliance-rules?active_only=${activeOnly}`);
  return data;
};

export const getComplianceRule = async (id: string): Promise<ComplianceRule> => {
  const { data } = await api.get(`/compliance-rules/${id}`);
  return data;
};

export const createComplianceRule = async (rule: ComplianceRuleCreate): Promise<ComplianceRule> => {
  const { data } = await api.post("/compliance-rules", rule);
  return data;
};

export const updateComplianceRule = async (id: string, updates: ComplianceRuleUpdate): Promise<ComplianceRule> => {
  const { data } = await api.patch(`/compliance-rules/${id}`, updates);
  return data;
};

export const deleteComplianceRule = async (id: string): Promise<{ status: string }> => {
  const { data } = await api.delete(`/compliance-rules/${id}`);
  return data;
};
