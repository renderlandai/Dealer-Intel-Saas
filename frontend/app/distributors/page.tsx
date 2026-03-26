"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Plus,
  Building2,
  Globe,
  Facebook,
  Instagram,
  Youtube,
  MapPin,
  ArrowRight,
  Pencil,
  X,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { useDistributors, useCreateDistributor, useUpdateDistributor } from "@/lib/hooks";

interface Distributor {
  id: string;
  name: string;
  code?: string;
  website_url?: string;
  facebook_url?: string;
  instagram_url?: string;
  youtube_url?: string;
  google_ads_advertiser_id?: string;
  region?: string;
  status: string;
  match_count: number;
}

export default function DistributorsPage() {
  const { data: distributors = [], isLoading: loading, isError, refetch } = useDistributors();
  const createDistributorMutation = useCreateDistributor();
  const updateDistributorMutation = useUpdateDistributor();
  const [showCreate, setShowCreate] = useState(false);
  const [editingDistributor, setEditingDistributor] = useState<Distributor | null>(null);
  const [newDistributor, setNewDistributor] = useState({
    name: "",
    website_url: "",
    facebook_url: "",
    google_ads_advertiser_id: "",
    region: "",
  });
  const [editForm, setEditForm] = useState({
    name: "",
    website_url: "",
    facebook_url: "",
    instagram_url: "",
    youtube_url: "",
    google_ads_advertiser_id: "",
    region: "",
    code: "",
  });

  const handleCreate = async () => {
    if (!newDistributor.name) return;
    
    try {
      await createDistributorMutation.mutateAsync(newDistributor);
      setShowCreate(false);
      setNewDistributor({ name: "", website_url: "", facebook_url: "", google_ads_advertiser_id: "", region: "" });
    } catch (error) {
      console.error("Failed to create distributor:", error);
    }
  };

  const handleStartEdit = (distributor: Distributor, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setEditingDistributor(distributor);
    setEditForm({
      name: distributor.name || "",
      website_url: distributor.website_url || "",
      facebook_url: distributor.facebook_url || "",
      instagram_url: distributor.instagram_url || "",
      youtube_url: distributor.youtube_url || "",
      google_ads_advertiser_id: distributor.google_ads_advertiser_id || "",
      region: distributor.region || "",
      code: distributor.code || "",
    });
  };

  const handleSaveEdit = async () => {
    if (!editingDistributor || !editForm.name) return;
    
    try {
      await updateDistributorMutation.mutateAsync({
        id: editingDistributor.id,
        updates: editForm,
      });
      setEditingDistributor(null);
    } catch (error) {
      console.error("Failed to update distributor:", error);
    }
  };

  const handleCancelEdit = () => {
    setEditingDistributor(null);
  };

  return (
    <div className="min-h-screen">
      <Header
        title="Distributors"
        description="Manage your dealer and distributor network"
      />

      <div className="p-8 space-y-6">
        {/* Header Actions */}
        <div className="flex justify-between items-center opacity-0 animate-fade-up">
          <div>
            <p className="text-sm text-muted-foreground font-mono">
              {distributors.length} distributor{distributors.length !== 1 ? "s" : ""}
            </p>
          </div>
          <Button onClick={() => setShowCreate(true)} size="sm">
            <Plus className="mr-2 h-4 w-4" />
            Add Distributor
          </Button>
        </div>

        {/* Create Distributor Form */}
        {showCreate && (
          <Card className="border-primary/30 opacity-0 animate-fade-up">
            <CardHeader className="border-b border-border">
              <CardTitle className="text-base">Add New Distributor</CardTitle>
            </CardHeader>
            <CardContent className="pt-5 space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Distributor Name *
                  </label>
                  <Input
                    placeholder="e.g., Mustang CAT"
                    value={newDistributor.name}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, name: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Region
                  </label>
                  <Input
                    placeholder="e.g., Texas or Houston"
                    value={newDistributor.region}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, region: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Website URL
                  </label>
                  <Input
                    placeholder="https://example.com"
                    value={newDistributor.website_url}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, website_url: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Facebook URL
                  </label>
                  <Input
                    placeholder="https://facebook.com/page"
                    value={newDistributor.facebook_url}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, facebook_url: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Google Ads Advertiser ID
                  </label>
                  <Input
                    placeholder="e.g., AR12345678901234567"
                    value={newDistributor.google_ads_advertiser_id}
                    onChange={(e) =>
                      setNewDistributor({ ...newDistributor, google_ads_advertiser_id: e.target.value })
                    }
                    className="mt-2"
                  />
                </div>
              </div>
              <div className="flex gap-2 pt-2">
                <Button onClick={handleCreate} disabled={createDistributorMutation.isPending} size="sm">
                  {createDistributorMutation.isPending ? "Adding..." : "Add Distributor"}
                </Button>
                <Button variant="outline" onClick={() => setShowCreate(false)} size="sm">
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Edit Distributor Modal */}
        {editingDistributor && (
          <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-2xl border-primary/30 animate-fade-up">
              <CardHeader className="border-b border-border flex flex-row items-center justify-between">
                <CardTitle className="text-base">Edit Distributor</CardTitle>
                <Button variant="ghost" size="sm" onClick={handleCancelEdit} className="h-8 w-8 p-0">
                  <X className="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent className="pt-5 space-y-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Distributor Name *
                    </label>
                    <Input
                      placeholder="e.g., Mustang CAT"
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Code
                    </label>
                    <Input
                      placeholder="e.g., MCAT001"
                      value={editForm.code}
                      onChange={(e) => setEditForm({ ...editForm, code: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Region (State or City)
                    </label>
                    <Input
                      placeholder="e.g., Texas, Houston, or TX"
                      value={editForm.region}
                      onChange={(e) => setEditForm({ ...editForm, region: e.target.value })}
                      className="mt-2"
                    />
                    <p className="text-2xs text-muted-foreground mt-1">
                      Used for map location. Enter a US state name, city, or abbreviation.
                    </p>
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Website URL
                    </label>
                    <Input
                      placeholder="https://example.com"
                      value={editForm.website_url}
                      onChange={(e) => setEditForm({ ...editForm, website_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Facebook URL
                    </label>
                    <Input
                      placeholder="https://facebook.com/page"
                      value={editForm.facebook_url}
                      onChange={(e) => setEditForm({ ...editForm, facebook_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Instagram URL
                    </label>
                    <Input
                      placeholder="https://instagram.com/page"
                      value={editForm.instagram_url}
                      onChange={(e) => setEditForm({ ...editForm, instagram_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Google Ads Advertiser ID
                    </label>
                    <Input
                      placeholder="e.g., AR12345678901234567"
                      value={editForm.google_ads_advertiser_id}
                      onChange={(e) => setEditForm({ ...editForm, google_ads_advertiser_id: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      YouTube URL
                    </label>
                    <Input
                      placeholder="https://youtube.com/channel"
                      value={editForm.youtube_url}
                      onChange={(e) => setEditForm({ ...editForm, youtube_url: e.target.value })}
                      className="mt-2"
                    />
                  </div>
                </div>
                <div className="flex gap-2 pt-4 border-t border-border">
                  <Button onClick={handleSaveEdit} disabled={updateDistributorMutation.isPending} size="sm">
                    {updateDistributorMutation.isPending ? "Saving..." : "Save Changes"}
                  </Button>
                  <Button variant="outline" onClick={handleCancelEdit} size="sm">
                    Cancel
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Distributors List */}
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="stat-card animate-pulse">
                <div className="flex items-center gap-4">
                  <div className="h-12 w-12 bg-secondary" />
                  <div className="flex-1">
                    <div className="h-5 bg-secondary w-1/4 mb-2" />
                    <div className="h-4 bg-secondary w-1/3" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : isError ? (
          <Card className="opacity-0 animate-fade-up border-destructive/30">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="h-14 w-14 flex items-center justify-center bg-destructive/10 border border-destructive/20 mb-4">
                <Building2 className="h-7 w-7 text-destructive" />
              </div>
              <h3 className="text-base font-medium">Failed to load distributors</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md text-center">
                Could not connect to the server. Make sure the backend is running on port 8000.
              </p>
              <Button className="mt-6" onClick={() => refetch()} size="sm" variant="outline">
                Try Again
              </Button>
            </CardContent>
          </Card>
        ) : distributors.length === 0 ? (
          <Card className="opacity-0 animate-fade-up">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="h-14 w-14 flex items-center justify-center bg-secondary border border-border mb-4">
                <Building2 className="h-7 w-7 text-muted-foreground" />
              </div>
              <h3 className="text-base font-medium">No distributors yet</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Add your first distributor to start monitoring their channels
              </p>
              <Button className="mt-6" onClick={() => setShowCreate(true)} size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Add Distributor
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {distributors.map((distributor: Distributor, index: number) => (
              <Link key={distributor.id} href={`/distributors/${distributor.id}`}>
                <div 
                  className="stat-card transition-all hover:border-primary/30 group cursor-pointer opacity-0 animate-fade-up"
                  style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className="flex h-12 w-12 items-center justify-center bg-secondary border border-border group-hover:border-primary/30 transition-colors">
                        <Building2 className="h-5 w-5 text-primary" />
                      </div>
                      <div>
                        <div className="flex items-center gap-3">
                          <h3 className="font-medium group-hover:text-primary transition-colors">
                            {distributor.name}
                          </h3>
                          <Badge
                            className={
                              distributor.status === "active"
                                ? "border-success/30 bg-success/10 text-success"
                                : "border-border bg-secondary text-muted-foreground"
                            }
                          >
                            {distributor.status}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-4 mt-1.5 text-xs text-muted-foreground">
                          {distributor.region && (
                            <span className="flex items-center gap-1">
                              <MapPin className="h-3 w-3" />
                              {distributor.region}
                            </span>
                          )}
                          <span className="font-mono">{distributor.match_count} matches</span>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-6">
                      {/* Channel Icons */}
                      <div className="flex items-center gap-3">
                        {distributor.website_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-secondary border border-border">
                            <Globe className="h-4 w-4 text-muted-foreground" />
                          </div>
                        )}
                        {distributor.facebook_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-blue-500/10 border border-blue-500/20">
                            <Facebook className="h-4 w-4 text-blue-400" />
                          </div>
                        )}
                        {distributor.instagram_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-pink-500/10 border border-pink-500/20">
                            <Instagram className="h-4 w-4 text-pink-400" />
                          </div>
                        )}
                        {distributor.youtube_url && (
                          <div className="h-8 w-8 flex items-center justify-center bg-red-500/10 border border-red-500/20">
                            <Youtube className="h-4 w-4 text-red-400" />
                          </div>
                        )}
                      </div>
                      
                      {/* Edit Button */}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => handleStartEdit(distributor, e)}
                        className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      
                      <ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-all group-hover:translate-x-0.5" />
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
