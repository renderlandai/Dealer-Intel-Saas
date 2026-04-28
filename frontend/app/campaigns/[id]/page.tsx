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
  PowerOff,
  Layers,
  Users,
  Search,
  X
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
  updateAsset,
  deleteAsset,
  deleteCampaign,
  startCampaignScan,
  startCampaignBatchScan,
  getCampaignScans,
  getCampaignMatches,
  getCampaignScanStats,
  getCampaignScan,
  downloadComplianceReport,
  getSchedules,
  createSchedule,
  updateSchedule,
  deleteSchedule,
  getDistributors,
  ScanSchedule,
  ALL_TARGET_PLATFORMS,
  TARGET_PLATFORM_LABELS,
  type TargetPlatform,
  type Distributor,
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
  target_platforms: TargetPlatform[];
  campaign_id: string;
  created_at: string;
  updated_at: string;
}

// A creative that has been chosen via drop/file-picker but not yet POSTed.
// previewUrl comes from URL.createObjectURL and MUST be revoked when the row
// is removed or after a successful upload to avoid leaking blob memory.
interface PendingUpload {
  id: string;
  file: File;
  previewUrl: string;
  platforms: TargetPlatform[];
  status: "queued" | "uploading" | "error";
  error?: string;
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
  const [scanningAll, setScanningAll] = useState(false);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  // Dealer selector for the Scans tab. Empty selection = scan every active
  // dealer (matches backend default). The selection persists per-campaign in
  // localStorage so a user running repeated scans doesn't re-tick boxes.
  const [distributors, setDistributors] = useState<Distributor[]>([]);
  const [distributorsLoading, setDistributorsLoading] = useState(false);
  const [selectedDealerIds, setSelectedDealerIds] = useState<string[]>([]);
  const [dealerSearch, setDealerSearch] = useState("");
  const [dealerPickerOpen, setDealerPickerOpen] = useState(false);
  const [activeTab, setActiveTab] = useState(initialTab);
  const [pollingScanId, setPollingScanId] = useState<string | null>(null);
  const [deletingAssetId, setDeletingAssetId] = useState<string | null>(null);
  const [downloadingReport, setDownloadingReport] = useState<string | null>(null);
  // Default channels seeded on every newly-staged upload row. Users can edit
  // each row independently before committing. Empty = "all channels".
  const [uploadPlatforms, setUploadPlatforms] = useState<TargetPlatform[]>([]);
  // Files staged for upload but not yet committed. Each row owns its own
  // platform tags so a single batch can ship one creative as IG-only and
  // another as Website+Facebook in one go.
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const [committingUploads, setCommittingUploads] = useState(false);
  // Per-asset inline editor state (asset id whose platform editor is open).
  const [editingAssetId, setEditingAssetId] = useState<string | null>(null);
  const [editingPlatforms, setEditingPlatforms] = useState<TargetPlatform[]>([]);
  const [savingAssetEdits, setSavingAssetEdits] = useState(false);
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

