"use client";

import { useState } from "react";
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
import { useMatches, useMatchStats, useApproveMatch, useFlagMatch, useDeleteMatch, useDeleteAllMatches } from "@/lib/hooks";
import {
  timeAgo,
  getMatchTypeBadge,
  getComplianceStatusBadge,
} from "@/lib/utils";

interface Match {
  id: string;
  asset_name?: string;
  asset_url?: string;
  screenshot_url?: string;
  discovered_image_url?: string;
  distributor_name?: string;
  campaign_name?: string;
  confidence_score: number;
  match_type: string;
  compliance_status: string;
  channel?: string;
  source_url?: string;
  created_at: string;
  is_modified: boolean;
}

export default function MatchesPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const statusFilter = searchParams.get("status") || "";
  
  const { data: matches = [], isLoading: loading } = useMatches(
    statusFilter ? { status: statusFilter } : undefined
  );
  const { data: stats = {
    total_matches: 0,
    compliant: 0,
    violations: 0,
    pending_review: 0,
    compliance_rate: 0,
  } } = useMatchStats();
  const approveMutation = useApproveMatch();
  const flagMutation = useFlagMatch();
  const deleteMatchMutation = useDeleteMatch();
  const deleteAllMatchesMutation = useDeleteAllMatches();
  const [searchFilter, setSearchFilter] = useState("");
  
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
    } catch (error) {
      console.error("Failed to approve:", error);
    }
  };

  const handleFlag = async (id: string) => {
    try {
      await flagMutation.mutateAsync({ id });
    } catch (error) {
      console.error("Failed to flag:", error);
    }
  };

  const handleDeleteMatch = async (id: string) => {
    if (confirm("Delete this match?")) {
      try {
        await deleteMatchMutation.mutateAsync(id);
      } catch (error) {
        console.error("Failed to delete match:", error);
      }
    }
  };

  const handleDeleteAllMatches = async () => {
    if (confirm("Delete ALL matches? This cannot be undone.")) {
      try {
        await deleteAllMatchesMutation.mutateAsync();
      } catch (error) {
        console.error("Failed to delete all matches:", error);
      }
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
                        className="opacity-0 animate-fade-up"
                        style={{ animationDelay: `${250 + index * 30}ms`, animationFillMode: 'forwards' }}
                      >
                        {/* Visual Comparison - Asset vs Discovered */}
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {/* Asset Thumbnail */}
                            <div className="relative h-12 w-12 overflow-hidden bg-secondary border-2 border-success/40 flex-shrink-0">
                              {match.asset_url ? (
                                <Image
                                  src={match.asset_url}
                                  alt={match.asset_name || "Asset"}
                                  fill
                                  className="object-cover"
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
                        <TableCell>
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
