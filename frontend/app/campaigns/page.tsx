"use client";

import { useState } from "react";
import Link from "next/link";
import { Plus, ImageIcon, Calendar, ArrowRight, Folder } from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { useCampaigns, useCreateCampaign } from "@/lib/hooks";
import { formatDate } from "@/lib/utils";

interface Campaign {
  id: string;
  name: string;
  description?: string;
  status: string;
  start_date?: string;
  end_date?: string;
  asset_count: number;
  created_at: string;
}

export default function CampaignsPage() {
  const { data: campaigns = [], isLoading: loading, isError, error, refetch } = useCampaigns();
  const createCampaignMutation = useCreateCampaign();
  const [showCreate, setShowCreate] = useState(false);
  const [newCampaign, setNewCampaign] = useState({ name: "", description: "" });

  const handleCreate = async () => {
    if (!newCampaign.name) return;
    
    try {
      await createCampaignMutation.mutateAsync(newCampaign);
      setShowCreate(false);
      setNewCampaign({ name: "", description: "" });
    } catch (error) {
      console.error("Failed to create campaign:", error);
    }
  };

  const statusStyles: Record<string, string> = {
    active: "border-success/30 bg-success/10 text-success",
    paused: "border-amber-500/30 bg-amber-500/10 text-amber-400",
    completed: "border-border bg-secondary text-muted-foreground",
  };

  return (
    <div className="min-h-screen">
      <Header
        title="Campaigns"
        description="Manage your marketing campaigns and assets"
      />

      <div className="p-8 space-y-6">
        {/* Header Actions */}
        <div className="flex justify-between items-center opacity-0 animate-fade-up">
          <div>
            <p className="text-sm text-muted-foreground font-mono">
              {campaigns.length} campaign{campaigns.length !== 1 ? "s" : ""}
            </p>
          </div>
          <Button onClick={() => setShowCreate(true)} size="sm">
            <Plus className="mr-2 h-4 w-4" />
            New Campaign
          </Button>
        </div>

        {/* Create Campaign Modal */}
        {showCreate && (
          <Card className="border-primary/30 opacity-0 animate-fade-up">
            <CardHeader className="border-b border-border">
              <CardTitle className="text-base">Create New Campaign</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 pt-5">
              <div>
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Campaign Name
                </label>
                <Input
                  placeholder="e.g., Q1 2026 Brand Campaign"
                  value={newCampaign.name}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, name: e.target.value })
                  }
                  className="mt-2"
                />
              </div>
              <div>
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Description
                </label>
                <Input
                  placeholder="Optional description..."
                  value={newCampaign.description}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, description: e.target.value })
                  }
                  className="mt-2"
                />
              </div>
              <div className="flex gap-2 pt-2">
                <Button onClick={handleCreate} disabled={createCampaignMutation.isPending} size="sm">
                  {createCampaignMutation.isPending ? "Creating..." : "Create Campaign"}
                </Button>
                <Button variant="outline" onClick={() => setShowCreate(false)} size="sm">
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Campaigns Grid */}
        {loading ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="stat-card animate-pulse">
                <div className="h-5 bg-secondary w-16 mb-4" />
                <div className="h-6 bg-secondary w-3/4 mb-3" />
                <div className="h-4 bg-secondary w-1/2" />
              </div>
            ))}
          </div>
        ) : isError ? (
          <Card className="opacity-0 animate-fade-up border-destructive/30">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="h-14 w-14 flex items-center justify-center bg-destructive/10 border border-destructive/20 mb-4">
                <Folder className="h-7 w-7 text-destructive" />
              </div>
              <h3 className="text-base font-medium">Failed to load campaigns</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md text-center">
                Could not connect to the server. Make sure the backend is running on port 8000.
              </p>
              <Button className="mt-6" onClick={() => refetch()} size="sm" variant="outline">
                Try Again
              </Button>
            </CardContent>
          </Card>
        ) : campaigns.length === 0 ? (
          <Card className="opacity-0 animate-fade-up">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="h-14 w-14 flex items-center justify-center bg-secondary border border-border mb-4">
                <Folder className="h-7 w-7 text-muted-foreground" />
              </div>
              <h3 className="text-base font-medium">No campaigns yet</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Create your first campaign to start tracking assets
              </p>
              <Button className="mt-6" onClick={() => setShowCreate(true)} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Create Campaign
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {campaigns.map((campaign: Campaign, index: number) => (
              <Link key={campaign.id} href={`/campaigns/${campaign.id}`}>
                <div 
                  className="stat-card h-full transition-all hover:border-primary/30 group cursor-pointer opacity-0 animate-fade-up"
                  style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
                >
                  <div className="flex items-start justify-between mb-4">
                    <Badge className={statusStyles[campaign.status] || statusStyles.active}>
                      {campaign.status}
                    </Badge>
                    <ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-all group-hover:translate-x-0.5" />
                  </div>
                  
                  <h3 className="text-base font-semibold mb-2 group-hover:text-primary transition-colors">
                    {campaign.name}
                  </h3>
                  
                  {campaign.description && (
                    <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
                      {campaign.description}
                    </p>
                  )}
                  
                  <div className="flex items-center gap-4 text-xs text-muted-foreground mt-auto pt-4 border-t border-border">
                    <div className="flex items-center gap-1.5 font-mono">
                      <ImageIcon className="h-3.5 w-3.5" />
                      {campaign.asset_count} assets
                    </div>
                    <div className="flex items-center gap-1.5 font-mono">
                      <Calendar className="h-3.5 w-3.5" />
                      {formatDate(campaign.created_at)}
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
