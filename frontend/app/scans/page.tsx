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
  DollarSign,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useScanJobs, useCampaigns, useDeleteScan, useDeleteAllScans, useRetryScan, useBatchScan, useBillingUsage } from "@/lib/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { formatDateTime } from "@/lib/utils";

interface CostLineItem {
  vendor: string;
  op: string;
  units: number;
  unit: string;
  unit_cost_usd: number;
  cost_usd: number;
  meta?: Record<string, any>;
}

interface CostSummary {
  total_usd: number;
  by_vendor: Record<string, number>;
  line_items?: CostLineItem[];
  line_item_count?: number;
}

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
  // Phase 6.5.4 funnel additions:
  // - claude_error: images where EVERY ensemble call errored (the 0
  //   score that landed in below_threshold isn't a real "Claude said
  //   no" signal — it's infra noise).
  // - claude_errors: broader counter — images that experienced ANY
  //   Claude failure across their per-asset comparisons, including
  //   ones that ultimately matched on a different asset.
  // Per-kind buckets (claude_error_rate_limit, claude_error_timeout,
  // claude_error_overloaded, claude_error_json_parse,
  // claude_error_network, claude_error_image_optimize,
  // claude_error_other) populate dynamically — not every kind shows up
  // every scan, so we treat the stats blob as permissive on those keys.
  claude_error?: number;
  claude_errors?: number;
  [key: `claude_error_${string}`]: number | undefined;
  image_cache?: { hits: number; misses: number; hit_rate: number; cached_entries: number; cached_mb: number };
  pages_discovered?: number;
  pages_scanned?: number;
  pages_empty?: number;
  pages_blocked?: number;
  pages_failed?: number;
  pages_skipped?: number;
  dealers_total?: number;
  dealers_ok?: number;
  dealers_partial?: number;
  dealers_blocked?: number;
  dealers_failed?: number;
  dealers_empty?: number;
  blocked_details?: Array<{
    base_url?: string;
    distributor_id?: string | null;
    dealer_status?: string;
    pages: Array<{
      page_url: string;
      outcome: string;
      reason?: string | null;
      http_status?: number | null;
    }>;
  }>;
  early_stopped?: boolean;
  cache_hit?: boolean;
  cached_pages_used?: number;
  cost?: CostSummary;
  // Legacy fields for backward compat with older scans
  matched?: number;
  duplicates_skipped?: number;
}

// Friendly labels for the claude_error_<kind> tooltip. Keys match the
// `_classify_claude_error` buckets in backend/app/services/ai_service.py.
const CLAUDE_ERROR_KIND_LABELS: Record<string, string> = {
  rate_limit: "Rate limit",
  timeout: "Timeout",
  overloaded: "Overloaded",
  json_parse: "Parse failure",
  image_optimize: "Image optimize",
  network: "Network",
  other: "Other",
};

interface ClaudeErrorBreakdown {
  total: number;            // total comparisons that errored (sum of per-kind buckets)
  uniqueImages: number;     // distinct images that experienced any Claude error
  fullyErrored: number;     // images where every comparison errored (real funnel rejection)
  byKind: Array<[string, number]>;
}

function summarizeClaudeErrors(stats: PipelineStats): ClaudeErrorBreakdown | null {
  const total = Number(stats.claude_errors ?? 0);
  const fullyErrored = Number(stats.claude_error ?? 0);
  const byKind: Array<[string, number]> = [];
  for (const k of Object.keys(stats)) {
    if (!k.startsWith("claude_error_")) continue;
    const value = Number(stats[k as `claude_error_${string}`] ?? 0);
    if (value <= 0) continue;
    const kind = k.slice("claude_error_".length);
    byKind.push([kind, value]);
  }
  byKind.sort((a, b) => b[1] - a[1]);
  if (total === 0 && fullyErrored === 0 && byKind.length === 0) {
    return null;
  }
  // The per-kind sum can exceed `claude_errors` because one image can
  // bump multiple buckets if its asset comparisons fail with different
  // kinds. Use that sum, not claude_errors, as the true comparison-level
  // total for the tooltip.
  const comparisonTotal = byKind.reduce((acc, [, v]) => acc + v, 0) || total;
  return {
    total: comparisonTotal,
    uniqueImages: total,
    fullyErrored,
    byKind,
  };
}

interface ScanJob {
  id: string;
  campaign_id: string | null;
  source: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  total_items: number;
  processed_items: number;
  matches_count: number;
  error_message: string | null;
  pipeline_stats: PipelineStats | null;
  cost_usd: number | null;
  cost_breakdown: CostSummary | null;
  organization_id: string;
  apify_run_id: string | null;
  created_at: string;
}

interface Campaign {
  id: string;
  name: string;
  status: string;
  asset_count: number;
}

