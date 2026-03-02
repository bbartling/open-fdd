import { useState, useMemo } from "react";
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
import { useTrendingData } from "@/hooks/use-trending";
import { DateRangeSelect } from "./DateRangeSelect";
import type { DatePreset } from "./DateRangeSelect";
import { PointPicker } from "./PointPicker";
import type { Point, Equipment } from "@/types/api";

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

function presetRange(preset: DatePreset): { start: string; end: string } {
  const end = new Date();
  const start = new Date();
  switch (preset) {
    case "24h":
      start.setHours(start.getHours() - 24);
      break;
    case "7d":
      start.setDate(start.getDate() - 7);
      break;
    case "30d":
      start.setDate(start.getDate() - 30);
      break;
    default:
      start.setDate(start.getDate() - 7);
  }
  return { start: start.toISOString(), end: end.toISOString() };
}

function formatLocalDT(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface TrendingTabProps {
  siteId: string;
  points: Point[];
  equipment: Equipment[];
}

export function TrendingTab({ siteId, points, equipment }: TrendingTabProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [preset, setPreset] = useState<DatePreset>("24h");

  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const [customStart, setCustomStart] = useState(formatLocalDT(weekAgo));
  const [customEnd, setCustomEnd] = useState(formatLocalDT(now));

  const { start, end } = useMemo(() => {
    if (preset === "custom") {
      return {
        start: new Date(customStart).toISOString(),
        end: new Date(customEnd).toISOString(),
      };
    }
    return presetRange(preset);
  }, [preset, customStart, customEnd]);

  const { data, isLoading, error } = useTrendingData(
    siteId,
    selectedIds,
    start,
    end,
  );

  const pointMap = useMemo(
    () => new Map(points.map((p) => [p.id, p])),
    [points],
  );

  const selectedKeys = useMemo(
    () => selectedIds.map((id) => pointMap.get(id)?.external_id ?? id),
    [selectedIds, pointMap],
  );

  const config: ChartConfig = useMemo(() => {
    const c: ChartConfig = {};
    selectedIds.forEach((id, i) => {
      const p = pointMap.get(id);
      const key = p?.external_id ?? id;
      c[key] = {
        label: p?.object_name ?? key,
        color: COLORS[i % COLORS.length],
        unit: p?.unit ?? undefined,
      };
    });
    return c;
  }, [selectedIds, pointMap]);

  const units = useMemo(() => {
    const s = new Set<string>();
    for (const id of selectedIds) {
      const u = pointMap.get(id)?.unit;
      if (u) s.add(u);
    }
    return Array.from(s);
  }, [selectedIds, pointMap]);

  const dualAxis = units.length === 2;

  const timeFormat = useMemo(() => {
    if (preset === "24h") {
      return (ts: number) =>
        new Date(ts).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        });
    }
    return (ts: number) =>
      new Date(ts).toLocaleDateString([], {
        month: "short",
        day: "numeric",
      });
  }, [preset]);

  const tooltipFormat = (ts: number) =>
    new Date(ts).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <div className="mt-4 space-y-5">
      <div className="flex flex-wrap items-center gap-4">
        <PointPicker
          points={points}
          equipment={equipment}
          selectedIds={selectedIds}
          onChange={setSelectedIds}
        />
        <DateRangeSelect
          preset={preset}
          onPresetChange={setPreset}
          customStart={customStart}
          customEnd={customEnd}
          onCustomStartChange={setCustomStart}
          onCustomEndChange={setCustomEnd}
        />
      </div>

      {selectedIds.length === 0 && (
        <div className="flex h-72 items-center justify-center rounded-2xl border border-border/60 bg-card">
          <p className="text-sm text-muted-foreground">
            Select points to view trending data
          </p>
        </div>
      )}

      {selectedIds.length > 0 && isLoading && (
        <Skeleton className="h-72 w-full rounded-2xl" />
      )}

      {selectedIds.length > 0 && error && (
        <div className="flex h-72 items-center justify-center rounded-2xl border border-border/60 bg-card">
          <p className="text-sm text-destructive">
            Failed to load trending data. Please try again.
          </p>
        </div>
      )}

      {selectedIds.length > 0 && !isLoading && !error && data?.length === 0 && (
        <div className="flex h-72 items-center justify-center rounded-2xl border border-border/60 bg-card">
          <p className="text-sm text-muted-foreground">
            No data for the selected points in this date range
          </p>
        </div>
      )}

      {selectedIds.length > 0 && !isLoading && !error && data && data.length > 0 && (
        <ChartContainer
          config={config}
          className="rounded-2xl border border-border/60 bg-card p-5"
        >
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
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
              {dualAxis ? (
                <>
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 12, fill: "hsl(220 8% 46%)" }}
                    tickLine={false}
                    axisLine={false}
                    label={{
                      value: units[0],
                      angle: -90,
                      position: "insideLeft",
                      style: { fontSize: 11, fill: "hsl(220 8% 46%)" },
                    }}
                  />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={{ fontSize: 12, fill: "hsl(220 8% 46%)" }}
                    tickLine={false}
                    axisLine={false}
                    label={{
                      value: units[1],
                      angle: 90,
                      position: "insideRight",
                      style: { fontSize: 11, fill: "hsl(220 8% 46%)" },
                    }}
                  />
                </>
              ) : (
                <YAxis
                  tick={{ fontSize: 12, fill: "hsl(220 8% 46%)" }}
                  tickLine={false}
                  axisLine={false}
                  label={
                    units.length === 1
                      ? {
                          value: units[0],
                          angle: -90,
                          position: "insideLeft",
                          style: { fontSize: 11, fill: "hsl(220 8% 46%)" },
                        }
                      : undefined
                  }
                />
              )}
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    config={config}
                    formatTime={tooltipFormat}
                  />
                }
              />
              <ChartLegend
                content={<ChartLegendContent config={config} />}
              />
              {selectedKeys.map((key, i) => {
                const yAxisId = dualAxis
                  ? pointMap.get(selectedIds[i])?.unit === units[0]
                    ? "left"
                    : "right"
                  : undefined;
                return (
                  <Line
                    key={key}
                    type="monotone"
                    dataKey={key}
                    stroke={config[key]?.color}
                    strokeWidth={1.5}
                    dot={false}
                    connectNulls
                    activeDot={{ r: 3.5, strokeWidth: 0 }}
                    yAxisId={yAxisId}
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </ChartContainer>
      )}
    </div>
  );
}
