import axios from "axios";
import { supabase } from "./supabase";
import { upgradeEvents } from "./upgrade-events";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 15000,
});

// Attach Supabase JWT to every request
api.interceptors.request.use(async (config) => {
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    config.headers.Authorization = `Bearer ${session.access_token}`;
  }
  return config;
});

// Surface plan-limit errors as upgrade prompts instead of generic failures
api.interceptors.response.use(undefined, (error) => {
  const status = error?.response?.status;
  const detail = error?.response?.data?.detail;

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

// Dashboard
export const getDashboardStats = async () => {
  const { data } = await api.get("/dashboard/stats");
  return data;
};

export const getRecentMatches = async (limit = 10) => {
  const { data } = await api.get(`/dashboard/recent-matches?limit=${limit}`);
  return data;
};

export const getRecentAlerts = async (limit = 10) => {
  const { data } = await api.get(`/dashboard/recent-alerts?limit=${limit}`);
  return data;
};

export const getAlerts = async (unreadOnly = false, limit = 50, offset = 0) => {
  const { data } = await api.get(`/alerts?unread_only=${unreadOnly}&limit=${limit}&offset=${offset}`);
  return data;
};

export const getUnreadAlertCount = async () => {
  const { data } = await api.get("/alerts/count");
  return data;
};

export const markAlertRead = async (alertId: string) => {
  const { data } = await api.patch(`/alerts/${alertId}/read`);
  return data;
};

export const markAllAlertsRead = async () => {
  const { data } = await api.post("/alerts/mark-all-read");
  return data;
};

export const deleteAlert = async (alertId: string) => {
  const { data } = await api.delete(`/alerts/${alertId}`);
  return data;
};

export const getCoverageByChannel = async () => {
  const { data } = await api.get("/dashboard/coverage-by-channel");
  return data;
};

export const getCoverageByDistributor = async (limit = 10) => {
  const { data } = await api.get(`/dashboard/coverage-by-distributor?limit=${limit}`);
  return data;
};

// Campaigns
export const getCampaigns = async () => {
  const { data } = await api.get("/campaigns");
  return data;
};

export const getCampaign = async (id: string) => {
  const { data } = await api.get(`/campaigns/${id}`);
  return data;
};

export const createCampaign = async (campaign: any) => {
  const { data } = await api.post("/campaigns", campaign);
  return data;
};

export const deleteCampaign = async (id: string) => {
  const { data } = await api.delete(`/campaigns/${id}`);
  return data;
};

export const getCampaignAssets = async (campaignId: string) => {
  const { data } = await api.get(`/campaigns/${campaignId}/assets`);
  return data;
};

export const uploadAsset = async (campaignId: string, file: File, name?: string) => {
  const formData = new FormData();
  formData.append("file", file);
  if (name) formData.append("name", name);
  
  const { data } = await api.post(`/campaigns/${campaignId}/assets/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 60000,
  });
  return data;
};

export const deleteAsset = async (assetId: string) => {
  const { data } = await api.delete(`/campaigns/assets/${assetId}`);
  return data;
};

// Distributors
export const getDistributors = async () => {
  const { data } = await api.get("/distributors");
  return data;
};

export const getDistributor = async (id: string) => {
  const { data } = await api.get(`/distributors/${id}`);
  return data;
};

export const createDistributor = async (distributor: any) => {
  const { data } = await api.post("/distributors", distributor);
  return data;
};

export const deleteDistributor = async (id: string) => {
  const { data } = await api.delete(`/distributors/${id}`);
  return data;
};

export const getDistributorMatches = async (id: string) => {
  const { data } = await api.get(`/distributors/${id}/matches`);
  return data;
};

export const updateDistributor = async (id: string, updates: any) => {
  const { data } = await api.patch(`/distributors/${id}`, updates);
  return data;
};

export const lookupGoogleAdsId = async (distributorId: string) => {
  const { data } = await api.post(`/distributors/${distributorId}/lookup-google-ads-id`, {}, {
    timeout: 180000,
  });
  return data;
};

export const setGoogleAdsId = async (distributorId: string, advertiserId: string) => {
  const { data } = await api.patch(`/distributors/${distributorId}/google-ads-id?advertiser_id=${advertiserId}`);
  return data;
};

// Matches
export const getMatches = async (filters?: any) => {
  const params = new URLSearchParams();
  if (filters?.status) params.append("compliance_status", filters.status);
  if (filters?.type) params.append("match_type", filters.type);
  if (filters?.minConfidence) params.append("min_confidence", filters.minConfidence);
  
  const { data } = await api.get(`/matches?${params.toString()}`);
  return data;
};

export const getMatch = async (id: string) => {
  const { data } = await api.get(`/matches/${id}`);
  return data;
};

export const getMatchStats = async () => {
  const { data } = await api.get("/matches/stats");
  return data;
};

export const approveMatch = async (id: string) => {
  const { data } = await api.post(`/matches/${id}/approve`);
  return data;
};

export const flagMatch = async (id: string, reason?: string) => {
  const { data } = await api.post(`/matches/${id}/flag`, { reason });
  return data;
};

export const deleteMatch = async (id: string) => {
  const { data } = await api.delete(`/matches/${id}`);
  return data;
};

export const deleteAllMatches = async () => {
  const { data } = await api.delete("/matches");
  return data;
};

export const submitMatchFeedback = async (
  matchId: string,
  feedback: {
    was_correct: boolean;
    actual_verdict: "true_positive" | "false_positive" | "true_negative" | "false_negative";
    review_notes?: string;
  }
) => {
  const { data } = await api.post(`/matches/${matchId}/feedback`, {
    match_id: matchId,
    ...feedback,
  });
  return data;
};

export const getFeedbackStats = async () => {
  const { data } = await api.get("/matches/feedback/stats");
  return data;
};

export const getThresholdRecommendations = async () => {
  const { data } = await api.get("/matches/feedback/thresholds");
  return data;
};

// Scanning
export const startScan = async (source: string, distributorIds?: string[]) => {
  const { data } = await api.post("/scans/start", {
    source,
    distributor_ids: distributorIds,
  });
  return data;
};

export const getScanJobs = async () => {
  const { data } = await api.get("/scans");
  return data;
};

export const getScanJob = async (id: string) => {
  const { data } = await api.get(`/scans/${id}`);
  return data;
};

export const deleteScan = async (id: string) => {
  const { data } = await api.delete(`/scans/${id}`);
  return data;
};

export const deleteAllScans = async () => {
  const { data } = await api.delete("/scans");
  return data;
};

export const retryScan = async (jobId: string) => {
  const { data } = await api.post(`/scans/${jobId}/retry`);
  return data;
};

export const startBatchScan = async () => {
  const { data } = await api.post("/scans/batch");
  return data;
};

export const getComplianceTrend = async (days: number = 30) => {
  const { data } = await api.get(`/dashboard/compliance-trend?days=${days}`);
  return data;
};

export const analyzeScanResults = async (jobId: string, campaignId?: string) => {
  const params = campaignId ? `?campaign_id=${campaignId}` : "";
  const { data } = await api.post(`/scans/${jobId}/analyze${params}`);
  return data;
};

// Campaign Scans
export const startCampaignScan = async (
  campaignId: string,
  source: string,
  distributorIds?: string[]
) => {
  const params = new URLSearchParams();
  params.append("source", source);
  if (distributorIds && distributorIds.length > 0) {
    distributorIds.forEach((id) => params.append("distributor_ids", id));
  }
  
  const { data } = await api.post(`/campaigns/${campaignId}/scans/start?${params.toString()}`);
  return data;
};

export const getCampaignScans = async (campaignId: string, status?: string) => {
  const params = status ? `?status=${status}` : "";
  const { data } = await api.get(`/campaigns/${campaignId}/scans${params}`);
  return data;
};

export const getCampaignScan = async (campaignId: string, scanId: string) => {
  const { data } = await api.get(`/campaigns/${campaignId}/scans/${scanId}`);
  return data;
};

export const analyzeCampaignScan = async (campaignId: string, scanId: string) => {
  const { data } = await api.post(`/campaigns/${campaignId}/scans/${scanId}/analyze`);
  return data;
};

export const getCampaignMatches = async (campaignId: string, complianceStatus?: string) => {
  const params = complianceStatus ? `?compliance_status=${complianceStatus}` : "";
  const { data } = await api.get(`/campaigns/${campaignId}/matches${params}`);
  return data;
};

export const getCampaignScanStats = async (campaignId: string) => {
  const { data } = await api.get(`/campaigns/${campaignId}/scan-stats`);
  return data;
};

// Organizations
export const getOrgSettings = async (orgId?: string) => {
  const id = orgId || "me";
  const { data: meData } = await api.get("/auth/me");
  const resolvedId = orgId || meData.organization_id;
  const { data } = await api.get(`/organizations/${resolvedId}/settings`);
  return data;
};

export const updateOrgSettings = async (
  updates: {
    name?: string;
    report_brand_color?: string;
    notify_email?: string;
    notify_on_violation?: boolean;
  },
  orgId?: string
) => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.patch(`/organizations/${resolvedId}/settings`, updates);
  return data;
};

export const sendTestEmail = async (orgId?: string) => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.post(`/organizations/${resolvedId}/test-email`);
  return data;
};

export const getOrgLogo = async (orgId?: string) => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.get(`/organizations/${resolvedId}/logo`);
  return data;
};

export const uploadOrgLogo = async (file: File, orgId?: string) => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post(`/organizations/${resolvedId}/logo`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 30000,
  });
  return data;
};

export const deleteOrgLogo = async (orgId?: string) => {
  const resolvedId = orgId || (await api.get("/auth/me")).data.organization_id;
  const { data } = await api.delete(`/organizations/${resolvedId}/logo`);
  return data;
};

// Billing
export const getBillingUsage = async () => {
  const { data } = await api.get("/billing/usage");
  return data;
};

export const createCheckoutSession = async (plan: string) => {
  const { data } = await api.post("/billing/checkout-session", { plan });
  return data;
};

export const createPortalSession = async () => {
  const { data } = await api.post("/billing/portal-session");
  return data;
};

// Team
export const getTeamMembers = async () => {
  const { data } = await api.get("/team/members");
  return data;
};

export const getTeamInvites = async () => {
  const { data } = await api.get("/team/invites");
  return data;
};

export const inviteTeamMember = async (email: string, role: string = "member") => {
  const { data } = await api.post("/team/invites", { email, role });
  return data;
};

export const cancelInvite = async (inviteId: string) => {
  const { data } = await api.delete(`/team/invites/${inviteId}`);
  return data;
};

export const removeTeamMember = async (userId: string) => {
  const { data } = await api.delete(`/team/members/${userId}`);
  return data;
};

// Reports
export const downloadComplianceReport = async (
  format: "pdf" | "csv" = "pdf",
  options?: {
    days?: number;
    campaign_id?: string;
    distributor_id?: string;
  }
) => {
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
