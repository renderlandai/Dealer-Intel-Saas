"use client";

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
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { StatCard } from "@/components/dashboard/stat-card";
import { RecentMatches } from "@/components/dashboard/recent-matches";
import { AlertsPanel } from "@/components/dashboard/alerts-panel";
import { ChannelChart } from "@/components/dashboard/channel-chart";
import DealerMap from "@/components/dashboard/DealerMap";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  useDashboardStats,
  useRecentMatches,
  useRecentAlerts,
  useChannelCoverage,
  useCampaigns,
  useDistributors,
} from "@/lib/hooks";

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
  }, isLoading: statsLoading } = useDashboardStats();
  
  const { data: matches = [] } = useRecentMatches(10);
  const { data: alerts = [] } = useRecentAlerts(5);
  const { data: channelData = [] } = useChannelCoverage();
  const { data: allCampaigns = [] } = useCampaigns();
  const { data: distributors = [] } = useDistributors();
  
  const campaigns = allCampaigns.filter((c: Campaign) => c.status === "active");
  const loading = statsLoading;

  return (
    <div className="min-h-screen">
      <Header
        title="Dashboard"
        description="Monitor campaign asset usage across distributor networks"
      />

      <div className="p-8 space-y-8">
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
          <div className="lg:col-span-2 opacity-0 animate-fade-up delay-100" style={{ animationFillMode: 'forwards' }}>
            <Card className="h-full border-border/60">
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
          <div className="opacity-0 animate-fade-up delay-200 space-y-6" style={{ animationFillMode: 'forwards' }}>
            <RecentMatches matches={matches} />
            <AlertsPanel alerts={alerts} />
          </div>
        </div>

        {/* Secondary Stats */}
        <div className="grid gap-4 md:grid-cols-2">
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
        <div className="grid gap-6 lg:grid-cols-2">
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

        {/* Scan Action Card */}
        <div>
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
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {campaigns.slice(0, 3).map((campaign: Campaign, index: number) => (
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
                    {campaigns.length > 3 && (
                      <Link href="/campaigns">
                        <div className="p-4 border border-dashed border-border hover:border-primary/50 transition-colors cursor-pointer flex items-center justify-center h-full">
                          <span className="text-xs text-muted-foreground">
                            +{campaigns.length - 3} more campaigns
                          </span>
                        </div>
                      </Link>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
        </div>

      </div>
    </div>
  );
}
