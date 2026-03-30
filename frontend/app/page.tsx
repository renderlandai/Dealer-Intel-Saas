"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Megaphone,
  Building2,
  ImageIcon,
  AlertTriangle,
  TrendingUp,
  CheckCircle,
  Radar,
  ArrowRight,
  Search,
  Activity,
  Zap,
  FileText,
  Download,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { StatCard } from "@/components/dashboard/stat-card";
import { RecentMatches } from "@/components/dashboard/recent-matches";
import { AlertsPanel } from "@/components/dashboard/alerts-panel";
import { ChannelChart } from "@/components/dashboard/channel-chart";
import dynamic from "next/dynamic";
const DealerMap = dynamic(() => import("@/components/dashboard/DealerMap"), {
  ssr: false,
  loading: () => (
    <div className="h-[400px] w-full bg-secondary/20 animate-pulse flex items-center justify-center text-muted-foreground">
      Loading Map...
    </div>
  ),
});
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  useDashboardStats,
  useRecentMatches,
  useRecentAlerts,
  useChannelCoverage,
  useCampaigns,
  useDistributors,
  useBillingUsage,
} from "@/lib/hooks";
import { downloadComplianceReport } from "@/lib/api";
import { TrialBanner } from "@/components/dashboard/trial-banner";
import { UsageCard } from "@/components/dashboard/usage-card";
import { OnboardingChecklist } from "@/components/dashboard/onboarding-checklist";
import { ComplianceTrend } from "@/components/dashboard/compliance-trend";

interface Campaign {
  id: string;
  name: string;
  status: string;
  asset_count: number;
}

