"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Image from "next/image";
import { 
  Upload, 
  ImageIcon, 
  Trash2 as TrashIcon, 
  ArrowLeft, 
  Radar,
  Play,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  Eye,
  ExternalLink,
  Loader2,
  Sparkles,
  Download,
  CalendarClock,
  Plus,
  Power,
  PowerOff
} from "lucide-react";
import Link from "next/link";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  getCampaign, 
  getCampaignAssets, 
  uploadAsset,
  deleteAsset, 
  deleteCampaign,
  startCampaignScan,
  getCampaignScans,
  getCampaignMatches,
  getCampaignScanStats,
  getCampaignScan,
  downloadComplianceReport,
  getSchedules,
  createSchedule,
  updateSchedule,
  deleteSchedule,
  ScanSchedule,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";

interface Asset {
  id: string;
  name: string;
  file_url: string;
  file_type: string | null;
  file_size: number | null;
  thumbnail_url: string | null;
  width: number | null;
  height: number | null;
  metadata: Record<string, unknown>;
  campaign_id: string;
  created_at: string;
  updated_at: string;
}

interface Campaign {
  id: string;
  name: string;
  description: string | null;
  status: string;
  asset_count: number;
}

interface ScanJob {
  id: string;
  status: string;
  source: string;
  started_at: string | null;
  completed_at: string | null;
  total_items: number;
  processed_items: number;
  matches_count: number;
  error_message: string | null;
  pipeline_stats: Record<string, unknown> | null;
  organization_id: string;
  campaign_id: string | null;
  apify_run_id: string | null;
  created_at: string;
}

interface Match {
  id: string;
  asset_name: string | null;
  asset_url: string | null;
  distributor_name: string | null;
  confidence_score: number;
  match_type: string;
  compliance_status: string;
  previous_compliance_status: string | null;
  source_url: string | null;
  channel: string | null;
  created_at: string;
  last_seen_at: string | null;
  scan_count: number;
}

interface ScanStats {
  total_scans: number;
  completed_scans: number;
  running_scans?: number;
  failed_scans?: number;
  total_matches: number;
  violations?: number;
  compliant?: number;
  pending_review?: number;
  last_scan?: ScanJob;
}

const SCAN_SOURCES = [
  { value: "google_ads", label: "Google Ads", logo: "/logos/google.svg", desc: "Paid display ads" },
  { value: "facebook", label: "Facebook Ads", logo: "/logos/meta.png", desc: "Meta Ad Library" },
  { value: "instagram", label: "Instagram", logo: "/logos/instagram.svg", desc: "Organic posts" },
  { value: "website", label: "Websites", logo: "/logos/www.svg?v=2", desc: "Dealer sites" },
];