  // Revoke any object URLs left in the staging queue when the page unmounts.
  // We mirror the queue into a ref so the unmount cleanup can read the latest
  // value without re-running on every state change.
  const pendingUploadsRef = useRef<PendingUpload[]>([]);
  useEffect(() => {
    pendingUploadsRef.current = pendingUploads;
  }, [pendingUploads]);
  useEffect(() => {
    return () => {
      pendingUploadsRef.current.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
  }, []);

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
      loadDistributors();
    } else if (activeTab === "results") {
      loadMatches();
    } else if (activeTab === "schedules") {
      loadSchedules();
    }
  }, [activeTab, campaignId]);

  // Restore the dealer selection saved for this campaign (if any).
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(`campaign:${campaignId}:dealers`);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.every((x) => typeof x === "string")) {
        setSelectedDealerIds(parsed);
      }
    } catch { /* ignore corrupt entries */ }
  }, [campaignId]);

  // Persist the dealer selection. We intentionally write the empty list too
  // so "explicitly cleared" survives reloads instead of falling back to the
  // last non-empty value.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(
        `campaign:${campaignId}:dealers`,
        JSON.stringify(selectedDealerIds),
      );
    } catch { /* quota / private mode — non-fatal */ }
  }, [campaignId, selectedDealerIds]);

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

  const loadDistributors = async () => {
    setDistributorsLoading(true);
    try {
      const data = await getDistributors();
      setDistributors(data);
      // Drop stale selections (deleted dealers, dealers from another org).
      setSelectedDealerIds((prev) => {
        const valid = new Set(data.map((d) => d.id));
        const next = prev.filter((id) => valid.has(id));
        return next.length === prev.length ? prev : next;
      });
    } catch (error) {
      console.error("Failed to load dealers:", error);
    } finally {
      setDistributorsLoading(false);
    }
  };

  const toggleDealer = (id: string) => {
    setSelectedDealerIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const filteredDealers = distributors.filter((d) => {
    if (!dealerSearch.trim()) return true;
    const q = dealerSearch.trim().toLowerCase();
    return (
      d.name.toLowerCase().includes(q) ||
      (d.code ?? "").toLowerCase().includes(q) ||
      (d.region ?? "").toLowerCase().includes(q)
    );
  });

  const selectAllVisible = () => {
    setSelectedDealerIds((prev) => {
      const next = new Set(prev);
      filteredDealers.forEach((d) => next.add(d.id));
      return Array.from(next);
    });
  };

  const clearDealerSelection = () => setSelectedDealerIds([]);

  // How many dealers a given channel will actually hit, given the current
  // dealer selection. Mirrors the URL-availability checks in the backend
  // dispatch (e.g. Instagram skips dealers without `instagram_url`).
  const dealersForChannel = (channel: string): number => {
    const pool = selectedDealerIds.length === 0
      ? distributors.filter((d) => d.status === "active")
      : distributors.filter((d) => selectedDealerIds.includes(d.id));
    switch (channel) {
      case "google_ads":
        return pool.length;
      case "instagram":
        return pool.filter((d) => !!d.instagram_url).length;
      case "facebook":
        return pool.filter((d) => !!d.facebook_url).length;
      case "website":
        return pool.filter((d) => !!d.website_url).length;
      default:
        return pool.length;
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
      const scanJob = await startCampaignScan(
        campaignId,
        source,
        selectedDealerIds.length > 0 ? selectedDealerIds : undefined,
      );
      // Start polling for this scan
      setPollingScanId(scanJob.id);
      // Refresh scans and stats
      await Promise.all([loadScans(), loadCampaign()]);
      setActiveTab("scans");
    } catch (error: any) {
      console.error("Failed to start scan:", error);
      const detail = error?.response?.data?.detail;
      alert(detail || "Failed to start scan. Please try again.");
    } finally {
      setScanning(false);
      setSelectedSource(null);
    }
  };

  const handleScanAllChannels = async () => {
    if (assets.length === 0) {
      alert("Please upload at least one asset before starting a scan.");
      return;
    }

    setScanningAll(true);
    try {
      const result = await startCampaignBatchScan(
        campaignId,
        selectedDealerIds.length > 0 ? selectedDealerIds : undefined,
      );
      const jobs = result.jobs || [];

      if (jobs.length > 0) {
        setPollingScanId(jobs[0].id);
      }

      await Promise.all([loadScans(), loadCampaign()]);
      setActiveTab("scans");
    } catch (error: any) {
      console.error("Failed to start batch scan:", error);
      const detail = error?.response?.data?.detail;
      if (detail) {
        alert(detail);
      } else {
        alert("Failed to start scans. Please try again.");
      }
    } finally {
      setScanningAll(false);
    }
  };

  // Stage files locally without uploading. Each row inherits the current
  // global default but is independently editable below. We accept anything
  // that looks like an image OR has a .psd extension — browsers can't render
  // PSDs natively, so the row falls back to a placeholder and the backend
  // rasterizes the composite to PNG at upload time.
  const isAcceptedCreative = (f: File) =>
    f.type.startsWith("image/") || /\.psd$/i.test(f.name);
  const isPsdFile = (f: File) =>
    /\.psd$/i.test(f.name) ||
    f.type === "image/vnd.adobe.photoshop" ||
    f.type === "image/x-photoshop" ||
    f.type === "application/x-photoshop";

  const enqueueFiles = (files: FileList | File[]) => {
    const list = Array.from(files).filter(isAcceptedCreative);
    if (list.length === 0) return;
    setPendingUploads((prev) => [
      ...prev,
      ...list.map<PendingUpload>((file) => ({
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
        file,
        // PSDs can't be rendered by the browser; skip the blob URL.
        previewUrl: isPsdFile(file) ? "" : URL.createObjectURL(file),
        platforms: [...uploadPlatforms],
        status: "queued",
      })),
    ]);
  };

  const removePendingRow = (rowId: string) => {
    setPendingUploads((prev) => {
      const row = prev.find((p) => p.id === rowId);
      if (row) URL.revokeObjectURL(row.previewUrl);
      return prev.filter((p) => p.id !== rowId);
    });
  };

  const clearPendingUploads = () => {
    setPendingUploads((prev) => {
      prev.forEach((row) => URL.revokeObjectURL(row.previewUrl));
      return [];
    });
  };

  const togglePendingPlatform = (rowId: string, platform: TargetPlatform) => {
    setPendingUploads((prev) =>
      prev.map((p) => {
        if (p.id !== rowId) return p;
        const has = p.platforms.includes(platform);
        return {
          ...p,
          platforms: has ? p.platforms.filter((x) => x !== platform) : [...p.platforms, platform],
        };
      }),
    );
  };

  const applyDefaultToAllPending = () => {
    setPendingUploads((prev) =>
      prev.map((p) => (p.status === "uploading" ? p : { ...p, platforms: [...uploadPlatforms] })),
    );
  };

  const commitPendingUploads = async () => {
    if (pendingUploads.length === 0 || committingUploads) return;
    setCommittingUploads(true);
    setUploading(true);
    const succeededIds: string[] = [];
    try {
      for (const row of pendingUploads) {
        if (row.status === "uploading") continue;
        setPendingUploads((prev) =>
          prev.map((p) =>
            p.id === row.id ? { ...p, status: "uploading", error: undefined } : p,
          ),
        );
        try {
          await uploadAsset(campaignId, row.file, { targetPlatforms: row.platforms });
          succeededIds.push(row.id);
        } catch (e: any) {
          const errorMessage =
            e?.response?.data?.detail || e?.message || "Upload failed";
          setPendingUploads((prev) =>
            prev.map((p) =>
              p.id === row.id ? { ...p, status: "error", error: errorMessage } : p,
            ),
          );
        }
      }

      // Drop successful rows from the queue (and revoke their preview URLs).
      // Failed rows stay so the user can edit and retry.
      setPendingUploads((prev) => {
        const keep: PendingUpload[] = [];
        for (const p of prev) {
          if (succeededIds.includes(p.id)) {
            URL.revokeObjectURL(p.previewUrl);
          } else {
            keep.push(p);
          }
        }
        return keep;
      });

      if (succeededIds.length > 0) {
        await loadCampaign();
      }
    } finally {
      setCommittingUploads(false);
      setUploading(false);
    }
  };

  const toggleUploadPlatform = (platform: TargetPlatform) => {
    setUploadPlatforms((prev) =>
      prev.includes(platform) ? prev.filter((p) => p !== platform) : [...prev, platform],
    );
  };

  const openPlatformEditor = (asset: Asset) => {
    setEditingAssetId(asset.id);
    setEditingPlatforms(asset.target_platforms || []);
  };

  const closePlatformEditor = () => {
    setEditingAssetId(null);
    setEditingPlatforms([]);
  };

  const toggleEditingPlatform = (platform: TargetPlatform) => {
    setEditingPlatforms((prev) =>
      prev.includes(platform) ? prev.filter((p) => p !== platform) : [...prev, platform],
    );
  };

  const eligibleAssetsForSource = useCallback(
    (source: TargetPlatform | string) => {
      return assets.filter((a) => {
        const tags = a.target_platforms || [];
        return tags.length === 0 || tags.includes(source as TargetPlatform);
      }).length;
    },
    [assets],
  );

  const savePlatformEdits = async () => {
    if (!editingAssetId) return;
    setSavingAssetEdits(true);
    try {
      const updated = await updateAsset(editingAssetId, {
        target_platforms: editingPlatforms,
      });
      setAssets((prev) => prev.map((a) => (a.id === updated.id ? { ...a, ...updated } : a)));
      closePlatformEditor();
    } catch (error: any) {
      console.error("Failed to update asset platforms:", error);
      alert(error?.response?.data?.detail || "Failed to update channels.");
    } finally {
      setSavingAssetEdits(false);
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
      enqueueFiles(e.dataTransfer.files);
    }
    // enqueueFiles is intentionally not in the dep array — it closes over
    // uploadPlatforms by design (drops always inherit the current default).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId, uploadPlatforms]);

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
              <CardContent className="space-y-4">
                <div>
                  <p className="text-sm font-medium mb-2">
                    Default channels for new uploads
                  </p>
                  <p className="text-xs text-muted-foreground mb-3">
                    Each new file inherits this selection. You can edit channels per creative below before uploading.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {ALL_TARGET_PLATFORMS.map((platform) => {
                      const active = uploadPlatforms.includes(platform);
                      return (
                        <button
                          key={platform}
                          type="button"
                          onClick={() => toggleUploadPlatform(platform)}
                          className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                            active
                              ? "bg-primary text-primary-foreground border-primary"
                              : "bg-background hover:bg-muted border-border"
                          }`}
                        >
                          {TARGET_PLATFORM_LABELS[platform]}
                        </button>
                      );
                    })}
                    {uploadPlatforms.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setUploadPlatforms([])}
                        className="px-3 py-1.5 rounded-full text-sm text-muted-foreground hover:text-foreground"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

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
                    {committingUploads ? "Uploading..." : "Drag and drop creatives here"}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    or click to select files — you&apos;ll choose channels for each one before upload
                  </p>
                  <label className="relative inline-block">
                    <Button className="mt-4" disabled={committingUploads} type="button">
                      Select Files
                    </Button>
                    <input
                      type="file"
                      multiple
                      accept="image/*,.psd,image/vnd.adobe.photoshop"
                      className="absolute inset-0 opacity-0 cursor-pointer"
                      onChange={(e) => {
                        if (e.target.files) {
                          enqueueFiles(e.target.files);
                          e.target.value = ""; // Reset input to allow re-uploading same file
                        }
                      }}
                    />
                  </label>
                </div>

                {pendingUploads.length > 0 && (
                  <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium">
                        Ready to upload ({pendingUploads.length})
                      </p>
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-8 text-xs"
                          onClick={applyDefaultToAllPending}
                          disabled={committingUploads}
                          title="Set every queued row to the default channels above"
                        >
                          Apply default to all
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-8 text-xs text-muted-foreground"
                          onClick={clearPendingUploads}
                          disabled={committingUploads}
                        >
                          Clear all
                        </Button>
                      </div>
                    </div>

                    <ul className="space-y-2">
                      {pendingUploads.map((row) => (
                        <li
                          key={row.id}
                          className="flex flex-wrap gap-3 rounded-md border bg-background p-2"
                        >
                          <div className="relative h-16 w-16 flex-shrink-0 overflow-hidden rounded bg-muted">
                            {row.previewUrl ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={row.previewUrl}
                                alt={row.file.name}
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <div
                                className="flex h-full w-full flex-col items-center justify-center gap-0.5 bg-muted text-muted-foreground"
                                title="PSD will be flattened to PNG on upload"
                              >
                                <span className="text-[10px] font-semibold tracking-wide">PSD</span>
                                <span className="text-[8px] uppercase">flatten</span>
                              </div>
                            )}
                          </div>

                          <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <div className="flex items-center justify-between gap-2">
                              <p className="truncate text-sm font-medium" title={row.file.name}>
                                {row.file.name}
                              </p>
                              <button
                                type="button"
                                onClick={() => removePendingRow(row.id)}
                                disabled={row.status === "uploading"}
                                className="text-muted-foreground hover:text-destructive disabled:opacity-50"
                                title="Remove from queue"
                              >
                                <TrashIcon className="h-4 w-4" />
                              </button>
                            </div>

                            <div className="flex flex-wrap gap-1">
                              {ALL_TARGET_PLATFORMS.map((platform) => {
                                const active = row.platforms.includes(platform);
                                return (
                                  <button
                                    key={platform}
                                    type="button"
                                    onClick={() => togglePendingPlatform(row.id, platform)}
                                    disabled={row.status === "uploading"}
                                    className={`px-2 py-0.5 rounded-full text-[11px] border transition-colors disabled:opacity-50 ${
                                      active
                                        ? "bg-primary text-primary-foreground border-primary"
                                        : "bg-background hover:bg-muted border-border"
                                    }`}
                                  >
                                    {TARGET_PLATFORM_LABELS[platform]}
                                  </button>
                                );
                              })}
                              {row.platforms.length === 0 && (
                                <span className="self-center text-[11px] text-muted-foreground">
                                  All channels
                                </span>
                              )}
                            </div>

                            {row.status === "uploading" && (
                              <p className="flex items-center gap-1 text-xs text-blue-600">
                                <Loader2 className="h-3 w-3 animate-spin" />
                                Uploading…
                              </p>
                            )}
                            {row.status === "error" && (
                              <p className="text-xs text-destructive">
                                {row.error ?? "Upload failed. Edit channels and click Upload again."}
                              </p>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>

                    <div className="flex items-center justify-end gap-2">
                      <Button
                        type="button"
                        onClick={commitPendingUploads}
                        disabled={committingUploads}
                      >
                        {committingUploads ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Uploading…
                          </>
                        ) : (
                          `Upload ${pendingUploads.length} creative${pendingUploads.length === 1 ? "" : "s"}`
                        )}
                      </Button>
                    </div>
                  </div>
                )}
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
                  {assets.map((asset) => {
                    const platforms = asset.target_platforms || [];
                    const isEditing = editingAssetId === asset.id;
                    return (
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
                        <CardContent className="p-3 space-y-2">
                          <div>
                            <p className="font-medium text-sm truncate">{asset.name}</p>
                            <p className="text-xs text-muted-foreground">
                              {formatDate(asset.created_at)}
                            </p>
                          </div>

                          {isEditing ? (
                            <div className="space-y-2">
                              <div className="flex flex-wrap gap-1">
                                {ALL_TARGET_PLATFORMS.map((platform) => {
                                  const active = editingPlatforms.includes(platform);
                                  return (
                                    <button
                                      key={platform}
                                      type="button"
                                      onClick={() => toggleEditingPlatform(platform)}
                                      className={`px-2 py-0.5 rounded-full text-[11px] border transition-colors ${
                                        active
                                          ? "bg-primary text-primary-foreground border-primary"
                                          : "bg-background hover:bg-muted border-border"
                                      }`}
                                    >
                                      {TARGET_PLATFORM_LABELS[platform]}
                                    </button>
                                  );
                                })}
                              </div>
                              <div className="flex items-center gap-2">
                                <Button
                                  size="sm"
                                  className="h-7 px-2 text-xs"
                                  onClick={savePlatformEdits}
                                  disabled={savingAssetEdits}
                                >
                                  {savingAssetEdits ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    "Save"
                                  )}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-2 text-xs"
                                  onClick={closePlatformEditor}
                                  disabled={savingAssetEdits}
                                >
                                  Cancel
                                </Button>
                              </div>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => openPlatformEditor(asset)}
                              className="w-full text-left flex flex-wrap gap-1 hover:opacity-80"
                              title="Click to edit channels"
                            >
                              {platforms.length === 0 ? (
                                <Badge variant="outline" className="text-[11px]">
                                  All channels
                                </Badge>
                              ) : (
                                platforms.map((p) => (
                                  <Badge key={p} variant="secondary" className="text-[11px]">
                                    {TARGET_PLATFORM_LABELS[p] ?? p}
                                  </Badge>
                                ))
                              )}
                            </button>
                          )}
                        </CardContent>
                      </Card>
                    );
                  })}
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
                  <div className="space-y-4">
                    {/* Dealer selector */}
                    <div className="rounded-lg border bg-muted/30 p-3 space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <Users className="h-4 w-4 text-muted-foreground" />
                          <span className="text-sm font-medium">Dealers to scan</span>
                          <Badge variant="outline" className="text-[11px]">
                            {selectedDealerIds.length === 0
                              ? distributorsLoading
                                ? "Loading…"
                                : `All active (${distributors.filter((d) => d.status === "active").length})`
                              : `${selectedDealerIds.length} selected`}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2">
                          {selectedDealerIds.length > 0 && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={clearDealerSelection}
                            >
                              <X className="h-3 w-3 mr-1" />
                              Clear (use all)
                            </Button>
                          )}
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => setDealerPickerOpen((v) => !v)}
                            disabled={distributorsLoading || distributors.length === 0}
                          >
                            {dealerPickerOpen ? "Hide picker" : "Choose dealers"}
                          </Button>
                        </div>
                      </div>

                      {distributors.length === 0 && !distributorsLoading && (
                        <p className="text-xs text-muted-foreground">
                          No dealers found yet.{" "}
                          <Link href="/distributors" className="text-primary hover:underline">
                            Add dealers
                          </Link>{" "}
                          to start scanning.
                        </p>
                      )}

                      {dealerPickerOpen && distributors.length > 0 && (
                        <div className="space-y-2">
                          <div className="relative">
                            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                            <input
                              type="text"
                              value={dealerSearch}
                              onChange={(e) => setDealerSearch(e.target.value)}
                              placeholder="Search dealers by name, code, or region…"
                              className="flex h-8 w-full rounded-md border border-input bg-background pl-8 pr-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                            />
                          </div>
                          <div className="flex items-center justify-between text-xs text-muted-foreground">
                            <span>
                              {filteredDealers.length} of {distributors.length} shown
                            </span>
                            <div className="flex items-center gap-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2 text-[11px]"
                                onClick={selectAllVisible}
                              >
                                Select visible
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2 text-[11px]"
                                onClick={clearDealerSelection}
                              >
                                Clear all
                              </Button>
                            </div>
                          </div>
                          <div className="max-h-56 overflow-y-auto rounded-md border bg-background divide-y">
                            {filteredDealers.length === 0 ? (
                              <p className="p-3 text-xs text-muted-foreground text-center">
                                No dealers match &ldquo;{dealerSearch}&rdquo;.
                              </p>
                            ) : (
                              filteredDealers.map((d) => {
                                const checked = selectedDealerIds.includes(d.id);
                                return (
                                  <label
                                    key={d.id}
                                    className="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-muted/50"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={() => toggleDealer(d.id)}
                                      className="h-3.5 w-3.5"
                                    />
                                    <span className="flex-1 truncate text-xs">
                                      {d.name}
                                      {d.code && (
                                        <span className="text-muted-foreground ml-1">
                                          ({d.code})
                                        </span>
                                      )}
                                    </span>
                                    {d.status !== "active" && (
                                      <Badge variant="outline" className="text-[10px]">
                                        {d.status}
                                      </Badge>
                                    )}
                                  </label>
                                );
                              })
                            )}
                          </div>
                          <p className="text-[11px] text-muted-foreground">
                            Tip: leave the selection empty to scan every active dealer in your org.
                          </p>
                        </div>
                      )}
                    </div>

                    <Button
                      className="w-full h-auto py-3 flex items-center justify-center gap-2"
                      onClick={handleScanAllChannels}
                      disabled={scanning || scanningAll}
                    >
                      {scanningAll ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        <Layers className="h-5 w-5" />
                      )}
                      <span className="font-semibold">
                        {scanningAll ? "Starting All Scans..." : "Scan All Channels"}
                      </span>
                    </Button>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      {SCAN_SOURCES.map((source) => {
                        const eligible = eligibleAssetsForSource(source.value);
                        const total = assets.length;
                        const noneEligible = eligible === 0;
                        const dealerCount = dealersForChannel(source.value);
                        const noDealers = dealerCount === 0;
                        const disabled = scanning || scanningAll || noneEligible || noDealers;
                        const dealerLabel = selectedDealerIds.length === 0
                          ? `${dealerCount} active dealer${dealerCount === 1 ? "" : "s"}`
                          : `${dealerCount} of ${selectedDealerIds.length} dealer${selectedDealerIds.length === 1 ? "" : "s"}`;
                        return (
                          <Button
                            key={source.value}
                            variant="outline"
                            className="h-auto py-4 flex flex-col items-center gap-2 hover:border-primary hover:bg-primary/5"
                            onClick={() => handleStartScan(source.value)}
                            disabled={disabled}
                            title={
                              noneEligible
                                ? `No creatives are tagged for ${source.label}. Tag at least one asset (or leave it untagged) to scan this channel.`
                                : noDealers
                                  ? `None of the ${selectedDealerIds.length === 0 ? "active" : "selected"} dealers have a ${source.label} URL configured.`
                                  : `${eligible} of ${total} creative${total === 1 ? "" : "s"} will be checked on ${source.label} across ${dealerLabel}.`
                            }
                          >
                            <img src={source.logo} alt={source.label} className="h-8 w-8 object-contain" />
                            <span className="font-medium">{source.label}</span>
                            <span className="text-2xs text-muted-foreground">{source.desc}</span>
                            <span
                              className={`text-2xs ${
                                noneEligible || noDealers ? "text-yellow-600" : "text-muted-foreground"
                              }`}
                            >
                              {noneEligible
                                ? "No matching creatives"
                                : noDealers
                                  ? "No dealers configured"
                                  : `${eligible} creative${eligible === 1 ? "" : "s"} · ${dealerLabel}`}
                            </span>
                            {scanning && selectedSource === source.value && (
                              <RefreshCw className="h-4 w-4 animate-spin" />
                            )}
                          </Button>
                        );
                      })}
                    </div>
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
