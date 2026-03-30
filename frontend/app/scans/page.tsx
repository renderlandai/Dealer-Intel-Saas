"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Play,
  Clock,
  CheckCircle,
  XCircle,
  RefreshCw,
  Loader2,
  Megaphone,
  Radar,
  Eye,
  Trash2,
  ChevronDown,
  ChevronUp,
  BarChart3,
  Layers,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useScanJobs, useCampaigns, useDeleteScan, useDeleteAllScans, useRetryScan, useBatchScan, useBillingUsage } from "@/lib/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { formatDateTime } from "@/lib/utils";

interface PipelineStats {
  total_images: number;
  download_failed: number;
  hash_rejected: number;
  clip_rejected: number;
  filter_rejected: number;
  below_threshold: number;
  verification_rejected: number;
  matched_new: number;
  matched_confirmed: number;
  drift_detected: number;
  errors: number;
  image_cache?: { hits: number; misses: number; hit_rate: number; cached_entries: number; cached_mb: number };
  pages_discovered?: number;
  pages_scanned?: number;
  pages_skipped?: number;
  early_stopped?: boolean;
  cache_hit?: boolean;
  cached_pages_used?: number;
  // Legacy fields for backward compat with older scans
  matched?: number;
  duplicates_skipped?: number;
}

interface ScanJob {
  id: string;
  campaign_id?: string;
  source: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  total_items: number;
  processed_items: number;
  matches_count: number;
  error_message?: string;
  pipeline_stats?: PipelineStats;
  created_at: string;
}

interface Campaign {
  id: string;
  name: string;
  status: string;
  asset_count: number;
}

function PipelineFunnel({ stats }: { stats: PipelineStats }) {
  const newMatches = stats.matched_new ?? stats.matched ?? 0;
  const confirmed = stats.matched_confirmed ?? 0;
  const drift = stats.drift_detected ?? 0;

  const stages = [
    { label: "Total Images", value: stats.total_images, color: "bg-slate-500" },
    { label: "Download Failed", value: stats.download_failed, color: "bg-red-500" },
    { label: "Hash Rejected", value: stats.hash_rejected, color: "bg-orange-500" },
    { label: "CLIP Rejected", value: stats.clip_rejected, color: "bg-amber-500" },
    { label: "Haiku Filter Rejected", value: stats.filter_rejected, color: "bg-yellow-500" },
    { label: "Below Threshold", value: stats.below_threshold, color: "bg-purple-500" },
    { label: "Verification Rejected", value: stats.verification_rejected, color: "bg-pink-500" },
    { label: "Errors", value: stats.errors, color: "bg-red-600" },
    { label: "New Matches", value: newMatches, color: "bg-green-500" },
    { label: "Confirmed Matches", value: confirmed, color: "bg-emerald-400" },
    ...(drift > 0 ? [{ label: "Compliance Drift", value: drift, color: "bg-amber-500" }] : []),
  ];

  const maxVal = stats.total_images || 1;

  return (
    <div className="mt-3 space-y-1.5 p-3 rounded-lg bg-muted/50 border border-border/50">
      {stages.map((stage) => (
        <div key={stage.label} className="flex items-center gap-3 text-xs">
          <span className="w-36 text-muted-foreground shrink-0">{stage.label}</span>
          <div className="flex-1 h-4 bg-muted rounded-full overflow-hidden">
            <div
              className={`h-full ${stage.color} rounded-full transition-all`}
              style={{ width: `${Math.max((stage.value / maxVal) * 100, stage.value > 0 ? 2 : 0)}%` }}
            />
          </div>
          <span className="w-8 text-right font-mono tabular-nums">{stage.value}</span>
        </div>
      ))}
      {stats.pages_discovered != null && (
        <div className={`mt-2 pt-2 border-t border-border/30 text-xs flex gap-4 ${stats.early_stopped ? "text-emerald-400" : "text-muted-foreground"}`}>
          {stats.cache_hit ? (
            <>
              <span>Cache Hit: all assets matched from {stats.cached_pages_used} cached page(s)</span>
              <span>Page discovery skipped</span>
            </>
          ) : stats.early_stopped ? (
            <>
              <span>Early Stop: all assets matched after {stats.pages_scanned}/{stats.pages_discovered} pages</span>
              <span>{stats.pages_skipped} pages skipped</span>
              {(stats.cached_pages_used ?? 0) > 0 && (
                <span>{stats.cached_pages_used} from cache</span>
              )}
            </>
          ) : (
            <span>
              Pages: {stats.pages_scanned}/{stats.pages_discovered} scanned
              {(stats.cached_pages_used ?? 0) > 0 && ` (${stats.cached_pages_used} from cache)`}
            </span>
          )}
        </div>
      )}
      {stats.image_cache && (
        <div className="mt-2 pt-2 border-t border-border/30 text-xs text-muted-foreground flex gap-4">
          <span>Image Cache: {stats.image_cache.hit_rate}% hit rate</span>
          <span>{stats.image_cache.hits} hits / {stats.image_cache.misses} downloads</span>
          <span>{stats.image_cache.cached_mb} MB cached</span>
        </div>
      )}
    </div>
  );
}

