"use client";

import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatCardProps {
  title: string;
  value: string | number;
  change?: string;
  changeType?: "positive" | "negative" | "neutral";
  icon: LucideIcon;
  iconColor?: string;
}

export function StatCard({
  title,
  value,
  change,
  changeType = "neutral",
  icon: Icon,
  iconColor = "text-primary",
}: StatCardProps) {
  return (
    <div className="stat-card group hover-lift opacity-0 animate-fade-up">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
            {title}
          </p>
          <p className="data-value text-foreground">
            {typeof value === 'number' ? value.toLocaleString() : value}
          </p>
          {change && (
            <p
              className={cn(
                "mt-2 text-xs font-mono",
                changeType === "positive" && "text-success",
                changeType === "negative" && "text-destructive",
                changeType === "neutral" && "text-muted-foreground"
              )}
            >
              {changeType === "positive" && "↑ "}
              {changeType === "negative" && "↓ "}
              {change}
            </p>
          )}
        </div>
        <div className={cn(
          "flex h-10 w-10 items-center justify-center bg-secondary border border-border transition-colors group-hover:border-primary/50",
          iconColor
        )}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}
