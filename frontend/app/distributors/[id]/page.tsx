"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import {
  ArrowLeft,
  Building2,
  Globe,
  Facebook,
  Instagram,
  Youtube,
  MapPin,
  ImageIcon,
  Trash2,
  Search,
  CheckCircle,
  XCircle,
  Loader2,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { getDistributor, getDistributorMatches, deleteDistributor, lookupGoogleAdsId, setGoogleAdsId } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { getMatchTypeBadge, getComplianceStatusBadge, timeAgo } from "@/lib/utils";

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

interface Match {
  id: string;
  asset_name?: string;
  asset_url?: string;
  confidence_score: number;
  match_type: string;
  compliance_status: string;
  channel?: string;
  created_at: string;
}

export default function DistributorDetailPage() {
  const params = useParams();
  const router = useRouter();
  const distributorId = params.id as string;

  const [distributor, setDistributor] = useState<Distributor | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [lookingUpGoogleAds, setLookingUpGoogleAds] = useState(false);
  const [lookupResult, setLookupResult] = useState<{
    success: boolean;
    message: string;
    advertiser_id?: string;
    search_url?: string;
  } | null>(null);
  const [showManualEntry, setShowManualEntry] = useState(false);
  const [manualAdId, setManualAdId] = useState("");
  const [savingManualId, setSavingManualId] = useState(false);

  useEffect(() => {
    loadDistributor();
  }, [distributorId]);

  const loadDistributor = async () => {
    try {
      const [distData, matchesData] = await Promise.all([
        getDistributor(distributorId),
        getDistributorMatches(distributorId),
      ]);
      setDistributor(distData);
      setMatches(matchesData);
    } catch (error) {
      console.error("Failed to load distributor:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteDistributor(distributorId);
      router.push("/distributors");
    } catch (error) {
      console.error("Failed to delete distributor:", error);
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  const handleLookupGoogleAdsId = async () => {
    setLookingUpGoogleAds(true);
    setLookupResult(null);
    setShowManualEntry(false);
    try {
      const result = await lookupGoogleAdsId(distributorId);
      setLookupResult(result);
      if (result.success && result.advertiser_id) {
        // Refresh distributor data to get the updated ID
        const updatedDistributor = await getDistributor(distributorId);
        setDistributor(updatedDistributor);
      } else {
        // Show manual entry option if auto-lookup failed
        setShowManualEntry(true);
      }
    } catch (error) {
      console.error("Failed to lookup Google Ads ID:", error);
      setLookupResult({
        success: false,
        message: "Failed to lookup Google Ads ID. Please try manually.",
      });
      setShowManualEntry(true);
    } finally {
      setLookingUpGoogleAds(false);
    }
  };

  const handleSaveManualId = async () => {
    if (!manualAdId.trim()) return;
    
    setSavingManualId(true);
    try {
      const result = await setGoogleAdsId(distributorId, manualAdId.trim());
      if (result.success) {
        // Refresh distributor data
        const updatedDistributor = await getDistributor(distributorId);
        setDistributor(updatedDistributor);
        setShowManualEntry(false);
        setManualAdId("");
        setLookupResult(null);
      }
    } catch (error: any) {
      console.error("Failed to save Google Ads ID:", error);
      setLookupResult({
        success: false,
        message: error.response?.data?.detail || "Failed to save. Make sure ID starts with AR followed by numbers.",
      });
    } finally {
      setSavingManualId(false);
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

  if (!distributor) {
    return (
      <div className="min-h-screen">
        <Header title="Distributor Not Found" />
        <div className="p-6">
          <p>The distributor you're looking for doesn't exist.</p>
          <Link href="/distributors">
            <Button className="mt-4">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Distributors
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Header
        title={distributor.name}
        description={distributor.region || "Distributor details"}
      />

      <div className="p-6 space-y-6">
        {/* Back Button */}
        <Link href="/distributors">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Distributors
          </Button>
        </Link>

        {/* Distributor Info */}
        <Card>
          <CardContent className="p-6">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-primary/10">
                  <Building2 className="h-8 w-8 text-primary" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-2xl font-bold">{distributor.name}</h2>
                    <Badge
                      className={
                        distributor.status === "active"
                          ? "bg-green-500/20 text-green-400"
                          : "bg-gray-500/20 text-gray-400"
                      }
                    >
                      {distributor.status}
                    </Badge>
                  </div>
                  {distributor.region && (
                    <p className="text-muted-foreground flex items-center gap-1 mt-1">
                      <MapPin className="h-4 w-4" />
                      {distributor.region}
                    </p>
                  )}
                  {distributor.code && (
                    <p className="text-sm text-muted-foreground mt-1">
                      Code: {distributor.code}
                    </p>
                  )}
                  {/* Google Ads Advertiser ID */}
                  <div className="mt-2">
                    {distributor.google_ads_advertiser_id ? (
                      <div className="flex items-center gap-2">
                        <CheckCircle className="h-4 w-4 text-green-500" />
                        <span className="text-sm">
                          Google Ads ID: <code className="bg-muted px-1.5 py-0.5 rounded text-xs">{distributor.google_ads_advertiser_id}</code>
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setShowManualEntry(true)}
                          className="text-xs h-6"
                        >
                          Edit
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <XCircle className="h-4 w-4 text-orange-500" />
                        <span className="text-sm text-muted-foreground">No Google Ads ID</span>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleLookupGoogleAdsId}
                          disabled={lookingUpGoogleAds}
                        >
                          {lookingUpGoogleAds ? (
                            <>
                              <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                              Looking up...
                            </>
                          ) : (
                            <>
                              <Search className="mr-2 h-3 w-3" />
                              Auto Find
                            </>
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setShowManualEntry(true)}
                        >
                          Enter Manually
                        </Button>
                      </div>
                    )}
                  </div>
                  
                  {/* Lookup Result Message */}
                  {lookupResult && (
                    <div className="mt-2">
                      <p className={`text-sm ${lookupResult.success ? 'text-green-500' : 'text-orange-500'}`}>
                        {lookupResult.message}
                      </p>
                      {lookupResult.search_url && !lookupResult.success && (
                        <a 
                          href={lookupResult.search_url} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-sm text-primary hover:underline"
                        >
                          → Search on Google Ads Transparency
                        </a>
                      )}
                    </div>
                  )}
                  
                  {/* Manual Entry Form */}
                  {showManualEntry && (
                    <div className="mt-3 p-3 rounded-lg border border-border bg-muted/30">
                      <p className="text-sm text-muted-foreground mb-2">
                        Enter the Google Ads Advertiser ID (starts with AR):
                      </p>
                      <div className="flex gap-2">
                        <Input
                          value={manualAdId}
                          onChange={(e) => setManualAdId(e.target.value)}
                          placeholder="AR18135649662495883265"
                          className="flex-1 h-8 text-sm font-mono"
                        />
                        <Button
                          size="sm"
                          onClick={handleSaveManualId}
                          disabled={savingManualId || !manualAdId.trim()}
                        >
                          {savingManualId ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            "Save"
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setShowManualEntry(false);
                            setManualAdId("");
                          }}
                        >
                          Cancel
                        </Button>
                      </div>
                      <p className="text-xs text-muted-foreground mt-2">
                        Find the ID by searching on{" "}
                        <a 
                          href={`https://adstransparency.google.com/?region=anywhere&query=${encodeURIComponent(distributor.name)}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline"
                        >
                          Google Ads Transparency
                        </a>
                        {" "}and copying the AR... from the URL.
                      </p>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-6">
                <div className="text-right">
                  <p className="text-3xl font-bold">{matches.length}</p>
                  <p className="text-muted-foreground">Total Matches</p>
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* Delete Confirmation */}
            {showDeleteConfirm && (
              <div className="mt-4 p-4 rounded-lg border border-destructive/50 bg-destructive/10">
                <p className="font-medium text-destructive">Delete this distributor?</p>
                <p className="text-sm text-muted-foreground mt-1">
                  This will permanently delete the distributor. This action cannot be undone.
                </p>
                <div className="flex gap-2 mt-3">
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? "Deleting..." : "Yes, Delete Distributor"}
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

            {/* Channel Links */}
            <div className="flex flex-wrap gap-3 mt-6 pt-6 border-t border-border">
              {distributor.website_url && (
                <a
                  href={distributor.website_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" size="sm">
                    <Globe className="mr-2 h-4 w-4" />
                    Website
                  </Button>
                </a>
              )}
              {distributor.facebook_url && (
                <a
                  href={distributor.facebook_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" size="sm" className="text-[#1877F2]">
                    <Facebook className="mr-2 h-4 w-4" />
                    Facebook
                  </Button>
                </a>
              )}
              {distributor.instagram_url && (
                <a
                  href={distributor.instagram_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" size="sm" className="text-[#E4405F]">
                    <Instagram className="mr-2 h-4 w-4" />
                    Instagram
                  </Button>
                </a>
              )}
              {distributor.youtube_url && (
                <a
                  href={distributor.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline" size="sm" className="text-[#FF0000]">
                    <Youtube className="mr-2 h-4 w-4" />
                    YouTube
                  </Button>
                </a>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Matches */}
        <Card>
          <CardHeader>
            <CardTitle>Asset Matches ({matches.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {matches.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8">
                <ImageIcon className="h-12 w-12 text-muted-foreground mb-4" />
                <p className="text-muted-foreground">
                  No matches found for this distributor yet
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {matches.map((match) => {
                  const matchBadge = getMatchTypeBadge(match.match_type);
                  const statusBadge = getComplianceStatusBadge(match.compliance_status);

                  return (
                    <Link
                      key={match.id}
                      href={`/matches/${match.id}`}
                      className="flex items-center gap-4 rounded-lg border border-border p-4 transition-colors hover:bg-muted/50"
                    >
                      <div className="relative h-14 w-14 rounded-lg overflow-hidden bg-muted flex-shrink-0">
                        {match.asset_url ? (
                          <Image
                            src={match.asset_url}
                            alt={match.asset_name || "Asset"}
                            fill
                            className="object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center">
                            <ImageIcon className="h-6 w-6 text-muted-foreground" />
                          </div>
                        )}
                      </div>

                      <div className="flex-1 min-w-0">
                        <p className="font-medium truncate">
                          {match.asset_name || "Unknown Asset"}
                        </p>
                        <p className="text-sm text-muted-foreground capitalize">
                          {match.channel?.replace("_", " ") || "Unknown channel"}
                        </p>
                      </div>

                      <div className="w-24">
                        <div className="flex items-center justify-between text-xs mb-1">
                          <span className="text-muted-foreground">Match</span>
                          <span className="font-medium">{match.confidence_score}%</span>
                        </div>
                        <Progress value={match.confidence_score} />
                      </div>

                      <div className="flex flex-col gap-1">
                        <Badge className={matchBadge.className}>
                          {matchBadge.label}
                        </Badge>
                        <Badge className={statusBadge.className}>
                          {statusBadge.label}
                        </Badge>
                      </div>

                      <span className="text-sm text-muted-foreground">
                        {timeAgo(match.created_at)}
                      </span>
                    </Link>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