function formatCost(usd: number | null | undefined): string {
  if (usd == null || isNaN(Number(usd))) return "—";
  const n = Number(usd);
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

const VENDOR_LABELS: Record<string, string> = {
  anthropic: "Claude (Anthropic)",
  apify: "Apify",
  serpapi: "SerpApi",
  brightdata_unlocker: "Bright Data (Web Unlocker)",
  // Historical — old scan_jobs.cost_breakdown rows from before Phase 6.5
  // still carry the screenshotone vendor key. Keep the label so historical
  // cost breakdowns render with a friendly name in the UI.
  screenshotone: "ScreenshotOne (legacy)",
};

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

interface AnthropicCacheStats {
  call_count: number;
  cached_call_count: number;
  uncached_input_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  output_tokens: number;
  cache_write_cost_usd: number;
  cache_read_cost_usd: number;
  /** What we'd have paid in input tokens if no caching was active. */
  no_cache_input_cost_usd: number;
  /** What we did pay for input (uncached + write + read at their multipliers). */
  actual_input_cost_usd: number;
  /** Total tokens that participated in the cache (creation + reads). */
  cacheable_token_volume: number;
}

function summarizeAnthropicCache(items: CostLineItem[]): AnthropicCacheStats | null {
  const anthropic = items.filter((li) => li.vendor === "anthropic");
  if (anthropic.length === 0) return null;

  let uncached_input_tokens = 0;
  let cache_creation_tokens = 0;
  let cache_read_tokens = 0;
  let output_tokens = 0;
  let cache_write_cost_usd = 0;
  let cache_read_cost_usd = 0;
  let no_cache_input_cost_usd = 0;
  let actual_input_cost_usd = 0;
  let cached_call_count = 0;

  for (const li of anthropic) {
    const m = li.meta || {};
    const u = Number(m.input_tokens || 0);
    const cw = Number(m.cache_creation_tokens || 0);
    const cr = Number(m.cache_read_tokens || 0);
    const out = Number(m.output_tokens || 0);
    const inputRate = Number(m.rate_input_per_mtok || 0);
    const inCost = Number(m.input_cost_usd || 0);
    const writeCost = Number(m.cache_write_cost_usd || 0);
    const readCost = Number(m.cache_read_cost_usd || 0);

    uncached_input_tokens += u;
    cache_creation_tokens += cw;
    cache_read_tokens += cr;
    output_tokens += out;
    cache_write_cost_usd += writeCost;
    cache_read_cost_usd += readCost;
    actual_input_cost_usd += inCost + writeCost + readCost;

    // Hypothetical cost if every token had been billed at the regular input rate
    // (i.e. caching had been disabled).
    const totalInputTokens = u + cw + cr;
    no_cache_input_cost_usd += (totalInputTokens / 1_000_000) * inputRate;

    if (cr > 0) cached_call_count += 1;
  }

  return {
    call_count: anthropic.length,
    cached_call_count,
    uncached_input_tokens,
    cache_creation_tokens,
    cache_read_tokens,
    output_tokens,
    cache_write_cost_usd,
    cache_read_cost_usd,
    no_cache_input_cost_usd,
    actual_input_cost_usd,
    cacheable_token_volume: cache_creation_tokens + cache_read_tokens,
  };
}

function CacheStatsBar({ stats }: { stats: AnthropicCacheStats }) {
  const { cache_read_tokens, cache_creation_tokens, uncached_input_tokens, call_count, cached_call_count } = stats;
  const total_input = uncached_input_tokens + cache_creation_tokens + cache_read_tokens;

  // Hit rate by tokens (not by calls) — this is the true measure of cache effectiveness.
  const hit_rate_tokens = total_input > 0 ? (cache_read_tokens / total_input) * 100 : 0;
  const hit_rate_calls = call_count > 0 ? (cached_call_count / call_count) * 100 : 0;

  const savings = stats.no_cache_input_cost_usd - stats.actual_input_cost_usd;
  const savings_pct = stats.no_cache_input_cost_usd > 0
    ? (savings / stats.no_cache_input_cost_usd) * 100
    : 0;

  // Detect the "caching is configured but not yet warm" case so we can show a
  // helpful hint instead of just zeroes.
  const cache_active = cache_creation_tokens > 0 || cache_read_tokens > 0;

  return (
    <div className="mt-2 pt-2 border-t border-border/20 text-xs">
      <div className="flex items-center justify-between mb-1.5 text-muted-foreground">
        <span className="font-medium">Anthropic prompt cache</span>
        {cache_active ? (
          <span className="font-mono tabular-nums text-emerald-400">
            saved {formatCost(savings)} ({savings_pct.toFixed(0)}% of input)
          </span>
        ) : (
          <span className="text-muted-foreground/70 italic">no cache hits yet</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Hit rate (tokens)</span>
          <span className="font-mono tabular-nums">{hit_rate_tokens.toFixed(1)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Hit rate (calls)</span>
          <span className="font-mono tabular-nums">
            {cached_call_count}/{call_count} ({hit_rate_calls.toFixed(0)}%)
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Cache reads</span>
          <span className="font-mono tabular-nums text-emerald-400">{formatTokens(cache_read_tokens)} tok</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Cache writes</span>
          <span className="font-mono tabular-nums text-amber-400">{formatTokens(cache_creation_tokens)} tok</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Uncached input</span>
          <span className="font-mono tabular-nums">{formatTokens(uncached_input_tokens)} tok</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Output</span>
          <span className="font-mono tabular-nums">{formatTokens(stats.output_tokens)} tok</span>
        </div>
      </div>
    </div>
  );
}

function CostBreakdown({ cost }: { cost: CostSummary }) {
  const vendors = Object.entries(cost.by_vendor || {}).sort((a, b) => b[1] - a[1]);
  if (vendors.length === 0) return null;

  const cacheStats = cost.line_items ? summarizeAnthropicCache(cost.line_items) : null;

  return (
    <div className="mt-2 pt-2 border-t border-border/30 text-xs">
      <div className="flex items-center gap-2 mb-1.5 text-muted-foreground">
        <DollarSign className="h-3 w-3" />
        <span className="font-medium">Cost breakdown — total {formatCost(cost.total_usd)}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {vendors.map(([vendor, amount]) => (
          <div key={vendor} className="flex justify-between">
            <span className="text-muted-foreground">{VENDOR_LABELS[vendor] || vendor}</span>
            <span className="font-mono tabular-nums">{formatCost(amount)}</span>
          </div>
        ))}
      </div>
      {cacheStats && cacheStats.call_count > 0 && <CacheStatsBar stats={cacheStats} />}
    </div>
  );
}

function ClaudeErrorBreakdownPanel({ breakdown }: { breakdown: ClaudeErrorBreakdown }) {
  return (
    <div className="mt-2 pt-2 border-t border-border/30 text-xs">
      <div className="flex items-center justify-between mb-1.5 text-muted-foreground">
        <span className="font-medium text-amber-400">Claude infra errors</span>
        <span className="font-mono tabular-nums text-muted-foreground/80">
          {breakdown.uniqueImages} image{breakdown.uniqueImages === 1 ? "" : "s"} affected
          {breakdown.fullyErrored > 0 && (
            <span className="text-red-400">
              {" "}· {breakdown.fullyErrored} fully errored
            </span>
          )}
        </span>
      </div>
      {breakdown.byKind.length > 0 ? (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
          {breakdown.byKind.map(([kind, count]) => (
            <div key={kind} className="flex justify-between">
              <span className="text-muted-foreground">
                {CLAUDE_ERROR_KIND_LABELS[kind] || kind}
              </span>
              <span className="font-mono tabular-nums">{count}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-muted-foreground/80 italic">
          No per-kind breakdown recorded
        </div>
      )}
      <p className="mt-1.5 text-muted-foreground/70">
        These are scans where Claude itself failed (rate limit, timeout, parse
        error) — not "Claude said this isn't a match". Spikes correlate with
        Anthropic infra pressure or Bright-Data-driven traffic bumping into
        quota.
      </p>
    </div>
  );
}

function PipelineFunnel({ stats }: { stats: PipelineStats }) {
  const newMatches = stats.matched_new ?? stats.matched ?? 0;
  const confirmed = stats.matched_confirmed ?? 0;
  const drift = stats.drift_detected ?? 0;
  const claudeErrorStage = Number(stats.claude_error ?? 0);
  const claudeBreakdown = summarizeClaudeErrors(stats);

  // Phase 6.5.4 surfaces ``claude_error`` (the funnel stage where every
  // comparison errored) separately from ``below_threshold`` so a spike
  // in Anthropic pressure is visible at a glance instead of silently
  // depressing the match rate. Only show the row when it actually fired.
  const stages = [
    { label: "Total Images", value: stats.total_images, color: "bg-slate-500" },
    { label: "Download Failed", value: stats.download_failed, color: "bg-red-500" },
    { label: "Hash Rejected", value: stats.hash_rejected, color: "bg-orange-500" },
    { label: "CLIP Rejected", value: stats.clip_rejected, color: "bg-amber-500" },
    { label: "Haiku Filter Rejected", value: stats.filter_rejected, color: "bg-yellow-500" },
    { label: "Below Threshold", value: stats.below_threshold, color: "bg-purple-500" },
    { label: "Verification Rejected", value: stats.verification_rejected, color: "bg-pink-500" },
    ...(claudeErrorStage > 0
      ? [{ label: "Claude Errors", value: claudeErrorStage, color: "bg-rose-500" }]
      : []),
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
          {((stats.pages_blocked ?? 0) > 0 || (stats.pages_failed ?? 0) > 0) && (
            <span className="text-amber-400">
              {(stats.pages_blocked ?? 0) > 0 && `${stats.pages_blocked} blocked`}
              {(stats.pages_blocked ?? 0) > 0 && (stats.pages_failed ?? 0) > 0 && ", "}
              {(stats.pages_failed ?? 0) > 0 && `${stats.pages_failed} failed`}
            </span>
          )}
          {(stats.dealers_blocked ?? 0) > 0 && (
            <span className="text-amber-400">
              {stats.dealers_blocked} dealer{stats.dealers_blocked === 1 ? "" : "s"} blocked
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
      {claudeBreakdown && <ClaudeErrorBreakdownPanel breakdown={claudeBreakdown} />}
      {stats.cost && <CostBreakdown cost={stats.cost} />}
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
                  Started {Array.isArray(batchScanMutation.data) ? batchScanMutation.data.length : 0} scan(s)
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
            {scanJobs.map((job: any) => (
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
                      {Number(job.cost_usd ?? 0) > 0 && (
                        <div className="text-right">
                          <div className="flex items-center justify-end gap-1 text-sm font-medium text-emerald-400">
                            <DollarSign className="h-3.5 w-3.5" />
                            <span className="font-mono tabular-nums">{formatCost(job.cost_usd)}</span>
                          </div>
                          <p className="text-xs text-muted-foreground">scan cost</p>
                        </div>
                      )}
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
                        {/* Claude-infra-error count surfaces here so a low
                            match-count caused by Anthropic pressure is
                            distinguishable at-a-glance from a genuine
                            "nothing matched" outcome. Only renders when
                            the counter is non-zero — quiet otherwise. */}
                        {job.pipeline_stats && Number(job.pipeline_stats.claude_errors ?? 0) > 0 && (
                          <p className="text-xs text-rose-400 mt-0.5" title="Images where Claude itself failed (rate limit / timeout / parse error). Expand the Pipeline Funnel for a per-kind breakdown.">
                            {Number(job.pipeline_stats.claude_errors)} Claude error{Number(job.pipeline_stats.claude_errors) === 1 ? "" : "s"}
                            {Number(job.pipeline_stats.claude_error ?? 0) > 0 && (
                              <span className="text-rose-300/80">
                                {" "}({Number(job.pipeline_stats.claude_error)} fully)
                              </span>
                            )}
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
                          {(() => {
                            const msg = job.error_message?.toLowerCase() ?? "";
                            // If the backend already produced a normalised,
                            // self-explanatory message (currently only the
                            // Playwright "browser runtime not installed"
                            // prefix), don't add a second redundant hint —
                            // the verbatim error_message above already tells
                            // the user exactly what to do.
                            if (msg.startsWith("browser runtime not installed")) {
                              return null;
                            }
                            const hint = msg.includes("timeout")
                              ? "The scan timed out. Try scanning fewer dealers or a different channel."
                              : msg.includes("rate")
                              ? "API rate limit hit. Wait a few minutes and retry."
                              : msg.includes("browsertype.launch") ||
                                msg.includes("chrome-headless-shell") ||
                                msg.includes("playwright install")
                              ? "The scan worker is missing browser binaries (Playwright Chromium). Run backend/scripts/install_playwright.sh, then retry."
                              : msg.includes("url") || msg.includes("404")
                              ? "A dealer URL may be invalid. Check your distributor settings."
                              : "Check your campaign assets and dealer URLs, then retry.";
                            return (
                              <p className="text-xs text-muted-foreground mt-1.5">
                                {hint}
                              </p>
                            );
                          })()}
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

                  {(job.pipeline_stats || job.cost_breakdown) && (
                    <div className="mt-3">
                      <button
                        onClick={() => toggleExpanded(job.id)}
                        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <BarChart3 className="h-3.5 w-3.5" />
                        {job.pipeline_stats ? "Pipeline Funnel & Cost" : "Cost Breakdown"}
                        {expandedJobs.has(job.id) ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                      </button>

                      {expandedJobs.has(job.id) && (
                        job.pipeline_stats ? (
                          <PipelineFunnel
                            stats={{
                              ...job.pipeline_stats,
                              cost: job.pipeline_stats.cost ?? job.cost_breakdown ?? undefined,
                            }}
                          />
                        ) : job.cost_breakdown ? (
                          <div className="mt-3 p-3 rounded-lg bg-muted/50 border border-border/50">
                            <CostBreakdown cost={job.cost_breakdown} />
                          </div>
                        ) : null
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