export default function DashboardPage() {
  const { data: stats = {
    active_campaigns: 0,
    total_assets: 0,
    active_distributors: 0,
    total_matches: 0,
    unread_alerts: 0,
    compliance_rate: 0,
    matches_today: 0,
    violations_count: 0,
  }, isLoading: statsLoading, isError: statsError } = useDashboardStats();
  
  const { data: matches = [] } = useRecentMatches(6);
  const { data: alerts = [] } = useRecentAlerts(5);
  const { data: channelData = [] } = useChannelCoverage();
  const { data: allCampaigns = [], isError: campaignsError } = useCampaigns();
  const { data: distributors = [], isError: distributorsError } = useDistributors();
  const { data: billing } = useBillingUsage();
  
  const campaigns = allCampaigns.filter((c: Campaign) => c.status === "active");
  const loading = statsLoading;
  const [downloading, setDownloading] = useState<string | null>(null);

  const handleDownload = async (format: "pdf" | "csv") => {
    setDownloading(format);
    try {
      await downloadComplianceReport(format);
    } catch (error: any) {
      console.error("Download failed:", error);
      alert(error?.response?.data?.detail || "Report download failed. Please try again.");
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="min-h-screen">
      <Header
        title="Dashboard"
        description="Monitor campaign asset usage across distributor networks"
      />

      <div className="p-8 space-y-8">
        {/* Trial Banner */}
        {billing && (
          <TrialBanner
            plan={billing.plan}
            planStatus={billing.plan_status}
            trialDaysLeft={billing.trial_days_left}
          />
        )}

        {/* Onboarding Checklist */}
        {!statsLoading && (
          <OnboardingChecklist
            campaignCount={stats.active_campaigns}
            assetCount={stats.total_assets}
            distributorCount={stats.active_distributors}
            scanCount={stats.total_matches}
          />
        )}

        {/* Connection Error Banner */}
        {(statsError || campaignsError || distributorsError) && (
          <div className="flex items-center gap-3 p-4 border border-destructive/30 bg-destructive/5 opacity-0 animate-fade-up">
            <AlertTriangle className="h-5 w-5 text-destructive flex-shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-medium">Unable to connect to the server</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Make sure the backend is running on port 8000. Data shown below may be incomplete.
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
              Retry
            </Button>
          </div>
        )}

        {/* Top Key Metrics */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Link href="/matches?status=compliant" className="stat-card opacity-0 animate-fade-up delay-150 hover:border-success/40 transition-colors cursor-pointer">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center bg-success/10 border border-success/20">
                <CheckCircle className="h-6 w-6 text-success" />
              </div>
              <div>
                <p className="text-2xs uppercase tracking-wider text-muted-foreground">Compliance Rate</p>
                <p className="data-value mt-1">{stats.compliance_rate}%</p>
              </div>
            </div>
          </Link>
          <Link href="/matches?status=violation" className="stat-card opacity-0 animate-fade-up delay-225 hover:border-destructive/40 transition-colors cursor-pointer">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center bg-destructive/10 border border-destructive/20">
                <AlertTriangle className="h-6 w-6 text-destructive" />
              </div>
              <div>
                <p className="text-2xs uppercase tracking-wider text-muted-foreground">Violations</p>
                <p className="data-value mt-1">{stats.violations_count}</p>
              </div>
            </div>
          </Link>
          <StatCard
            title="Active Campaigns"
            value={stats.active_campaigns}
            icon={Megaphone}
            iconColor="text-primary"
          />
          <StatCard
            title="Distributors"
            value={stats.active_distributors}
            icon={Building2}
            iconColor="text-emerald-400"
          />
        </div>

        {/* War Room: Map + Feed */}
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-6">
            <div className="opacity-0 animate-fade-up delay-100" style={{ animationFillMode: 'forwards' }}>
              <Card className="border-border/60">
                <CardHeader className="pb-3 border-b border-border/50">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Radar className="h-5 w-5 text-primary" />
                    Dealer Network Compliance Map
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Geospatial view of compliant (green) vs violating (red) dealers
                  </CardDescription>
                </CardHeader>
                <CardContent className="p-0">
                  <DealerMap distributors={distributors} />
                </CardContent>
              </Card>
            </div>

            {/* Secondary Stats */}
            <div className="grid gap-4 grid-cols-2">
              <StatCard
                title="Tracked Assets"
                value={stats.total_assets}
                icon={ImageIcon}
                iconColor="text-blue-400"
              />
              <StatCard
                title="Total Matches"
                value={stats.total_matches}
                change={`${stats.matches_today} today`}
                changeType="positive"
                icon={Search}
                iconColor="text-primary"
              />
            </div>

            {/* Channel Chart + Asset Coverage */}
            <div className="grid gap-6 grid-cols-2">
              <ChannelChart data={channelData} />
              
              {/* Asset Coverage */}
              <Card className="opacity-0 animate-fade-up delay-75">
                <CardHeader className="border-b border-border">
                  <CardTitle className="accent-line pb-2">Asset Coverage</CardTitle>
                  <p className="text-xs text-muted-foreground mt-1">
                    Matches by platform
                  </p>
                </CardHeader>
                <CardContent className="pt-6">
                  <div className="space-y-4">
                    {[
                      { name: "Google Ads", key: "google_ads", color: "bg-amber-500" },
                      { name: "Facebook", key: "facebook", color: "bg-blue-500" },
                      { name: "Instagram", key: "instagram", color: "bg-pink-500" },
                      { name: "Websites", key: "website", color: "bg-emerald-500" },
                    ].map((channel, index) => {
                      const count = channelData.find((c: any) => c.channel === channel.key)?.count || 0;
                      const maxCount = Math.max(...channelData.map((c: any) => c.count), 1);
                      const percentage = (count / maxCount) * 100;
                      
                      return (
                        <div 
                          key={channel.key} 
                          className="opacity-0 animate-fade-up"
                          style={{ animationDelay: `${100 + index * 50}ms`, animationFillMode: 'forwards' }}
                        >
                          <div className="flex justify-between items-center mb-2">
                            <div className="flex items-center gap-2">
                              <div className={`w-2 h-2 ${channel.color}`} />
                              <span className="text-sm text-muted-foreground">{channel.name}</span>
                            </div>
                            <span className="text-sm font-mono font-medium">{count}</span>
                          </div>
                          <div className="h-1 bg-secondary overflow-hidden">
                            <div 
                              className={`h-full ${channel.color} transition-all duration-700 ease-out`}
                              style={{ width: `${percentage}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Compliance Trend — Pro/Business */}
            <ComplianceTrend
              enabled={!!billing?.features?.compliance_trends}
            />

            {/* Scan Action Card */}
            <Card className="border-primary/20 bg-gradient-to-r from-primary/5 via-transparent to-transparent opacity-0 animate-fade-up">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center bg-primary">
                    <Zap className="h-5 w-5 text-primary-foreground" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Start a Scan</CardTitle>
                    <CardDescription className="text-xs">
                      Select a campaign to scan for assets across distributor channels
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {campaigns.length === 0 ? (
                  <div className="text-center py-6 border border-dashed border-border bg-secondary/30">
                    <p className="text-sm text-muted-foreground mb-4">
                      No active campaigns found. Create a campaign first to start scanning.
                    </p>
                    <Link href="/campaigns">
                      <Button size="sm">
                        <Megaphone className="mr-2 h-4 w-4" />
                        Create Campaign
                      </Button>
                    </Link>
                  </div>
                ) : (
                  <div className="grid gap-3 grid-cols-2">
                    {campaigns.slice(0, 4).map((campaign: Campaign, index: number) => (
                      <Link key={campaign.id} href={`/campaigns/${campaign.id}?tab=scans`}>
                        <div 
                          className="group p-4 border border-border bg-card hover:border-primary/50 hover:bg-secondary/50 transition-all cursor-pointer opacity-0 animate-fade-up"
                          style={{ animationDelay: `${100 + index * 50}ms`, animationFillMode: 'forwards' }}
                        >
                          <div className="flex items-center justify-between">
                            <div>
                              <p className="text-sm font-medium group-hover:text-primary transition-colors">
                                {campaign.name}
                              </p>
                              <p className="text-2xs text-muted-foreground mt-1 font-mono">
                                {campaign.asset_count} assets
                              </p>
                            </div>
                            <ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-all group-hover:translate-x-0.5" />
                          </div>
                        </div>
                      </Link>
                    ))}
                    {campaigns.length > 4 && (
                      <Link href="/campaigns">
                        <div className="p-4 border border-dashed border-border hover:border-primary/50 transition-colors cursor-pointer flex items-center justify-center h-full">
                          <span className="text-xs text-muted-foreground">
                            +{campaigns.length - 4} more campaigns
                          </span>
                        </div>
                      </Link>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
            {/* Compliance Report Card */}
            <Card className="border-border/60 opacity-0 animate-fade-up">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center bg-secondary border border-border">
                    <FileText className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Compliance Report</CardTitle>
                    <CardDescription className="text-xs">
                      Export match data and compliance analytics
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleDownload("pdf")}
                    disabled={downloading !== null}
                  >
                    <Download className="mr-2 h-3.5 w-3.5" />
                    {downloading === "pdf" ? "Generating..." : "PDF Report"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleDownload("csv")}
                    disabled={downloading !== null}
                  >
                    <Download className="mr-2 h-3.5 w-3.5" />
                    {downloading === "csv" ? "Generating..." : "CSV Export"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
          <div className="opacity-0 animate-fade-up delay-200 space-y-6" style={{ animationFillMode: 'forwards' }}>
            {billing && (
              <UsageCard
                dealers={billing.dealers}
                campaigns={billing.campaigns}
                scans={billing.scans}
                plan={billing.plan}
              />
            )}
            <RecentMatches matches={matches} />
            <AlertsPanel alerts={alerts} />
          </div>
        </div>

      </div>
    </div>
  );
}
