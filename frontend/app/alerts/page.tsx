"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Bell,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Shield,
  Eye,
  Trash2,
  CheckCheck,
  Filter,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn, timeAgo } from "@/lib/utils";
import {
  useAlerts,
  useMarkAlertRead,
  useMarkAllAlertsRead,
  useDeleteAlert,
  useUnreadAlertCount,
} from "@/lib/hooks";

interface Alert {
  id: string;
  alert_type: string;
  severity: string;
  title: string;
  description: string | null;
  created_at: string;
  is_read: boolean;
  match_id: string | null;
  distributor_id: string | null;
  distributors?: { name: string };
  matches?: { confidence_score: number };
}

const alertIcons: Record<string, typeof AlertTriangle> = {
  compliance_violation: XCircle,
  zombie_ad: Clock,
  modified_asset: AlertTriangle,
};

const severityConfig: Record<string, { label: string; style: string; dot: string }> = {
  critical: {
    label: "Critical",
    style: "text-red-400 bg-red-500/10 border-red-500/20",
    dot: "bg-red-400",
  },
  warning: {
    label: "Warning",
    style: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    dot: "bg-amber-400",
  },
  info: {
    label: "Info",
    style: "text-blue-400 bg-blue-500/10 border-blue-500/20",
    dot: "bg-blue-400",
  },
};

type FilterMode = "all" | "unread";

export default function AlertsPage() {
  const [filter, setFilter] = useState<FilterMode>("all");
  const { data: alerts = [], isLoading } = useAlerts(filter === "unread");
  const { data: countData } = useUnreadAlertCount();
  const markReadMutation = useMarkAlertRead();
  const markAllReadMutation = useMarkAllAlertsRead();
  const deleteMutation = useDeleteAlert();

  const unreadCount = countData?.unread_count ?? 0;

  return (
    <div className="min-h-screen">
      <Header
        title="Alerts"
        description="Compliance alerts and notifications"
      />

      <div className="p-6 space-y-6">
        {/* Toolbar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button
              variant={filter === "all" ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter("all")}
            >
              All Alerts
            </Button>
            <Button
              variant={filter === "unread" ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter("unread")}
            >
              <Bell className="h-3.5 w-3.5 mr-1.5" />
              Unread
              {unreadCount > 0 && (
                <span className="ml-1.5 flex h-4 min-w-4 px-1 items-center justify-center bg-destructive text-[10px] font-mono text-white rounded-full">
                  {unreadCount}
                </span>
              )}
            </Button>
          </div>

          {unreadCount > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => markAllReadMutation.mutate()}
              disabled={markAllReadMutation.isPending}
            >
              <CheckCheck className="h-3.5 w-3.5 mr-1.5" />
              {markAllReadMutation.isPending ? "Marking..." : "Mark All Read"}
            </Button>
          )}
        </div>

        {/* Alert List */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Card key={i} className="animate-pulse">
                <CardContent className="p-6">
                  <div className="h-5 bg-muted rounded w-1/3 mb-2" />
                  <div className="h-4 bg-muted rounded w-2/3" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : alerts.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="flex h-14 w-14 items-center justify-center bg-success/10 border border-success/20 mb-4">
                <CheckCircle className="h-7 w-7 text-success" />
              </div>
              <h3 className="text-lg font-medium">All Clear</h3>
              <p className="text-sm text-muted-foreground mt-1">
                {filter === "unread"
                  ? "No unread alerts. You're all caught up."
                  : "No compliance alerts to display."}
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {alerts.map((alert: Alert) => {
              const Icon = alertIcons[alert.alert_type] || AlertTriangle;
              const severity = severityConfig[alert.severity] || severityConfig.info;

              return (
                <Card
                  key={alert.id}
                  className={cn(
                    "transition-colors",
                    !alert.is_read && "border-l-2 border-l-primary bg-secondary/20"
                  )}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-4">
                      <div className={cn("flex h-10 w-10 items-center justify-center border flex-shrink-0", severity.style)}>
                        <Icon className="h-5 w-5" />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <p className={cn("text-sm font-medium", !alert.is_read && "text-foreground")}>
                            {alert.title}
                          </p>
                          {!alert.is_read && (
                            <div className={cn("w-2 h-2 rounded-full flex-shrink-0", severity.dot)} />
                          )}
                          <Badge variant="outline" className={cn("text-2xs ml-auto flex-shrink-0", severity.style)}>
                            {severity.label}
                          </Badge>
                        </div>

                        {alert.description && (
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            {alert.description}
                          </p>
                        )}

                        <div className="flex items-center gap-3 mt-2">
                          <span className="text-2xs text-muted-foreground font-mono">
                            {timeAgo(alert.created_at)}
                          </span>
                          {alert.distributors?.name && (
                            <span className="text-2xs text-muted-foreground">
                              Dealer: {alert.distributors.name}
                            </span>
                          )}
                          {alert.matches?.confidence_score != null && (
                            <span className="text-2xs text-muted-foreground font-mono">
                              {Math.round(alert.matches.confidence_score)}% confidence
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-1 flex-shrink-0">
                        {alert.match_id && (
                          <Link href={`/matches?highlight=${alert.match_id}`}>
                            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" title="View match">
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                          </Link>
                        )}
                        {!alert.is_read && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0"
                            title="Mark as read"
                            onClick={() => markReadMutation.mutate(alert.id)}
                            disabled={markReadMutation.isPending}
                          >
                            <CheckCircle className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                          title="Delete alert"
                          onClick={() => {
                            if (confirm("Delete this alert?")) {
                              deleteMutation.mutate(alert.id);
                            }
                          }}
                          disabled={deleteMutation.isPending}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
