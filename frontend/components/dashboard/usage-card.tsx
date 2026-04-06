"use client";

import { Building2, Megaphone, ScanSearch, Gauge } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface UsageRow {
  label: string;
  current: number;
  max: number | null;
  icon: React.ReactNode;
  period?: string;
}

interface UsageCardProps {
  dealers: { current: number; max: number | null };
  campaigns: { current: number; max: number | null };
  scans: { current: number; max: number | null; period?: string };
  plan: string;
}

function UsageMeter({ row }: { row: UsageRow }) {
  const unlimited = row.max === null || row.max === undefined;
  const pct = unlimited ? 0 : Math.min(100, (row.current / row.max!) * 100);
  const atLimit = !unlimited && row.current >= row.max!;
  const nearLimit = !unlimited && pct >= 80 && !atLimit;

  const barColor = atLimit
    ? "bg-destructive"
    : nearLimit
    ? "bg-amber-500"
    : "bg-primary";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {row.icon}
          <span>{row.label}</span>
          {row.period && (
            <span className="text-2xs font-mono text-muted-foreground/60 uppercase">
              {row.period}
            </span>
          )}
        </div>
        <span className="text-sm font-mono tabular-nums">
          {row.current}
          <span className="text-muted-foreground">
            /{unlimited ? "∞" : row.max}
          </span>
        </span>
      </div>
      {!unlimited && (
        <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}

export function UsageCard({ dealers, campaigns, scans, plan }: UsageCardProps) {
  const planLabel = plan === "free"
    ? "Free Trial"
    : plan.charAt(0).toUpperCase() + plan.slice(1);

  const rows: UsageRow[] = [
    {
      label: "Dealers",
      current: dealers.current,
      max: dealers.max,
      icon: <Building2 className="h-4 w-4" />,
    },
    {
      label: "Campaigns",
      current: campaigns.current,
      max: campaigns.max,
      icon: <Megaphone className="h-4 w-4" />,
    },
    {
      label: "Scans",
      current: scans.current,
      max: scans.max,
      icon: <ScanSearch className="h-4 w-4" />,
      period: scans.period === "this_month" ? "/ mo" : scans.period === "total" ? "total" : undefined,
    },
  ];

  return (
    <Card className="border border-border bg-card opacity-0 animate-fade-up">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Gauge className="h-4 w-4 text-info" />
            Plan Usage
          </CardTitle>
          <span className="text-2xs font-mono uppercase tracking-wider text-info bg-info/10 px-2 py-0.5">
            {planLabel}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {rows.map((row) => (
          <UsageMeter key={row.label} row={row} />
        ))}
      </CardContent>
    </Card>
  );
}
