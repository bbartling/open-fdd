import { useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
} from "@/components/ui/chart";
import type { ChartConfig } from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { useFaultTimeseries } from "@/hooks/use-faults";
import type { FaultDefinition } from "@/types/api";

const COLORS = [
  "hsl(215, 60%, 42%)",
  "hsl(338, 65%, 48%)",
  "hsl(142, 71%, 35%)",
  "hsl(38, 92%, 50%)",
  "hsl(262, 52%, 50%)",
  "hsl(190, 70%, 40%)",
  "hsl(330, 55%, 45%)",
  "hsl(60, 65%, 38%)",
];

interface FaultOverTimeChartProps {
  siteId: string | undefined;
  definitions: FaultDefinition[];
  preset: "24h" | "7d" | "30d" | "custom";
  start: string;
  end: string;
  bucket: "hour" | "day";
}

/** Pivot API series (time, metric, value) into Recharts rows (timestamp, fault_id: value). */
function pivotFaultSeries(series: { time: string; metric: string; value: number }[]) {
  const byTs = new Map<number, Record<string, number>>();
  for (const r of series) {
    const t = new Date(r.time).getTime();
    if (!Number.isFinite(t)) continue;
    if (!byTs.has(t)) byTs.set(t, {});
    byTs.get(t)![r.metric] = r.value;
  }
  return Array.from(byTs.entries())
    .sort(([a], [b]) => a - b)
    .map(([timestamp, rest]) => ({ timestamp, ...rest }));
}

export function FaultOverTimeChart({ siteId, definitions, preset, start, end, bucket }: FaultOverTimeChartProps) {
  const { data, isLoading, error } = useFaultTimeseries(siteId ?? undefined, start, end, bucket);

  const chartData = useMemo(() => {
    const raw = data?.series ? pivotFaultSeries(data.series) : [];
    return raw.filter((row) => Number.isFinite(row.timestamp));
  }, [data]);
  const metrics = useMemo(() => {
    const set = new Set<string>();
    data?.series?.forEach((r) => set.add(r.metric));
    return Array.from(set);
  }, [data]);

  const defMap = useMemo(() => new Map(definitions.map((d) => [d.fault_id, d])), [definitions]);
  const config: ChartConfig = useMemo(() => {
    const c: ChartConfig = {};
    metrics.forEach((faultId, i) => {
      c[faultId] = {
        label: defMap.get(faultId)?.name ?? faultId,
        color: COLORS[i % COLORS.length],
      };
    });
    return c;
  }, [metrics, defMap]);

  const timeFormat = (ts: number) =>
    new Date(ts).toLocaleDateString([], { month: "short", day: "numeric", hour: preset === "24h" ? "2-digit" : undefined });
  const tooltipFormat = (ts: number) =>
    new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  if (error) {
    return (
      <div className="flex h-72 items-center justify-center rounded-2xl border border-border/60 bg-card">
        <p className="text-sm text-destructive">Failed to load fault history.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {isLoading && <Skeleton className="h-72 w-full rounded-2xl" />}

      {!isLoading && chartData.length === 0 && (
        <div className="flex h-72 items-center justify-center rounded-2xl border border-border/60 bg-card">
          <p className="text-sm text-muted-foreground">
            No fault data in this period. FDD runs periodically; widen the range or run FDD to see results.
          </p>
        </div>
      )}

      {!isLoading && chartData.length > 0 && (
        <ChartContainer
          config={config}
          className="rounded-2xl border border-border/60 bg-card p-5"
        >
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={chartData}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="hsl(220 13% 90% / 0.5)"
                vertical={false}
              />
              <XAxis
                dataKey="timestamp"
                type="number"
                domain={["dataMin", "dataMax"]}
                scale="time"
                tickFormatter={timeFormat}
                tick={{ fontSize: 12, fill: "hsl(220 8% 46%)" }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tick={{ fontSize: 12, fill: "hsl(220 8% 46%)" }}
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    config={config}
                    formatTime={tooltipFormat}
                  />
                }
              />
              <ChartLegend content={<ChartLegendContent config={config} />} />
              {metrics.map((key) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={config[key]?.color}
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
                  activeDot={{ r: 3.5, strokeWidth: 0 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </ChartContainer>
      )}
    </div>
  );
}

