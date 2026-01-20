"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface ChannelData {
  channel: string;
  count: number;
}

interface ChannelChartProps {
  data: ChannelData[];
}

const channelColors: Record<string, string> = {
  google_ads: "#F59E0B",
  facebook: "#3B82F6",
  instagram: "#EC4899",
  youtube: "#EF4444",
  website: "#10B981",
  unknown: "#6B7280",
};

const channelLabels: Record<string, string> = {
  google_ads: "Google Ads",
  facebook: "Facebook",
  instagram: "Instagram",
  youtube: "YouTube",
  website: "Website",
  unknown: "Unknown",
};

export function ChannelChart({ data }: ChannelChartProps) {
  const chartData = data.map((item) => ({
    ...item,
    name: channelLabels[item.channel] || item.channel,
    color: channelColors[item.channel] || channelColors.unknown,
  }));

  return (
    <Card className="opacity-0 animate-fade-up delay-300">
      <CardHeader className="border-b border-border">
        <CardTitle className="accent-line pb-2">Coverage by Channel</CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Asset distribution across platforms
        </p>
      </CardHeader>
      <CardContent className="pt-6">
        {chartData.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-muted-foreground text-sm">
            No data available
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={chartData} layout="vertical" barCategoryGap="20%">
              <XAxis 
                type="number" 
                stroke="hsl(220 10% 50%)" 
                fontSize={11}
                fontFamily="JetBrains Mono"
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                stroke="hsl(220 10% 50%)"
                fontSize={11}
                fontFamily="Sora"
                width={85}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                cursor={{ fill: 'hsl(220 15% 12%)' }}
                contentStyle={{
                  backgroundColor: "hsl(220 18% 7%)",
                  border: "1px solid hsl(220 15% 14%)",
                  borderRadius: "2px",
                  fontFamily: "Sora",
                  fontSize: "12px",
                }}
                labelStyle={{ color: "hsl(45 15% 92%)", fontWeight: 500 }}
                itemStyle={{ color: "hsl(220 10% 50%)" }}
              />
              <Bar dataKey="count" radius={[0, 2, 2, 0]} maxBarSize={24}>
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
