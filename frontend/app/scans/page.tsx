"use client";

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
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useScanJobs, useCampaigns, useDeleteScan, useDeleteAllScans } from "@/lib/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { formatDateTime } from "@/lib/utils";

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
  created_at: string;
}

interface Campaign {
  id: string;
  name: string;
  status: string;
  asset_count: number;
}

export default function ScansPage() {
  const { data: scanJobs = [], isLoading: loading } = useScanJobs();
  const { data: allCampaigns = [] } = useCampaigns();
  const queryClient = useQueryClient();
  const deleteScanMutation = useDeleteScan();
  const deleteAllScansMutation = useDeleteAllScans();
  
  const campaigns = allCampaigns.filter((c: Campaign) => c.status === "active");

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["scans"] });
  };

  const handleDeleteScan = async (id: string) => {
    if (confirm("Delete this scan and all its results?")) {
      try {
        await deleteScanMutation.mutateAsync(id);
      } catch (error) {
        console.error("Failed to delete scan:", error);
      }
    }
  };

  const handleDeleteAllScans = async () => {
    if (confirm("Delete ALL scans and results? This cannot be undone.")) {
      try {
        await deleteAllScansMutation.mutateAsync();
      } catch (error) {
        console.error("Failed to delete all scans:", error);
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
                        <p className="text-xs text-muted-foreground">
                          {job.total_items} images scanned
                        </p>
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

                  {job.error_message && (
                    <p className="mt-3 text-sm text-red-400 bg-red-500/10 rounded p-2">
                      {job.error_message}
                    </p>
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
