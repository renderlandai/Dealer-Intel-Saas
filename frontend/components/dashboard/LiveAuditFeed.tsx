"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { formatDistanceToNow } from "date-fns";
import { AlertTriangle, CheckCircle, Search } from "lucide-react";

interface Match {
  id: string;
  created_at: string;
  compliance_status: string;
  confidence: number;
  distributor?: {
    name: string;
  };
  campaign?: {
    name: string;
  };
}

interface LiveAuditFeedProps {
  initialMatches: Match[];
}

export function LiveAuditFeed({ initialMatches }: LiveAuditFeedProps) {
  const [matches, setMatches] = useState<Match[]>(initialMatches);

  // Simulate incoming live events for "War Room" feel
  useEffect(() => {
    // In a real app, this would be a websocket subscription
    // For now, we'll just periodically cycle the list to simulate movement
    const interval = setInterval(() => {
      setMatches(prev => {
        if (prev.length === 0) return prev;
        const [first, ...rest] = prev;
        // Move first to end to create "infinite" cycle effect or just shuffle
        return [...rest, { ...first, created_at: new Date().toISOString() }]; 
      });
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="h-[400px] border border-border rounded-lg bg-card flex flex-col overflow-hidden">
      <div className="p-4 border-b border-border bg-muted/30 flex items-center justify-between">
        <h3 className="font-semibold text-sm flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>
          </span>
          Live Audit Feed
        </h3>
        <Badge variant="outline" className="text-xs font-mono">LIVE</Badge>
      </div>
      
      <div className="flex-1 overflow-hidden relative">
        <div className="absolute inset-0 overflow-y-auto p-4 space-y-4 no-scrollbar">
          {matches.map((match, i) => (
            <div key={`${match.id}-${i}`} className="flex gap-4 p-3 rounded-lg border border-border/50 bg-background/50 hover:bg-accent transition-colors animate-in fade-in slide-in-from-bottom-2 duration-500">
              <div className="mt-1">
                {match.compliance_status === 'compliant' ? (
                  <div className="h-8 w-8 rounded-full bg-green-500/10 flex items-center justify-center border border-green-500/20">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                  </div>
                ) : match.compliance_status === 'violation' ? (
                  <div className="h-8 w-8 rounded-full bg-red-500/10 flex items-center justify-center border border-red-500/20">
                    <AlertTriangle className="h-4 w-4 text-red-500" />
                  </div>
                ) : (
                  <div className="h-8 w-8 rounded-full bg-blue-500/10 flex items-center justify-center border border-blue-500/20">
                    <Search className="h-4 w-4 text-blue-500" />
                  </div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-medium truncate">
                    {match.distributor?.name || "Unknown Distributor"}
                  </p>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {formatDistanceToNow(new Date(match.created_at), { addSuffix: true })}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground truncate mb-2">
                  Campaign: {match.campaign?.name || "General Scan"}
                </p>
                <div className="flex items-center gap-2">
                  <Badge variant={match.compliance_status === 'compliant' ? 'default' : 'destructive'} className="text-[10px] h-5 px-1.5">
                    {match.compliance_status?.toUpperCase() || "PENDING"}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground font-mono">
                    CONF: {Math.round((match.confidence || 0) * 100)}%
                  </span>
                </div>
              </div>
            </div>
          ))}
          {matches.length === 0 && (
            <div className="text-center py-10 text-muted-foreground text-sm">
              Waiting for incoming audits...
            </div>
          )}
        </div>
        {/* Gradient fade at bottom */}
        <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-card to-transparent pointer-events-none" />
      </div>
    </div>
  );
}

