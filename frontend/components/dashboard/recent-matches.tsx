"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowRight, ImageIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { getMatchTypeBadge, getComplianceStatusBadge } from "@/lib/utils";

interface Match {
  id: string;
  asset_name?: string;
  asset_url?: string;
  distributor_name?: string;
  confidence_score: number;
  match_type: string;
  compliance_status: string;
  channel?: string;
  created_at: string;
}

interface RecentMatchesProps {
  matches: Match[];
}

export function RecentMatches({ matches }: RecentMatchesProps) {
  return (
    <Card className="opacity-0 animate-fade-up delay-150">
      <CardHeader className="flex flex-row items-center justify-between border-b border-border">
        <div>
          <CardTitle className="flex items-center gap-2 pb-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
            </span>
            Live Audit Feed
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            Latest asset detections across channels
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs font-mono">LIVE</Badge>
        <Link href="/matches">
          <Button variant="ghost" size="sm" className="text-xs">
            View All <ArrowRight className="ml-1.5 h-3 w-3" />
          </Button>
        </Link>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-border max-h-[480px] overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
          {matches.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-5">
              <div className="h-12 w-12 flex items-center justify-center bg-secondary border border-border mb-4">
                <ImageIcon className="h-6 w-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No matches found</p>
              <p className="text-xs text-muted-foreground mt-1">
                Start a scan to discover asset usage
              </p>
            </div>
          ) : (
            matches.map((match, index) => {
              const matchBadge = getMatchTypeBadge(match.match_type);
              const statusBadge = getComplianceStatusBadge(match.compliance_status);
              
              return (
                <Link
                  key={match.id}
                  href={`/matches/${match.id}`}
                  className="flex items-center gap-4 p-4 transition-colors hover:bg-secondary/30 opacity-0 animate-fade-up group"
                  style={{ animationDelay: `${200 + index * 50}ms`, animationFillMode: 'forwards' }}
                >
                  {/* Thumbnail */}
                  <div className="relative h-14 w-14 flex-shrink-0 overflow-hidden bg-secondary border border-border">
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

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-sm font-medium group-hover:text-primary transition-colors">
                      {match.asset_name || "Unknown Asset"}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5 truncate">
                      {match.distributor_name || "Unknown Distributor"}
                    </p>
                  </div>

                  {/* Right Side Info - Always Visible */}
                  <div className="flex flex-col items-stretch gap-2 shrink-0">
                     {/* Badges Row */}
                     <div className="flex items-center gap-1.5">
                        <Badge className={`${matchBadge.className} px-1.5 py-0 text-[10px] h-5`}>
                          {matchBadge.label}
                        </Badge>
                        <Badge className={`${statusBadge.className} px-1.5 py-0 text-[10px] h-5`}>
                          {statusBadge.label}
                        </Badge>
                     </div>
                     
                     {/* Confidence Row - Full width to align with badges */}
                     <div>
                        <div className="flex items-center justify-between text-[10px] mb-1">
                          <span className="text-muted-foreground uppercase tracking-tight">Conf</span>
                          <span className="font-mono font-medium">{match.confidence_score}%</span>
                        </div>
                        <Progress value={match.confidence_score} className="h-1.5" />
                     </div>
                  </div>
                </Link>
              );
            })
          )}
        </div>
      </CardContent>
    </Card>
  );
}