export default function ScansPage() {
  const { data: scanJobs = [], isLoading: loading } = useScanJobs();
  const { data: allCampaigns = [] } = useCampaigns();
  const queryClient = useQueryClient();
  const deleteScanMutation = useDeleteScan();
  const deleteAllScansMutation = useDeleteAllScans();
  const retryScanMutation = useRetryScan();
  const batchScanMutation = useBatchScan();
  const { data: billing } = useBillingUsage();
  
  const campaigns = allCampaigns.filter((c: Campaign) => c.status === "active");
  const canBatchScan = billing?.plan && ["professional", "business", "enterprise"].includes(billing.plan);

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["scans"] });
  };

  const handleDeleteScan = async (id: string) => {
    if (confirm("Delete this scan and all its results?")) {
      try {
        await deleteScanMutation.mutateAsync(id);
      } catch (error: any) {
        console.error("Failed to delete scan:", error);
        alert(error?.response?.data?.detail || "Failed to delete scan.");
      }
    }
  };

  const handleDeleteAllScans = async () => {
    if (confirm("Delete ALL scans and results? This cannot be undone.")) {
      try {
        await deleteAllScansMutation.mutateAsync();
      } catch (error: any) {
        console.error("Failed to delete all scans:", error);
        alert(error?.response?.data?.detail || "Failed to delete scans.");
      }
    }
  };

  const sourceLabels: Record<string, string> = {
    google_ads: "Google Ads",
    facebook: "Facebook",
    instagram: "Instagram",
    youtube: "YouTube",
    website: "Website",
  };

  const statusIcons: Record<string, JSX.Element> = {
    pending: <Clock className="h-4 w-4 text-yellow-400" />,
    running: <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />,
    analyzing: <Loader2 className="h-4 w-4 text-purple-400 animate-spin" />,
    completed: <CheckCircle className="h-4 w-4 text-green-400" />,
    failed: <XCircle className="h-4 w-4 text-red-400" />,
  };

  const statusColors: Record<string, string> = {
    pending: "bg-yellow-500/20 text-yellow-400",
    running: "bg-blue-500/20 text-blue-400",
    analyzing: "bg-purple-500/20 text-purple-400",
    completed: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
  };

  const [expandedJobs, setExpandedJobs] = useState<Set<string>>(new Set());

  const toggleExpanded = (id: string) => {
    setExpandedJobs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="min-h-screen">
      <Header
        title="Scan Jobs"
        description="Manage and monitor data collection scans"
      />

      <div className="p-6 space-y-6">
        {/* Start Scan - Select Campaign */}
        <Card className="border-primary/20 bg-gradient-to-r from-primary/5 to-transparent">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Radar className="h-5 w-5 text-primary" />
              Start New Scan
            </CardTitle>
            <CardDescription>
              Select a campaign to scan. Scans will search distributor channels for your campaign assets.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {campaigns.length === 0 ? (
              <div className="text-center py-6">
                <Megaphone className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
                <p className="text-muted-foreground mb-3">
                  No active campaigns found. Create a campaign first to start scanning.
                </p>
                <Link href="/campaigns">
                  <Button>
                    <Megaphone className="mr-2 h-4 w-4" />
                    Create Campaign
                  </Button>
                </Link>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {campaigns.map((campaign: Campaign) => (
                  <Link key={campaign.id} href={`/campaigns/${campaign.id}?tab=scans`}>
                    <div className="group p-4 rounded-lg border bg-card hover:border-primary hover:bg-primary/5 transition-all cursor-pointer">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="font-medium group-hover:text-primary transition-colors">
                            {campaign.name}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            {campaign.asset_count} assets to scan for
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <Play className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
                        </div>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Batch Scan */}
        {canBatchScan && (
          <Card className="border-border/60 opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center bg-primary/10 border border-primary/20">
                    <Layers className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-medium">Batch Scan</p>
                    <p className="text-xs text-muted-foreground">
                      Scan all dealers across every available channel at once
                    </p>
                  </div>
                </div>
                <Button
                  onClick={() => {
                    if (confirm("Start scanning all dealers across all channels? This will create one scan per channel.")) {
                      batchScanMutation.mutate();
                    }
                  }}
                  disabled={batchScanMutation.isPending}
                >
                  <Layers className="mr-2 h-4 w-4" />
                  {batchScanMutation.isPending ? "Starting..." : "Scan All Channels"}
                </Button>
              </div>
              {batchScanMutation.isSuccess && batchScanMutation.data && (
                <p className="text-xs text-success mt-2">
                  {batchScanMutation.data.message}
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Scan Jobs List */}
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">All Scan History</h2>
          <div className="flex items-center gap-2">
            {scanJobs.length > 0 && (
              <Button 
                variant="outline" 
                size="sm" 
                onClick={handleDeleteAllScans}
                disabled={deleteAllScansMutation.isPending}
                className="text-red-400 hover:text-red-300 hover:border-red-400"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete All
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={handleRefresh}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Refresh
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Card key={i} className="animate-pulse">
                <CardContent className="p-6">
                  <div className="h-6 bg-muted rounded w-1/4 mb-2" />
                  <div className="h-4 bg-muted rounded w-1/2" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : scanJobs.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Radar className="h-12 w-12 text-muted-foreground mb-4" />
              <h3 className="text-lg font-medium">No scans yet</h3>
              <p className="text-muted-foreground mt-1">
                Select a campaign above to start your first scan
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {scanJobs.map((job: ScanJob) => (
              <Card key={job.id}>
                <CardContent className="p-6">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      {statusIcons[job.status]}
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="font-semibold">
                            {sourceLabels[job.source] || job.source}
                          </h3>
                          <Badge className={statusColors[job.status]}>
                            {job.status}
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">
                          {job.started_at
                            ? `Started ${formatDateTime(job.started_at)}`
                            : `Created ${formatDateTime(job.created_at)}`}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-sm font-medium">
                          {job.matches_count ?? 0} matches found
                        </p>
                        {job.pipeline_stats && (job.pipeline_stats.matched_confirmed > 0 || job.pipeline_stats.drift_detected > 0) ? (
                          <p className="text-xs text-muted-foreground">
                            {job.pipeline_stats.matched_new ?? 0} new, {job.pipeline_stats.matched_confirmed} confirmed
                            {job.pipeline_stats.drift_detected > 0 && (
                              <span className="text-amber-400 ml-1">
                                ({job.pipeline_stats.drift_detected} drift)
                              </span>
                            )}
                          </p>
                        ) : (
                          <p className="text-xs text-muted-foreground">
                            {job.total_items} images scanned
                          </p>
                        )}
                      </div>

                      {job.campaign_id && (
                        <Link href={`/campaigns/${job.campaign_id}?tab=results`}>
                          <Button size="sm" variant="outline">
                            <Eye className="h-3 w-3 mr-1" />
                            View Results
                          </Button>
                        </Link>
                      )}
                      
                      <Button 
                        size="sm" 
                        variant="ghost"
                        onClick={() => handleDeleteScan(job.id)}
                        disabled={deleteScanMutation.isPending}
                        className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>

                  {job.status === "failed" && (
                    <div className="mt-3 border border-red-500/20 bg-red-500/5 p-3 space-y-2">
                      <div className="flex items-start gap-2">
                        <XCircle className="h-4 w-4 text-red-400 mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-red-400">Scan failed</p>
                          {job.error_message && (
                            <p className="text-xs text-muted-foreground mt-1 break-words">
                              {job.error_message}
                            </p>
                          )}
                          <p className="text-xs text-muted-foreground mt-1.5">
                            {job.error_message?.toLowerCase().includes("timeout")
                              ? "The scan timed out. Try scanning fewer dealers or a different channel."
                              : job.error_message?.toLowerCase().includes("rate")
                              ? "API rate limit hit. Wait a few minutes and retry."
                              : job.error_message?.toLowerCase().includes("url") || job.error_message?.toLowerCase().includes("404")
                              ? "A dealer URL may be invalid. Check your distributor settings."
                              : "Check your campaign assets and dealer URLs, then retry."}
                          </p>
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          className="flex-shrink-0 text-xs"
                          onClick={() => retryScanMutation.mutate(job.id)}
                          disabled={retryScanMutation.isPending}
                        >
                          <RefreshCw className={`h-3 w-3 mr-1 ${retryScanMutation.isPending ? "animate-spin" : ""}`} />
                          {retryScanMutation.isPending ? "Retrying..." : "Retry"}
                        </Button>
                      </div>
                    </div>
                  )}

                  {job.pipeline_stats && (
                    <div className="mt-3">
                      <button
                        onClick={() => toggleExpanded(job.id)}
                        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <BarChart3 className="h-3.5 w-3.5" />
                        Pipeline Funnel
                        {expandedJobs.has(job.id) ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                      </button>

                      {expandedJobs.has(job.id) && (
                        <PipelineFunnel stats={job.pipeline_stats} />
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
