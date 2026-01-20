"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import {
  ArrowLeft,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ExternalLink,
  ImageIcon,
  Clock,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { getMatch, approveMatch, flagMatch } from "@/lib/api";
import { getMatchTypeBadge, getComplianceStatusBadge, formatDateTime } from "@/lib/utils";

interface Match {
  id: string;
  asset_name?: string;
  asset_url?: string;
  distributor_name?: string;
  campaign_name?: string;
  confidence_score: number;
  match_type: string;
  compliance_status: string;
  compliance_issues: any[];
  channel?: string;
  source_url?: string;
  screenshot_url?: string;
  discovered_image_url?: string;  // From the view - fallback to discovered_images.image_url
  is_modified: boolean;
  modifications: string[];
  ai_analysis?: any;
  created_at: string;
  discovered_at?: string;
}

export default function MatchDetailPage() {
  const params = useParams();
  const matchId = params.id as string;

  const [match, setMatch] = useState<Match | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadMatch();
  }, [matchId]);

  const loadMatch = async () => {
    try {
      const data = await getMatch(matchId);
      setMatch(data);
    } catch (error) {
      console.error("Failed to load match:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    try {
      await approveMatch(matchId);
      loadMatch();
    } catch (error) {
      console.error("Failed to approve:", error);
    }
  };

  const handleFlag = async () => {
    try {
      await flagMatch(matchId);
      loadMatch();
    } catch (error) {
      console.error("Failed to flag:", error);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen">
        <Header title="Loading..." />
        <div className="p-6">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-muted rounded w-1/3" />
            <div className="h-64 bg-muted rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (!match) {
    return (
      <div className="min-h-screen">
        <Header title="Match Not Found" />
        <div className="p-6">
          <p>The match you're looking for doesn't exist.</p>
          <Link href="/matches">
            <Button className="mt-4">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Matches
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  const matchBadge = getMatchTypeBadge(match.match_type);
  const statusBadge = getComplianceStatusBadge(match.compliance_status);

  return (
    <div className="min-h-screen">
      <Header
        title="Match Detail"
        description={`${match.asset_name || "Asset"} - ${match.distributor_name || "Distributor"}`}
      />

      <div className="p-6 space-y-6">
        {/* Back Button & Actions */}
        <div className="flex items-center justify-between">
          <Link href="/matches">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back to Matches
            </Button>
          </Link>

          {match.compliance_status === "pending" && (
            <div className="flex gap-2">
              <Button variant="success" onClick={handleApprove}>
                <CheckCircle className="mr-2 h-4 w-4" />
                Approve
              </Button>
              <Button variant="destructive" onClick={handleFlag}>
                <XCircle className="mr-2 h-4 w-4" />
                Flag Violation
              </Button>
            </div>
          )}
        </div>

        {/* Status Overview */}
        <Card>
          <CardContent className="p-6">
            <div className="flex flex-wrap items-center gap-4">
              <Badge className={matchBadge.className} style={{ fontSize: "0.875rem", padding: "0.5rem 1rem" }}>
                {matchBadge.label} Match
              </Badge>
              <Badge className={statusBadge.className} style={{ fontSize: "0.875rem", padding: "0.5rem 1rem" }}>
                {statusBadge.label}
              </Badge>
              {match.is_modified && (
                <Badge className="bg-yellow-500/20 text-yellow-400" style={{ fontSize: "0.875rem", padding: "0.5rem 1rem" }}>
                  Modified
                </Badge>
              )}
            </div>

            <div className="grid gap-6 md:grid-cols-3 mt-6">
              <div>
                <p className="text-sm text-muted-foreground">Confidence Score</p>
                <div className="mt-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-2xl font-bold">{match.confidence_score}%</span>
                  </div>
                  <Progress value={match.confidence_score} className="h-3" />
                </div>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Channel</p>
                <p className="text-lg font-medium capitalize mt-1">
                  {match.channel?.replace("_", " ") || "Unknown"}
                </p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Discovered</p>
                <p className="text-lg font-medium mt-1 flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  {formatDateTime(match.discovered_at || match.created_at)}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Image Comparison */}
        <div className="grid gap-6 md:grid-cols-2">
          {/* Approved Asset */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CheckCircle className="h-5 w-5 text-green-400" />
                Approved Asset
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="relative aspect-video rounded-lg overflow-hidden bg-muted">
                {match.asset_url ? (
                  <Image
                    src={match.asset_url}
                    alt={match.asset_name || "Approved Asset"}
                    fill
                    className="object-contain"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center">
                    <ImageIcon className="h-12 w-12 text-muted-foreground" />
                  </div>
                )}
              </div>
              <div className="mt-4">
                <p className="font-medium">{match.asset_name || "Unknown Asset"}</p>
                <p className="text-sm text-muted-foreground">{match.campaign_name}</p>
              </div>
            </CardContent>
          </Card>

          {/* Discovered Execution */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-yellow-400" />
                Discovered Image
              </CardTitle>
            </CardHeader>
            <CardContent>
              {/* Use discovered_image_url which falls back to discovered_images.image_url */}
              {(match.discovered_image_url || match.screenshot_url) ? (
                <a 
                  href={match.discovered_image_url || match.screenshot_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="block"
                >
                  <div className="relative aspect-video rounded-lg overflow-hidden bg-muted hover:ring-2 hover:ring-primary transition-all cursor-zoom-in">
                    <Image
                      src={match.discovered_image_url || match.screenshot_url || ""}
                      alt="Discovered"
                      fill
                      className="object-contain"
                    />
                  </div>
                </a>
              ) : (
                <div className="relative aspect-video rounded-lg overflow-hidden bg-muted">
                  <div className="flex h-full w-full items-center justify-center flex-col gap-2">
                    <ImageIcon className="h-12 w-12 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground">No image available</p>
                  </div>
                </div>
              )}
              <div className="mt-4">
                <p className="font-medium">{match.distributor_name || "Unknown Distributor"}</p>
                <p className="text-xs text-muted-foreground mt-1">Click image to view full size</p>
                {match.source_url && (
                  <a
                    href={match.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-primary hover:underline flex items-center gap-1 mt-2"
                  >
                    View Original Page <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Compliance Check Results */}
        <Card>
          <CardHeader>
            <CardTitle>Compliance Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            {match.compliance_issues && match.compliance_issues.length > 0 ? (
              <div className="space-y-3">
                {match.compliance_issues.map((issue: any, index: number) => {
                  const isAnalysisError = issue.type === "analysis_error";
                  return (
                    <div
                      key={index}
                      className={`flex items-start gap-3 p-3 rounded-lg ${
                        isAnalysisError 
                          ? "bg-yellow-500/10 border border-yellow-500/20" 
                          : "bg-red-500/10 border border-red-500/20"
                      }`}
                    >
                      {isAnalysisError ? (
                        <AlertTriangle className="h-5 w-5 text-yellow-400 mt-0.5" />
                      ) : (
                        <XCircle className="h-5 w-5 text-red-400 mt-0.5" />
                      )}
                      <div>
                        <p className={`font-medium capitalize ${isAnalysisError ? "text-yellow-400" : "text-red-400"}`}>
                          {isAnalysisError ? "Analysis Error" : (issue.type?.replace("_", " ") || "Issue")}
                        </p>
                        <p className="text-sm text-muted-foreground">
                          {isAnalysisError 
                            ? "The AI analysis encountered a temporary error. The system will retry automatically on the next scan."
                            : (issue.element || issue.message || issue.reason || "Compliance issue detected")
                          }
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : match.compliance_status === "compliant" ? (
              <div className="flex items-center gap-3 p-4 rounded-lg bg-green-500/10 border border-green-500/20">
                <CheckCircle className="h-6 w-6 text-green-400" />
                <div>
                  <p className="font-medium text-green-400">All Checks Passed</p>
                  <p className="text-sm text-muted-foreground">
                    This asset execution meets all compliance requirements
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground">No compliance data available</p>
            )}

            {/* Modifications */}
            {match.modifications && match.modifications.length > 0 && (
              <div className="mt-6 pt-6 border-t border-border">
                <h4 className="font-medium mb-3">Detected Modifications</h4>
                <div className="flex flex-wrap gap-2">
                  {match.modifications.map((mod: string, index: number) => (
                    <Badge key={index} variant="outline" className="capitalize">
                      {mod.replace("_", " ")}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* AI Analysis Summary */}
            {match.ai_analysis?.compliance?.summary && (
              <div className="mt-6 pt-6 border-t border-border">
                <h4 className="font-medium mb-3">AI Analysis Summary</h4>
                {match.ai_analysis.compliance.summary.startsWith("Analysis failed:") ? (
                  <div className="flex items-start gap-2 text-yellow-400/80">
                    <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                    <p className="text-sm">
                      AI analysis could not be completed due to a temporary service issue. 
                      The analysis will be automatically retried on the next scan.
                    </p>
                  </div>
                ) : (
                  <p className="text-muted-foreground">
                    {match.ai_analysis.compliance.summary}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}









