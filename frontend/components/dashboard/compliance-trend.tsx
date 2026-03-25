"use client";

import { useState } from "react";
import { TrendingUp, Lock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useComplianceTrend } from "@/lib/hooks";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface ComplianceTrendProps {
  enabled: boolean;
}

const PERIOD_OPTIONS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
] as const;

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;

  return (
    <div className="bg-card border border-border p-3 shadow-lg text-xs space-y-1">
      <p className="font-medium text-foreground">{label}</p>
      {payload.map((entry: any) => (
        <div key={entry.name} className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-muted-foreground capitalize">{entry.name}</span>
          <span className="font-mono ml-auto">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

export function ComplianceTrend({ enabled }: ComplianceTrendProps) {
  const [days, setDays] = useState(30);
  const { data: trendData = [], isLoading } = useComplianceTrend(enabled ? days : 0);

  if (!enabled) {
    return (
      <Card className="border-border/60 opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-muted-foreground" />
            Compliance Trend
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-10 border border-dashed border-border bg-secondary/20">
            <Lock className="h-8 w-8 text-muted-foreground mb-3" />
            <p className="text-sm font-medium">Pro & Business Feature</p>
            <p className="text-xs text-muted-foreground mt-1">
              Upgrade to see compliance trends over time.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const chartData = trendData.map((d: any) => ({
    ...d,
    date: d.date.slice(5),
  }));

  return (
    <Card className="border-border/60 opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
      <CardHeader className="pb-3 border-b border-border/50">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-primary" />
              Compliance Trend
            </CardTitle>
            <CardDescription className="text-xs mt-1">
              Match volume and compliance over time
            </CardDescription>
          </div>
          <div className="flex border border-border">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => setDays(opt.days)}
                className={`px-2.5 py-1 text-2xs font-mono transition-colors ${
                  days === opt.days
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-4">
        {isLoading ? (
          <div className="h-[220px] bg-secondary/20 animate-pulse" />
        ) : chartData.length === 0 ? (
          <div className="h-[220px] flex items-center justify-center text-sm text-muted-foreground">
            No data yet — run scans to see trends
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="gradCompliant" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradViolations" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="compliant"
                stroke="#22c55e"
                fill="url(#gradCompliant)"
                strokeWidth={2}
              />
              <Area
                type="monotone"
                dataKey="violations"
                stroke="#ef4444"
                fill="url(#gradViolations)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
