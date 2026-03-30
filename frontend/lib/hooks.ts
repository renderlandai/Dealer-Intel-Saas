import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getDashboardStats,
  getRecentMatches,
  getRecentAlerts,
  getAlerts,
  getUnreadAlertCount,
  markAlertRead,
  markAllAlertsRead,
  deleteAlert,
  getCoverageByChannel,
  getCampaigns,
  getCampaign,
  getCampaignAssets,
  getDistributors,
  getDistributor,
  getDistributorMatches,
  getMatches,
  getMatch,
  getMatchStats,
  getScanJobs,
  createCampaign,
  createDistributor,
  updateDistributor,
  deleteCampaign,
  deleteDistributor,
  approveMatch,
  flagMatch,
  deleteMatch,
  deleteAllMatches,
  deleteScan,
  deleteAllScans,
  retryScan,
  startBatchScan,
  getComplianceTrend,
  submitMatchFeedback,
  getFeedbackStats,
  getBillingUsage,
} from "./api";
import type {
  MatchFilters,
  DistributorUpdate,
  FeedbackSubmission,
} from "./api";

// Query keys for cache management
export const queryKeys = {
  billing: {
    usage: ["billing", "usage"] as const,
  },
  dashboard: {
    stats: ["dashboard", "stats"] as const,
    recentMatches: (limit: number) => ["dashboard", "recentMatches", limit] as const,
    recentAlerts: (limit: number) => ["dashboard", "recentAlerts", limit] as const,
    channelCoverage: ["dashboard", "channelCoverage"] as const,
  },
  campaigns: {
    all: ["campaigns"] as const,
    detail: (id: string) => ["campaigns", id] as const,
    assets: (id: string) => ["campaigns", id, "assets"] as const,
  },
  distributors: {
    all: ["distributors"] as const,
    detail: (id: string) => ["distributors", id] as const,
    matches: (id: string) => ["distributors", id, "matches"] as const,
  },
  matches: {
    all: (filters?: MatchFilters) => ["matches", filters] as const,
    detail: (id: string) => ["matches", id] as const,
    stats: ["matches", "stats"] as const,
  },
  scans: {
    all: ["scans"] as const,
  },
};

// Billing hooks
export function useBillingUsage() {
  return useQuery({
    queryKey: queryKeys.billing.usage,
    queryFn: getBillingUsage,
    staleTime: 60_000,
  });
}

// Dashboard hooks
export function useDashboardStats() {
  return useQuery({
    queryKey: queryKeys.dashboard.stats,
    queryFn: getDashboardStats,
  });
}

export function useRecentMatches(limit = 10) {
  return useQuery({
    queryKey: queryKeys.dashboard.recentMatches(limit),
    queryFn: () => getRecentMatches(limit),
  });
}

export function useRecentAlerts(limit = 10) {
  return useQuery({
    queryKey: queryKeys.dashboard.recentAlerts(limit),
    queryFn: () => getRecentAlerts(limit),
  });
}

// Alert hooks
export function useAlerts(unreadOnly = false) {
  return useQuery({
    queryKey: ["alerts", { unreadOnly }] as const,
    queryFn: () => getAlerts(unreadOnly),
  });
}

export function useUnreadAlertCount() {
  return useQuery({
    queryKey: ["alerts", "unread-count"] as const,
    queryFn: getUnreadAlertCount,
    refetchInterval: 60_000,
  });
}

export function useMarkAlertRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: markAlertRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useMarkAllAlertsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: markAllAlertsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useDeleteAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAlert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useChannelCoverage() {
  return useQuery({
    queryKey: queryKeys.dashboard.channelCoverage,
    queryFn: getCoverageByChannel,
  });
}

// Campaign hooks
export function useCampaigns() {
  return useQuery({
    queryKey: queryKeys.campaigns.all,
    queryFn: getCampaigns,
  });
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: queryKeys.campaigns.detail(id),
    queryFn: () => getCampaign(id),
    enabled: !!id,
  });
}

export function useCampaignAssets(campaignId: string) {
  return useQuery({
    queryKey: queryKeys.campaigns.assets(campaignId),
    queryFn: () => getCampaignAssets(campaignId),
    enabled: !!campaignId,
  });
}

export function useCreateCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createCampaign,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useDeleteCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteCampaign,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

// Distributor hooks
export function useDistributors() {
  return useQuery({
    queryKey: queryKeys.distributors.all,
    queryFn: getDistributors,
  });
}

export function useDistributor(id: string) {
  return useQuery({
    queryKey: queryKeys.distributors.detail(id),
    queryFn: () => getDistributor(id),
    enabled: !!id,
  });
}

export function useDistributorMatches(id: string) {
  return useQuery({
    queryKey: queryKeys.distributors.matches(id),
    queryFn: () => getDistributorMatches(id),
    enabled: !!id,
  });
}

export function useCreateDistributor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createDistributor,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.distributors.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useUpdateDistributor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: DistributorUpdate }) => updateDistributor(id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.distributors.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useDeleteDistributor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteDistributor,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.distributors.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

// Match hooks
export function useMatches(filters?: MatchFilters) {
  return useQuery({
    queryKey: queryKeys.matches.all(filters),
    queryFn: () => getMatches(filters),
  });
}

export function useMatch(id: string) {
  return useQuery({
    queryKey: queryKeys.matches.detail(id),
    queryFn: () => getMatch(id),
    enabled: !!id,
  });
}

export function useMatchStats() {
  return useQuery({
    queryKey: queryKeys.matches.stats,
    queryFn: getMatchStats,
  });
}

export function useApproveMatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: approveMatch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["matches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useFlagMatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => flagMatch(id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["matches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

// Scan hooks
export function useScanJobs() {
  return useQuery({
    queryKey: queryKeys.scans.all,
    queryFn: getScanJobs,
  });
}

export function useDeleteScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.scans.all });
      queryClient.invalidateQueries({ queryKey: ["matches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useDeleteAllScans() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAllScans,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.scans.all });
      queryClient.invalidateQueries({ queryKey: ["matches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useRetryScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: retryScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.scans.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useBatchScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startBatchScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.scans.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useComplianceTrend(days: number = 30) {
  return useQuery({
    queryKey: ["compliance-trend", days] as const,
    queryFn: () => getComplianceTrend(days),
    staleTime: 5 * 60_000,
  });
}

export function useDeleteMatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteMatch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["matches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useDeleteAllMatches() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAllMatches,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["matches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats });
    },
  });
}

export function useSubmitFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      matchId,
      feedback,
    }: {
      matchId: string;
      feedback: FeedbackSubmission;
    }) => submitMatchFeedback(matchId, feedback),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["matches"] });
      queryClient.invalidateQueries({ queryKey: ["feedbackStats"] });
    },
  });
}

export function useFeedbackStats() {
  return useQuery({
    queryKey: ["feedbackStats"],
    queryFn: getFeedbackStats,
  });
}




