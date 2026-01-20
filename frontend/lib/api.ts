import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 15000, // 15 second timeout
});

// Demo organization ID
export const DEMO_ORG_ID = "00000000-0000-0000-0000-000000000001";

// Dashboard
export const getDashboardStats = async () => {
  const { data } = await api.get(`/dashboard/stats?organization_id=${DEMO_ORG_ID}`);
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
  const { data } = await api.get(`/campaigns?organization_id=${DEMO_ORG_ID}`);
  return data;
};

export const getCampaign = async (id: string) => {
  const { data } = await api.get(`/campaigns/${id}`);
  return data;
};

export const createCampaign = async (campaign: any) => {
  const { data } = await api.post("/campaigns", {
    ...campaign,
    organization_id: DEMO_ORG_ID,
  });
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
    timeout: 60000, // 60 second timeout for file uploads
  });
  return data;
};

export const deleteAsset = async (assetId: string) => {
  const { data } = await api.delete(`/campaigns/assets/${assetId}`);
  return data;
};

// Distributors
export const getDistributors = async () => {
  const { data } = await api.get(`/distributors?organization_id=${DEMO_ORG_ID}`);
  return data;
};

export const getDistributor = async (id: string) => {
  const { data } = await api.get(`/distributors/${id}`);
  return data;
};

export const createDistributor = async (distributor: any) => {
  const { data } = await api.post("/distributors", {
    ...distributor,
    organization_id: DEMO_ORG_ID,
  });
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
    timeout: 180000, // 3 minute timeout for this long-running operation
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

// Scanning
export const startScan = async (source: string, distributorIds?: string[]) => {
  const { data } = await api.post("/scans/start", {
    organization_id: DEMO_ORG_ID,
    source,
    distributor_ids: distributorIds,
  });
  return data;
};

export const getScanJobs = async () => {
  const { data } = await api.get(`/scans?organization_id=${DEMO_ORG_ID}`);
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

