"use client";

import { useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import {
  Search,
  ImageIcon,
  CheckCircle,
  XCircle,
  Eye,
  Trash2,
  Layers,
  ThumbsUp,
  ThumbsDown,
  Download,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useMatches, useMatchStats, useApproveMatch, useFlagMatch, useDeleteMatch, useDeleteAllMatches, useSubmitFeedback } from "@/lib/hooks";
import { downloadComplianceReport } from "@/lib/api";
import {
  timeAgo,
  getMatchTypeBadge,
  getComplianceStatusBadge,
} from "@/lib/utils";

import { AssetThumbnail } from "@/components/asset-thumbnail";

interface Match {
  id: string;
  asset_id?: string | null;
  asset_name: string | null;
  asset_url: string | null;
  screenshot_url: string | null;
  discovered_image_url?: string;
  distributor_name: string | null;
  campaign_name: string | null;
  confidence_score: number;
  match_type: string;
  compliance_status: string;
  channel: string | null;
  source_url: string | null;
  created_at: string;
  is_modified: boolean;
}

function MatchesContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const statusFilter = searchParams.get("status") || "";
  
  const { data: matches = [], isLoading: loading } = useMatches(
    statusFilter ? { status: statusFilter } : undefined
  );
  const { data: rawStats } = useMatchStats();
  const stats = (rawStats as any) || {
    total_matches: 0,
    compliant: 0,
    violations: 0,
    pending_review: 0,
    compliance_rate: 0,
  };
  const approveMutation = useApproveMatch();
  const flagMutation = useFlagMatch();
  const deleteMatchMutation = useDeleteMatch();
  const deleteAllMatchesMutation = useDeleteAllMatches();
  const feedbackMutation = useSubmitFeedback();
  const [searchFilter, setSearchFilter] = useState("");
  const [feedbackGiven, setFeedbackGiven] = useState<Record<string, "correct" | "incorrect">>({});
  const [downloading, setDownloading] = useState<string | null>(null);

  const handleDownload = async (format: "pdf" | "csv") => {
    setDownloading(format);
    try {
      await downloadComplianceReport(format);
    } catch (error) {
      console.error("Download failed:", error);
    } finally {
      setDownloading(null);
    }
  };
  
  const handleStatusFilter = (status: string) => {
    if (status) {
      router.push(`/matches?status=${status}`);
    } else {
      router.push("/matches");
    }
  };

  const handleApprove = async (id: string) => {
    try {
      await approveMutation.mutateAsync(id);
    } catch (error: any) {
      console.error("Failed to approve:", error);
      alert(error?.response?.data?.detail || "Failed to approve match.");
    }
  };

  const handleFlag = async (id: string) => {
    try {
      await flagMutation.mutateAsync({ id });
    } catch (error: any) {
      console.error("Failed to flag:", error);
      alert(error?.response?.data?.detail || "Failed to flag match.");
    }
  };

  const handleDeleteMatch = async (id: string) => {
    if (confirm("Delete this match?")) {
      try {
        await deleteMatchMutation.mutateAsync(id);
      } catch (error: any) {
        console.error("Failed to delete match:", error);
        alert(error?.response?.data?.detail || "Failed to delete match.");
      }
    }
  };

  const handleDeleteAllMatches = async () => {
    if (confirm("Delete ALL matches? This cannot be undone.")) {
      try {
        await deleteAllMatchesMutation.mutateAsync();
      } catch (error: any) {
        console.error("Failed to delete all matches:", error);
        alert(error?.response?.data?.detail || "Failed to delete matches.");
      }
    }
  };

  const handleFeedback = async (id: string, wasCorrect: boolean) => {
    try {
      await feedbackMutation.mutateAsync({
        matchId: id,
        feedback: {
          was_correct: wasCorrect,
          actual_verdict: wasCorrect ? "true_positive" : "false_positive",
        },
      });
      setFeedbackGiven((prev) => ({ ...prev, [id]: wasCorrect ? "correct" : "incorrect" }));
    } catch (error: any) {
      console.error("Failed to submit feedback:", error);
      alert(error?.response?.data?.detail || "Failed to submit feedback.");
    }
  };

  const filteredMatches = matches.filter(
    (m: Match) =>
      m.asset_name?.toLowerCase().includes(searchFilter.toLowerCase()) ||
      m.distributor_name?.toLowerCase().includes(searchFilter.toLowerCase())
  );

  return (
    <div className="min-h-screen">
      <Header
        title="Matches"
        description="Review and manage discovered asset matches"
      />

      <div className="p-8 space-y-6">
        {/* Stats Cards */}
        <div className="grid gap-4 md:grid-cols-4">
          {[
            { label: "Total Matches", value: stats.total_matches, color: "text-foreground" },
            { label: "Compliant", value: stats.compliant, color: "text-success" },
            { label: "Violations", value: stats.violations, color: "text-destructive" },
            { label: "Compliance Rate", value: `${stats.compliance_rate}%`, color: "text-primary" },
          ].map((stat, index) => (
            <div 
              key={stat.label} 
              className="stat-card opacity-0 animate-fade-up"
              style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
            >
              <p className="text-2xs uppercase tracking-wider text-muted-foreground">{stat.label}</p>
              <p className={`data-value mt-2 ${stat.color}`}>{stat.value}</p>
            </div>
          ))}
        </div>

        {/* Status Filter Tabs */}
        <div className="flex items-center gap-2 opacity-0 animate-fade-up delay-100">
          <Button
            variant={!statusFilter ? "default" : "outline"}
            size="sm"
            onClick={() => handleStatusFilter("")}
          >
            All Matches
          </Button>
          <Button
            variant={statusFilter === "compliant" ? "default" : "outline"}
            size="sm"
            onClick={() => handleStatusFilter("compliant")}
            className={statusFilter === "compliant" ? "" : "text-success hover:text-success hover:border-success/50"}
          >
            <CheckCircle className="mr-2 h-3.5 w-3.5" />
            Compliant ({stats.compliant})
          </Button>
          <Button
            variant={statusFilter === "violation" ? "default" : "outline"}
            size="sm"
            onClick={() => handleStatusFilter("violation")}
            className={statusFilter === "violation" ? "" : "text-destructive hover:text-destructive hover:border-destructive/50"}
          >
            <XCircle className="mr-2 h-3.5 w-3.5" />
            Violations ({stats.violations})
          </Button>
          <Button
            variant={statusFilter === "pending" ? "default" : "outline"}
            size="sm"
            onClick={() => handleStatusFilter("pending")}
          >
            Pending Review ({stats.pending_review})
          </Button>
        </div>

        {/* Search & Actions */}
        <div className="flex items-center gap-3 opacity-0 animate-fade-up delay-150">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by asset or distributor..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="pl-9 h-9"
            />
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleDownload("pdf")}
              disabled={downloading !== null}
            >
              <Download className="mr-2 h-3.5 w-3.5" />
              {downloading === "pdf" ? "Generating..." : "PDF"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleDownload("csv")}
              disabled={downloading !== null}
            >
              <Download className="mr-2 h-3.5 w-3.5" />
              {downloading === "csv" ? "Generating..." : "CSV"}
            </Button>
            {matches.length > 0 && (
              <Button 
                variant="outline"
                size="sm"
                onClick={handleDeleteAllMatches}
                disabled={deleteAllMatchesMutation.isPending}
                className="text-destructive hover:text-destructive hover:border-destructive/50"
              >
                <Trash2 className="mr-2 h-3.5 w-3.5" />
                Delete All
              </Button>
            )}
          </div>
        </div>

        {/* Matches Table */}
        <Card className="opacity-0 animate-fade-up delay-225">
          <CardContent className="p-0">
            {loading ? (
              <div className="p-12 text-center text-muted-foreground text-sm">
                Loading matches...
              </div>
            ) : filteredMatches.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16">
                <div className="h-14 w-14 flex items-center justify-center bg-secondary border border-border mb-4">
                  <Layers className="h-7 w-7 text-muted-foreground" />
                </div>
                <p className="text-sm text-muted-foreground">
                  {searchFilter ? "No matches found for your search" : 
                   statusFilter ? `No ${statusFilter} matches found` : "No matches found yet"}
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Comparison</TableHead>
                    <TableHead>Asset</TableHead>
                    <TableHead>Distributor</TableHead>
                    <TableHead>Channel</TableHead>
                    <TableHead>Confidence</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Discovered</TableHead>
                    <TableHead>Feedback</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredMatches.map((match: Match, index: number) => {
                    const matchBadge = getMatchTypeBadge(match.match_type);
                    const statusBadge = getComplianceStatusBadge(match.compliance_status);

                    return (
                      <TableRow 
                        key={match.id}
                        className="opacity-0 animate-fade-up cursor-pointer hover:bg-secondary/50 transition-colors"
                        style={{ animationDelay: `${250 + index * 30}ms`, animationFillMode: 'forwards' }}
                        onClick={() => router.push(`/matches/${match.id}`)}
                      >
                        {/* Visual Comparison - Asset vs Discovered */}
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {/* Asset Thumbnail */}
                            <div className="relative h-12 w-12 overflow-hidden bg-secondary border-2 border-success/40 flex-shrink-0">
                              {match.asset_id ? (
                                <AssetThumbnail
                                  assetId={match.asset_id}
                                  alt={match.asset_name || "Asset"}
                                />
                              ) : (
                                <div className="flex h-full w-full items-center justify-center">
                                  <ImageIcon className="h-4 w-4 text-muted-foreground" />
                                </div>
                              )}
                            </div>
                            <span className="text-2xs text-muted-foreground font-mono">vs</span>
                            {/* Discovered Image Thumbnail */}
                            <div className="relative h-12 w-12 overflow-hidden bg-secondary border-2 border-primary/40 flex-shrink-0">
                              {(match.discovered_image_url || match.screenshot_url) ? (
                                <Image
                                  src={match.discovered_image_url || match.screenshot_url || ""}
                                  alt="Discovered"
                                  fill
                                  className="object-cover"
                                />
                              ) : (
                                <div className="flex h-full w-full items-center justify-center">
                                  <ImageIcon className="h-4 w-4 text-muted-foreground" />
                                </div>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div>
                            <p className="font-medium text-sm">
                              {match.asset_name || "Unknown"}
                            </p>
                            {match.campaign_name && (
                              <p className="text-2xs text-muted-foreground mt-0.5">
                                {match.campaign_name}
                              </p>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm">
                            {match.distributor_name || "Unknown"}
                          </span>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm capitalize">
                            {match.channel?.replace("_", " ") || "-"}
                          </span>
                        </TableCell>
                        <TableCell>
                          <div className="w-20">
                            <div className="flex items-center justify-between text-2xs mb-1.5">
                              <span className="font-mono font-medium">{match.confidence_score}%</span>
                            </div>
                            <Progress value={match.confidence_score} />
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge className={statusBadge.className}>
                            {statusBadge.label}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <span className="text-xs text-muted-foreground font-mono">
                            {timeAgo(match.created_at)}
                          </span>
                        </TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          {feedbackGiven[match.id] ? (
                            <Badge className={
                              feedbackGiven[match.id] === "correct"
                                ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
                                : "bg-amber-500/20 text-amber-400 border-amber-500/30"
                            }>
                              {feedbackGiven[match.id] === "correct" ? (
                                <><ThumbsUp className="h-3 w-3 mr-1" /> Correct</>
                              ) : (
                                <><ThumbsDown className="h-3 w-3 mr-1" /> Wrong</>
                              )}
                            </Badge>
                          ) : (
                            <div className="flex gap-0.5">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10"
                                onClick={() => handleFeedback(match.id, true)}
                                disabled={feedbackMutation.isPending}
                                title="Correct match"
                              >
                                <ThumbsUp className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-amber-400 hover:text-amber-300 hover:bg-amber-500/10"
                                onClick={() => handleFeedback(match.id, false)}
                                disabled={feedbackMutation.isPending}
                                title="Incorrect match"
                              >
                                <ThumbsDown className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          )}
                        </TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1">
                            <Link href={`/matches/${match.id}`}>
                              <Button variant="ghost" size="icon" className="h-8 w-8">
                                <Eye className="h-4 w-4" />
                              </Button>
                            </Link>
                            {match.compliance_status === "pending" && (
                              <>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-success hover:text-success hover:bg-success/10"
                                  onClick={() => handleApprove(match.id)}
                                  disabled={approveMutation.isPending}
                                >
                                  <CheckCircle className="h-4 w-4" />
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                                  onClick={() => handleFlag(match.id)}
                                  disabled={flagMutation.isPending}
                                >
                                  <XCircle className="h-4 w-4" />
                                </Button>
                              </>
                            )}
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                              onClick={() => handleDeleteMatch(match.id)}
                              disabled={deleteMatchMutation.isPending}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function MatchesLoading() {
  return (
    <div className="min-h-screen">
      <Header
        title="Matches"
        description="Review and manage discovered asset matches"
      />
      <div className="p-8">
        <div className="p-12 text-center text-muted-foreground text-sm">
          Loading...
        </div>
      </div>
    </div>
  );
}

export default function MatchesPage() {
  return (
    <Suspense fallback={<MatchesLoading />}>
      <MatchesContent />
    </Suspense>
  );
}
