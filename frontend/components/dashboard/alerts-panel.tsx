"use client";

import Link from "next/link";
import { AlertTriangle, CheckCircle, XCircle, Clock, Shield } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, timeAgo } from "@/lib/utils";

interface Alert {
  id: string;
  alert_type: string;
  severity: string;
  title: string;
  description: string | null;
  created_at: string;
  is_read: boolean;
  match_id: string | null;
}

interface AlertsPanelProps {
  alerts: Alert[];
}

const alertIcons = {
  compliance_violation: XCircle,
  zombie_ad: Clock,
  modified_asset: AlertTriangle,
  default: AlertTriangle,
};

const severityStyles = {
  critical: "text-red-400 bg-red-500/10 border-red-500/20",
  warning: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  info: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  default: "text-muted-foreground bg-secondary border-border",
};

export function AlertsPanel({ alerts }: AlertsPanelProps) {
  return (
    <Card className="opacity-0 animate-fade-up delay-225">
      <CardHeader className="border-b border-border">
        <CardTitle className="flex items-center gap-2 accent-line pb-2">
          <Shield className="h-4 w-4 text-primary" />
          Compliance Alerts
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-border">
          {alerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center px-5">
              <div className="h-12 w-12 flex items-center justify-center bg-success/10 border border-success/20 mb-4">
                <CheckCircle className="h-6 w-6 text-success" />
              </div>
              <p className="text-sm font-medium">All Clear</p>
              <p className="text-xs text-muted-foreground mt-1">
                No compliance issues detected
              </p>
            </div>
          ) : (
            alerts.map((alert, index) => {
              const Icon = alertIcons[alert.alert_type as keyof typeof alertIcons] || alertIcons.default;
              const styleClass = severityStyles[alert.severity as keyof typeof severityStyles] || severityStyles.default;

              const alertContent = (
                <div
                  className={cn(
                    "flex items-start gap-3 p-4 transition-colors hover:bg-secondary/30 cursor-pointer opacity-0 animate-fade-up",
                    !alert.is_read && "bg-secondary/20"
                  )}
                  style={{ animationDelay: `${250 + index * 50}ms`, animationFillMode: 'forwards' }}
                >
                  <div className={cn("flex h-8 w-8 items-center justify-center border", styleClass)}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-sm">{alert.title}</p>
                      {!alert.is_read && (
                        <span className="status-dot error" />
                      )}
                    </div>
                    {alert.description && (
                      <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                        {alert.description}
                      </p>
                    )}
                    <p className="text-2xs text-muted-foreground mt-2 font-mono">
                      {timeAgo(alert.created_at)}
                    </p>
                  </div>
                </div>
              );

              return alert.match_id ? (
                <Link key={alert.id} href={`/matches/${alert.match_id}`}>
                  {alertContent}
                </Link>
              ) : (
                <div key={alert.id}>{alertContent}</div>
              );
            })
          )}
        </div>
      </CardContent>
    </Card>
  );
}