export default function CampaignDetailPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const campaignId = params.id as string;
  const initialTab = searchParams.get("tab") || "assets";
  
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [scans, setScans] = useState<ScanJob[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [scanStats, setScanStats] = useState<ScanStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState(initialTab);
  const [pollingScanId, setPollingScanId] = useState<string | null>(null);
  const [deletingAssetId, setDeletingAssetId] = useState<string | null>(null);
  const [downloadingReport, setDownloadingReport] = useState<string | null>(null);
  const pollingInterval = useRef<NodeJS.Timeout | null>(null);

  // Schedule state
  const [schedules, setSchedules] = useState<ScanSchedule[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [newSchedSource, setNewSchedSource] = useState("website");
  const [newSchedFreq, setNewSchedFreq] = useState("weekly");
  const [newSchedTime, setNewSchedTime] = useState("09:00");
  const [newSchedDay, setNewSchedDay] = useState<number>(0);
  const [creatingSched, setCreatingSched] = useState(false);

  const DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

  const loadSchedules = async () => {
    setScheduleLoading(true);
    try {
      const data = await getSchedules(campaignId);
      setSchedules(data);
    } catch { /* table may not exist yet */ }
    finally { setScheduleLoading(false); }
  };

  const handleCreateSchedule = async () => {
    setCreatingSched(true);
    try {
      const dayVal = (newSchedFreq === "weekly" || newSchedFreq === "biweekly") ? newSchedDay : undefined;
      await createSchedule(campaignId, newSchedSource, newSchedFreq, newSchedTime, dayVal);
      await loadSchedules();
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to create schedule");
    } finally { setCreatingSched(false); }
  };

  const handleToggleSchedule = async (s: ScanSchedule) => {
    try {
      await updateSchedule(s.id, { is_active: !s.is_active });
      await loadSchedules();
    } catch { /* ignore */ }
  };

  const handleDeleteSchedule = async (id: string) => {
    try {
      await deleteSchedule(id);
      setSchedules((prev) => prev.filter((s) => s.id !== id));
    } catch { /* ignore */ }
  };

  const handleDownloadReport = async (format: "pdf" | "csv") => {
    setDownloadingReport(format);
    try {
      await downloadComplianceReport(format, { campaign_id: campaignId });
    } catch (error: any) {
      console.error("Download failed:", error);
      alert(error?.response?.data?.detail || "Report download failed. Please try again.");
    } finally {
      setDownloadingReport(null);
    }
  };

  useEffect(() => {
    loadCampaign();
    
    // Cleanup polling on unmount
    return () => {
      if (pollingInterval.current) {
        clearInterval(pollingInterval.current);
      }
    };
  }, [campaignId]);

  useEffect(() => {
    if (activeTab === "scans") {
      loadScans();
    } else if (activeTab === "results") {
      loadMatches();
    } else if (activeTab === "schedules") {
      loadSchedules();
    }
  }, [activeTab, campaignId]);

  // Poll for scan status when a scan is running or analyzing
  useEffect(() => {
    if (pollingScanId) {
      pollingInterval.current = setInterval(async () => {
        try {
          const scanData = await getCampaignScan(campaignId, pollingScanId);
          if (scanData.status === "completed" || scanData.status === "failed") {
            setPollingScanId(null);
            if (pollingInterval.current) {
              clearInterval(pollingInterval.current);
            }
            // Refresh all data
            await Promise.all([loadScans(), loadCampaign(), loadMatches()]);
          } else {
            // Still running or analyzing - just refresh scans list
            await loadScans();
          }
        } catch (error) {
          console.error("Polling error:", error);
        }
      }, 3000); // Poll every 3 seconds for better responsiveness
    }
    
    return () => {
      if (pollingInterval.current) {
        clearInterval(pollingInterval.current);
      }
    };
  }, [pollingScanId, campaignId]);

  const loadCampaign = async () => {
    try {
      const [campaignData, assetsData, statsData] = await Promise.all([
        getCampaign(campaignId),
        getCampaignAssets(campaignId),
        getCampaignScanStats(campaignId),
      ]);
      setCampaign(campaignData);
      setAssets(assetsData);
      setScanStats(statsData);
    } catch (error) {
      console.error("Failed to load campaign:", error);
    } finally {
      setLoading(false);
    }
  };

  const loadScans = async () => {
    try {
      const scansData = await getCampaignScans(campaignId);
      setScans(scansData);
    } catch (error) {
      console.error("Failed to load scans:", error);
    }
  };

  const loadMatches = async () => {
    try {
      const matchesData = await getCampaignMatches(campaignId);
      setMatches(matchesData);
    } catch (error) {
      console.error("Failed to load matches:", error);
    }
  };

  const handleStartScan = async (source: string) => {
    if (assets.length === 0) {
      alert("Please upload at least one asset before starting a scan.");
      return;
    }

    setScanning(true);
    setSelectedSource(source);
    try {
      const scanJob = await startCampaignScan(campaignId, source);
      // Start polling for this scan
      setPollingScanId(scanJob.id);
      // Refresh scans and stats
      await Promise.all([loadScans(), loadCampaign()]);
      setActiveTab("scans");
    } catch (error) {
      console.error("Failed to start scan:", error);
      alert("Failed to start scan. Please try again.");
    } finally {
      setScanning(false);
      setSelectedSource(null);
    }
  };

  const handleUpload = async (files: FileList) => {
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        if (file.type.startsWith("image/")) {
          await uploadAsset(campaignId, file);
        }
      }
      await loadCampaign();
    } catch (error: any) {
      console.error("Upload failed:", error);
      const errorMessage = error?.response?.data?.detail || error?.message || "Unknown error occurred";
      alert(`Upload failed: ${errorMessage}`);
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteAsset = async (assetId: string) => {
    setDeletingAssetId(assetId);
    try {
      await deleteAsset(assetId);
      // Refresh assets list
      loadCampaign();
    } catch (error: any) {
      console.error("Failed to delete asset:", error);
      alert(error?.response?.data?.detail || "Failed to delete asset.");
    } finally {
      setDeletingAssetId(null);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files) {
      handleUpload(e.dataTransfer.files);
    }
  }, [campaignId]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteCampaign(campaignId);
      router.push("/campaigns");
    } catch (error: any) {
      console.error("Failed to delete campaign:", error);
      alert(error?.response?.data?.detail || "Failed to delete campaign.");
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle2 className="h-4 w-4 text-green-500" />;
      case "running":
        return <RefreshCw className="h-4 w-4 text-blue-500 animate-spin" />;
      case "analyzing":
        return <Sparkles className="h-4 w-4 text-purple-500 animate-pulse" />;
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500" />;
      default:
        return <Clock className="h-4 w-4 text-yellow-500" />;
    }
  };

  const getComplianceBadge = (status: string) => {
    switch (status) {
      case "compliant":
        return <Badge className="bg-green-500/10 text-green-500 border-green-500/20">Compliant</Badge>;
      case "violation":
        return <Badge className="bg-red-500/10 text-red-500 border-red-500/20">Violation</Badge>;
      case "review":
        return <Badge className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">Review</Badge>;
      default:
        return <Badge variant="secondary">Pending</Badge>;
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen">
        <Header title="Loading..." />
        <div className="p-6">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-muted rounded w-1/3" />
            <div className="h-4 bg-muted rounded w-1/2" />
          </div>
        </div>
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="min-h-screen">
        <Header title="Campaign Not Found" />
        <div className="p-6">
          <p>The campaign you're looking for doesn't exist.</p>
          <Link href="/campaigns">
            <Button className="mt-4">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Campaigns
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Header
        title={campaign.name}
        description={campaign.description || "Campaign assets and monitoring"}
      />

      <div className="p-6 space-y-6">
        {/* Back Button */}
        <Link href="/campaigns">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Campaigns
          </Button>
        </Link>

        {/* Campaign Info */}
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <Badge className="mb-2">
                  {campaign.status}
                </Badge>
                <h2 className="text-2xl font-bold">{campaign.name}</h2>
                {campaign.description && (
                  <p className="text-muted-foreground mt-1">{campaign.description}</p>
                )}
              </div>
              <div className="flex items-center gap-6">
                <div className="text-right">
                  <p className="text-3xl font-bold">{assets.length}</p>
                  <p className="text-muted-foreground">Assets</p>
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  <TrashIcon className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* Scan Stats */}
            {scanStats && (
              <div className="mt-6 grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-4 rounded-lg bg-muted/50">
                  <div className="flex items-center gap-2">
                    <Radar className="h-4 w-4 text-blue-500" />
                    <span className="text-sm text-muted-foreground">Total Scans</span>
                  </div>
                  <p className="text-2xl font-bold mt-1">{scanStats.total_scans}</p>
                </div>
                <div className="p-4 rounded-lg bg-muted/50">
                  <div className="flex items-center gap-2">
                    <Eye className="h-4 w-4 text-purple-500" />
                    <span className="text-sm text-muted-foreground">Matches Found</span>
                  </div>
                  <p className="text-2xl font-bold mt-1">{scanStats.total_matches}</p>
                </div>
                <div className="p-4 rounded-lg bg-muted/50">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                    <span className="text-sm text-muted-foreground">Compliant</span>
                  </div>
                  <p className="text-2xl font-bold mt-1">{scanStats.compliant}</p>
                </div>
                <div className="p-4 rounded-lg bg-muted/50">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-red-500" />
                    <span className="text-sm text-muted-foreground">Violations</span>
                  </div>
                  <p className="text-2xl font-bold mt-1">{scanStats.violations}</p>
                </div>
              </div>
            )}

            {/* Delete Confirmation */}
            {showDeleteConfirm && (
              <div className="mt-4 p-4 rounded-lg border border-destructive/50 bg-destructive/10">
                <p className="font-medium text-destructive">Delete this campaign?</p>
                <p className="text-sm text-muted-foreground mt-1">
                  This will permanently delete the campaign and all its assets. This action cannot be undone.
                </p>
                <div className="flex gap-2 mt-3">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? "Deleting..." : "Yes, Delete Campaign"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowDeleteConfirm(false)}
                    disabled={deleting}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="assets" className="flex items-center gap-2">
              <ImageIcon className="h-4 w-4" />
              Assets ({assets.length})
            </TabsTrigger>
            <TabsTrigger value="scans" className="flex items-center gap-2">
              <Radar className="h-4 w-4" />
              Scans ({scanStats?.total_scans || 0})
            </TabsTrigger>
            <TabsTrigger value="results" className="flex items-center gap-2">
              <Eye className="h-4 w-4" />
              Results ({scanStats?.total_matches || 0})
            </TabsTrigger>
            <TabsTrigger value="schedules" className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4" />
              Schedules
            </TabsTrigger>
          </TabsList>

          {/* Assets Tab */}
          <TabsContent value="assets" className="space-y-4">
            {/* Upload Area */}
            <Card>
              <CardHeader>
                <CardTitle>Upload Assets</CardTitle>
                <CardDescription>
                  Upload your approved campaign creative. These will be used to match against distributor ads.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div
                  className={`relative border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                    dragOver
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50"
                  }`}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                >
                  <Upload className="h-10 w-10 mx-auto text-muted-foreground mb-4" />
                  <p className="font-medium">
                    {uploading ? "Uploading..." : "Drag and drop assets here"}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    or click to select files
                  </p>
                  <label className="relative inline-block">
                    <Button className="mt-4" disabled={uploading} type="button">
                      Select Files
                    </Button>
                    <input
                      type="file"
                      multiple
                      accept="image/*"
                      className="absolute inset-0 opacity-0 cursor-pointer"
                      onChange={(e) => {
                        if (e.target.files) {
                          handleUpload(e.target.files);
                          e.target.value = ""; // Reset input to allow re-uploading same file
                        }
                      }}
                    />
                  </label>
                </div>
              </CardContent>
            </Card>

            {/* Assets Grid */}
            <div>
              <h3 className="text-lg font-semibold mb-4">
                Campaign Assets ({assets.length})
              </h3>
              
              {assets.length === 0 ? (
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-12">
                    <ImageIcon className="h-12 w-12 text-muted-foreground mb-4" />
                    <p className="text-muted-foreground">
                      No assets uploaded yet. Upload your first asset above.
                    </p>
                  </CardContent>
                </Card>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
                  {assets.map((asset) => (
                    <Card key={asset.id} className="overflow-hidden group">
                      <div className="relative aspect-video bg-muted">
                        <Image
                          src={asset.file_url}
                          alt={asset.name}
                          fill
                          className="object-cover"
                        />
                        <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                          <Button 
                            variant="destructive" 
                            size="icon"
                            onClick={() => handleDeleteAsset(asset.id)}
                            disabled={deletingAssetId === asset.id}
                          >
                            {deletingAssetId === asset.id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <TrashIcon className="h-4 w-4" />
                            )}
                          </Button>
                        </div>
                      </div>
                      <CardContent className="p-3">
                        <p className="font-medium text-sm truncate">{asset.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(asset.created_at)}
                        </p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          </TabsContent>

          {/* Scans Tab */}
          <TabsContent value="scans" className="space-y-4">
            {/* Start Scan Section */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Radar className="h-5 w-5" />
                  Start a Scan
                </CardTitle>
                <CardDescription>
                  Scan distributor channels to find where your campaign assets are being used.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {assets.length === 0 ? (
                  <div className="text-center py-6">
                    <AlertTriangle className="h-10 w-10 text-yellow-500 mx-auto mb-3" />
                    <p className="font-medium">No assets to scan for</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      Upload at least one asset before starting a scan.
                    </p>
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {SCAN_SOURCES.map((source) => (
                      <Button
                        key={source.value}
                        variant="outline"
                        className="h-auto py-4 flex flex-col items-center gap-2 hover:border-primary hover:bg-primary/5"
                        onClick={() => handleStartScan(source.value)}
                        disabled={scanning}
                      >
                        <img src={source.logo} alt={source.label} className="h-8 w-8 object-contain" />
                        <span className="font-medium">{source.label}</span>
                        <span className="text-2xs text-muted-foreground">{source.desc}</span>
                        {scanning && selectedSource === source.value && (
                          <RefreshCw className="h-4 w-4 animate-spin" />
                        )}
                      </Button>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Scan History */}
            <Card>
              <CardHeader>
                <CardTitle>Scan History</CardTitle>
                <CardDescription>
                  View past scans and their results
                </CardDescription>
              </CardHeader>
              <CardContent>
                {scans.length === 0 ? (
                  <div className="text-center py-8">
                    <Radar className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
                    <p className="text-muted-foreground">No scans yet</p>
                    <p className="text-sm text-muted-foreground">
                      Start your first scan above to find your assets in the wild.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {scans.map((scan) => (
                      <div
                        key={scan.id}
                        className={`flex items-center justify-between p-4 rounded-lg border bg-card ${
                          scan.status === "running" ? "border-blue-500/50 bg-blue-500/5" : ""
                        }`}
                      >
                        <div className="flex items-center gap-4">
                          {getStatusIcon(scan.status)}
                          <div>
                            <p className="font-medium capitalize">
                              {scan.source.replace("_", " ")} Scan
                            </p>
                            <p className="text-sm text-muted-foreground">
                              {formatDate(scan.created_at)}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          {scan.status === "running" && (
                            <div className="flex items-center gap-2 text-sm text-blue-500">
                              <Loader2 className="h-3 w-3 animate-spin" />
                              <span>Scanning websites...</span>
                            </div>
                          )}
                          {scan.status === "analyzing" && (
                            <div className="flex items-center gap-2 text-sm text-purple-500">
                              <Sparkles className="h-3 w-3 animate-pulse" />
                              <span>Analyzing images with AI...</span>
                            </div>
                          )}
                          {scan.status === "completed" && scan.total_items > 0 && (
                            <div className="text-right text-sm">
                              <p className="font-medium">{scan.total_items} items found</p>
                              {scan.processed_items > 0 && (
                                <p className="text-muted-foreground">{scan.processed_items} analyzed</p>
                              )}
                            </div>
                          )}
                          <Badge variant={
                            scan.status === "completed" ? "default" :
                            scan.status === "running" ? "secondary" :
                            scan.status === "analyzing" ? "secondary" :
                            scan.status === "failed" ? "destructive" : "outline"
                          }>
                            {scan.status}
                          </Badge>
                          {scan.status === "completed" && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                setActiveTab("results");
                                loadMatches();
                              }}
                            >
                              <Eye className="h-3 w-3 mr-1" />
                              View Results
                            </Button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Results Tab */}
          <TabsContent value="results" className="space-y-4">
            <Card>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <Eye className="h-5 w-5" />
                      Scan Results
                    </CardTitle>
                    <CardDescription className="mt-1">
                      Matches found between your campaign assets and distributor ads
                    </CardDescription>
                  </div>
                  {matches.length > 0 && (
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDownloadReport("pdf")}
                        disabled={downloadingReport !== null}
                      >
                        <Download className="mr-1.5 h-3.5 w-3.5" />
                        {downloadingReport === "pdf" ? "..." : "PDF"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDownloadReport("csv")}
                        disabled={downloadingReport !== null}
                      >
                        <Download className="mr-1.5 h-3.5 w-3.5" />
                        {downloadingReport === "csv" ? "..." : "CSV"}
                      </Button>
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {matches.length === 0 ? (
                  <div className="text-center py-8">
                    <Eye className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
                    <p className="text-muted-foreground">No matches found yet</p>
                    <p className="text-sm text-muted-foreground">
                      Run a scan and analyze results to find matches.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {matches.map((match) => (
                      <div
                        key={match.id}
                        className="flex items-start gap-4 p-4 rounded-lg border bg-card"
                      >
                        {match.asset_url && (
                          <div className="relative w-20 h-20 rounded overflow-hidden shrink-0">
                            <Image
                              src={match.asset_url}
                              alt={match.asset_name || "Asset"}
                              fill
                              className="object-cover"
                            />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="font-medium">
                                {match.asset_name || "Unknown Asset"}
                              </p>
                              <p className="text-sm text-muted-foreground">
                                Found at: {match.distributor_name || "Unknown Distributor"}
                              </p>
                            </div>
                            {getComplianceBadge(match.compliance_status)}
                          </div>
                          <div className="flex items-center gap-4 mt-2 text-sm">
                            <span className="text-muted-foreground">
                              Confidence: <span className="font-medium text-foreground">
                                {match.confidence_score.toFixed(0)}%
                              </span>
                            </span>
                            <Badge variant="outline" className="capitalize">
                              {match.match_type}
                            </Badge>
                            {match.channel && (
                              <Badge variant="secondary" className="capitalize">
                                {match.channel.replace("_", " ")}
                              </Badge>
                            )}
                            {(match.scan_count ?? 0) > 1 && (
                              <span className="text-muted-foreground" title={`Last confirmed: ${match.last_seen_at ? new Date(match.last_seen_at).toLocaleDateString() : "unknown"}`}>
                                Seen {match.scan_count}x
                              </span>
                            )}
                            {match.previous_compliance_status && match.previous_compliance_status !== match.compliance_status && (
                              <Badge className="bg-amber-500/20 text-amber-400">
                                was {match.previous_compliance_status}
                              </Badge>
                            )}
                          </div>
                          {match.source_url && (
                            <a
                              href={match.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-sm text-primary hover:underline mt-2"
                            >
                              View Source <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Schedules Tab */}
          <TabsContent value="schedules" className="space-y-4">
            {/* Create new schedule */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Add Automated Scan</CardTitle>
                <CardDescription>Configure a recurring scan for this campaign</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap items-end gap-4">
                  <div className="space-y-1.5">
                    <label className="text-sm font-medium text-muted-foreground">Channel</label>
                    <select
                      value={newSchedSource}
                      onChange={(e) => setNewSchedSource(e.target.value)}
                      className="flex h-9 w-[160px] rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      {SCAN_SOURCES.map((s) => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-sm font-medium text-muted-foreground">Frequency</label>
                    <select
                      value={newSchedFreq}
                      onChange={(e) => setNewSchedFreq(e.target.value)}
                      className="flex h-9 w-[160px] rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      <option value="daily">Daily</option>
                      <option value="weekly">Weekly</option>
                      <option value="biweekly">Every 2 Weeks</option>
                      <option value="monthly">Monthly</option>
                    </select>
                  </div>

                  {(newSchedFreq === "weekly" || newSchedFreq === "biweekly") && (
                    <div className="space-y-1.5">
                      <label className="text-sm font-medium text-muted-foreground">Day</label>
                      <select
                        value={newSchedDay}
                        onChange={(e) => setNewSchedDay(Number(e.target.value))}
                        className="flex h-9 w-[140px] rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      >
                        {DAYS_OF_WEEK.map((d, i) => (
                          <option key={i} value={i}>{d}</option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <label className="text-sm font-medium text-muted-foreground">Time (UTC)</label>
                    <input
                      type="time"
                      value={newSchedTime}
                      onChange={(e) => setNewSchedTime(e.target.value)}
                      className="flex h-9 w-[120px] rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    />
                  </div>

                  <Button onClick={handleCreateSchedule} disabled={creatingSched} size="sm">
                    {creatingSched ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Plus className="h-4 w-4 mr-1" />}
                    Add Schedule
                  </Button>
                </div>
              </CardContent>
            </Card>

            {/* Active schedules */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Active Schedules</CardTitle>
              </CardHeader>
              <CardContent>
                {scheduleLoading ? (
                  <div className="flex justify-center py-8">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  </div>
                ) : schedules.length === 0 ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <CalendarClock className="h-10 w-10 mx-auto mb-3 opacity-50" />
                    <p className="font-medium">No schedules yet</p>
                    <p className="text-sm mt-1">Add an automated scan above to get started</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {schedules.map((s) => {
                      const sourceLabel = SCAN_SOURCES.find((x) => x.value === s.source)?.label || s.source;
                      const freqLabel = s.frequency === "biweekly" ? "Every 2 Weeks" : s.frequency.charAt(0).toUpperCase() + s.frequency.slice(1);
                      const timeLabel = s.run_at_time || "09:00";
                      const dayLabel = (s.frequency === "weekly" || s.frequency === "biweekly") && s.run_on_day != null
                        ? DAYS_OF_WEEK[s.run_on_day] + "s"
                        : null;
                      const schedDesc = dayLabel ? `${freqLabel} · ${dayLabel} at ${timeLabel} UTC` : `${freqLabel} at ${timeLabel} UTC`;
                      return (
                        <div
                          key={s.id}
                          className={`flex items-center justify-between rounded-lg border p-4 ${s.is_active ? "bg-card" : "bg-muted/40 opacity-70"}`}
                        >
                          <div className="flex items-center gap-4">
                            <div className={`h-2.5 w-2.5 rounded-full ${s.is_active ? "bg-green-500" : "bg-gray-400"}`} />
                            <div>
                              <p className="font-medium text-sm">{sourceLabel}</p>
                              <p className="text-xs text-muted-foreground">{schedDesc}</p>
                            </div>
                          </div>

                          <div className="flex items-center gap-6 text-xs text-muted-foreground">
                            {s.last_run_at && (
                              <span>Last run: {formatDate(s.last_run_at)}</span>
                            )}
                            {s.next_run_at && s.is_active && (
                              <span>Next: {formatDate(s.next_run_at)}</span>
                            )}
                          </div>

                          <div className="flex items-center gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleToggleSchedule(s)}
                              title={s.is_active ? "Pause" : "Resume"}
                            >
                              {s.is_active ? <PowerOff className="h-4 w-4 text-amber-500" /> : <Power className="h-4 w-4 text-green-500" />}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDeleteSchedule(s.id)}
                              title="Delete"
                            >
                              <TrashIcon className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
