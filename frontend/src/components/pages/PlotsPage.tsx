import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Brush,
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
import { useSiteContext } from "@/contexts/site-context";
import { usePoints, useEquipment } from "@/hooks/use-sites";
import { useTrendingData } from "@/hooks/use-trending";
import { useFaultDefinitions, useFaultTimeseries } from "@/hooks/use-faults";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import { PointPicker } from "@/components/site/PointPicker";
import { FaultPicker } from "@/components/site/FaultPicker";
import type { Point } from "@/types/api";
import { downloadTimeseriesCsv } from "@/lib/csv";
import { Download } from "lucide-react";
import { displayRangeUpdater } from "./plots-display-range";

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

function timeFormat(ts: number) {
  return new Date(ts).toLocaleDateString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
  });
}
function tooltipFormat(ts: number) {
  return new Date(ts).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const CHART_MIN_HEIGHT = 360;
const OVERVIEW_HEIGHT = 56;

/** Bucket width in ms for fault swim lanes (hour or day from API). */
function faultBucketMs(start: string, end: string): number {
  const span = new Date(end).getTime() - new Date(start).getTime();
  return span <= 2 * 24 * 60 * 60 * 1000 ? 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
}

interface TrendChartProps {
  siteId: string;
  pointIds: string[];
  points: Point[];
  start: string;
  end: string;
  selectedFaultIds: string[];
  /** When the user zooms (brush), report the displayed time range for CSV download. */
  onDisplayRangeChange?: (displayStart: string, displayEnd: string) => void;
}

function TrendChart({
  siteId,
  pointIds,
  points,
  start,
  end,
  selectedFaultIds,
  onDisplayRangeChange,
}: TrendChartProps) {
  const [brushRange, setBrushRange] = useState<{ startIndex: number; endIndex: number } | null>(null);

  const { data, isLoading, error } = useTrendingData(siteId, pointIds, start, end);
  const bucket = start && end && new Date(end).getTime() - new Date(start).getTime() < 2 * 24 * 60 * 60 * 1000 ? "hour" : "day";
  const { data: faultData, isLoading: faultLoading } = useFaultTimeseries(
    selectedFaultIds.length > 0 ? siteId : undefined,
    start,
    end,
    bucket,
  );

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setBrushRange(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const pointMap = useMemo(() => new Map(points.map((p) => [p.id, p])), [points]);
  const set = useMemo(
    () => new Set(selectedFaultIds.map((id) => String(id).trim()).filter(Boolean)),
    [selectedFaultIds],
  );
  const faultKeys = useMemo(() => {
    if (!faultData?.series?.length || set.size === 0) return [];
    return faultData.series
      .filter((s) => set.has(String(s.metric).trim()))
      .map((s) => String(s.metric).trim());
  }, [faultData, set]);
  /** Fault active windows [startMs, endMs) per fault_id for swim-lane value 0/1. */
  const faultSegmentsList = useMemo(() => {
    const list: { start: number; end: number; fault_id: string }[] = [];
    if (!faultData?.series?.length || set.size === 0) return list;
    const bucketMs = faultBucketMs(start, end);
    faultData.series
      .filter((s) => s.value > 0 && set.has(String(s.metric).trim()))
      .forEach((s) => {
        const t = new Date(s.time).getTime();
        list.push({ start: t, end: t + bucketMs, fault_id: String(s.metric).trim() });
      });
    return list;
  }, [faultData, set, start, end]);

  const config: ChartConfig = useMemo(() => {
    const c: ChartConfig = {};
    pointIds.forEach((id, i) => {
      const p = pointMap.get(id);
      c[id] = {
        label: p?.object_name ?? p?.external_id ?? id,
        color: COLORS[i % COLORS.length],
        unit: p?.unit ?? undefined,
      };
    });
    faultKeys.forEach((fid, i) => {
      c[fid] = {
        label: fid,
        color: COLORS[(pointIds.length + i) % COLORS.length],
        unit: "0/1",
      };
    });
    return c;
  }, [pointIds, pointMap, faultKeys]);

  const keys = pointIds.filter(Boolean);

  /** Group point IDs by unit (data-model unit); order = first occurrence. Enables one axis per unit. */
  const unitGroups = useMemo((): string[][] => {
    const seen = new Set<string>();
    const order: string[] = [];
    const byUnit = new Map<string, string[]>();
    for (const id of pointIds) {
      if (!id) continue;
      const p = pointMap.get(id);
      const unit = (p?.unit ?? "") || "_";
      if (!byUnit.has(unit)) byUnit.set(unit, []);
      byUnit.get(unit)!.push(id);
      if (!seen.has(unit)) {
        seen.add(unit);
        order.push(unit);
      }
    }
    return order.map((u) => byUnit.get(u) ?? []).filter((g) => g.length > 0);
  }, [pointIds, pointMap]);

  /** Map each point ID to yAxisId: first unit group = left, second+ = right2 (faults stay on right). */
  const pointToYAxisId = useMemo((): Map<string, "left" | "right2"> => {
    const m = new Map<string, "left" | "right2">();
    unitGroups.forEach((group, i) => {
      const axisId = i === 0 ? "left" : "right2";
      group.forEach((id) => m.set(id, axisId));
    });
    return m;
  }, [unitGroups]);

  const hasSecondPointAxis = unitGroups.length >= 2;

  const faultColor = (faultId: string) =>
    COLORS[(pointIds.length + faultKeys.indexOf(faultId)) % COLORS.length];

  const isFaultActiveAt = useCallback(
    (ts: number, faultId: string) =>
      faultSegmentsList.some((s) => s.fault_id === faultId && ts >= s.start && ts < s.end),
    [faultSegmentsList],
  );

  type ChartRow = { timestamp: number; [k: string]: number };
  const fullData = useMemo((): ChartRow[] => {
    if (data?.length) {
      const timeSet = new Set<number>(data.map((d) => d.timestamp));
      faultSegmentsList.forEach((s) => {
        timeSet.add(s.start);
        timeSet.add(s.end - 1);
      });
      const sorted = Array.from(timeSet).sort((a, b) => a - b);
      return sorted.map((timestamp) => {
        const existing = data.find((d) => d.timestamp === timestamp);
        const row: ChartRow = { timestamp };
        if (existing) {
          for (const key of Object.keys(existing)) {
            if (key === "timestamp") continue;
            const v = existing[key];
            if (typeof v === "number" && !Number.isNaN(v)) row[key] = v;
          }
        }
        faultKeys.forEach((fid) => {
          row[fid] = isFaultActiveAt(timestamp, fid) ? 1 : 0;
        });
        return row;
      });
    }
    if (faultData?.series?.length && faultKeys.length > 0) {
      const times = new Set<number>();
      faultSegmentsList.forEach((s) => {
        times.add(s.start);
        times.add(s.end - 1);
      });
      const sorted = Array.from(times).sort((a, b) => a - b);
      return sorted.map((timestamp) => {
        const row: ChartRow = { timestamp };
        faultKeys.forEach((fid) => {
          row[fid] = isFaultActiveAt(timestamp, fid) ? 1 : 0;
        });
        return row;
      });
    }
    return [];
  }, [data, faultData, faultKeys, faultSegmentsList, isFaultActiveAt]);

  const displayedData = useMemo(() => {
    if (!fullData.length) return [];
    if (!brushRange) return fullData;
    const { startIndex, endIndex } = brushRange;
    const lo = Math.max(0, Math.min(startIndex, fullData.length - 1));
    const hi = Math.max(0, Math.min(endIndex, fullData.length - 1));
    return fullData.slice(Math.min(lo, hi), Math.max(lo, hi) + 1);
  }, [fullData, brushRange]);

  // Report effective display range for CSV download (zoomed range when brush active, else full range).
  // Only call when the reported range actually changes to avoid setState loops in parent.
  const lastReportedRange = useRef<{ start: string; end: string } | null>(null);
  useEffect(() => {
    if (!onDisplayRangeChange) return;
    let newStart: string;
    let newEnd: string;
    if (fullData.length === 0) {
      newStart = start;
      newEnd = end;
    } else if (brushRange != null) {
      const lo = Math.max(0, Math.min(brushRange.startIndex, fullData.length - 1));
      const hi = Math.max(0, Math.min(brushRange.endIndex, fullData.length - 1));
      newStart = new Date(fullData[Math.min(lo, hi)].timestamp).toISOString();
      newEnd = new Date(fullData[Math.max(lo, hi)].timestamp).toISOString();
    } else {
      newStart = start;
      newEnd = end;
    }
    const last = lastReportedRange.current;
    if (last && last.start === newStart && last.end === newEnd) return;
    lastReportedRange.current = { start: newStart, end: newEnd };
    onDisplayRangeChange(newStart, newEnd);
  }, [onDisplayRangeChange, fullData, brushRange, start, end]);

  const handleBrushChange = useCallback((range: { startIndex?: number; endIndex?: number } | null) => {
    if (range == null || range.startIndex == null || range.endIndex == null) {
      setBrushRange(null);
      return;
    }
    setBrushRange({ startIndex: range.startIndex, endIndex: range.endIndex });
  }, []);

  const loadingPoints = pointIds.length > 0 && isLoading;
  const loadingFaultsOnly = pointIds.length === 0 && selectedFaultIds.length > 0 && faultLoading;
  const hasAnyData = fullData.length > 0;

  if (pointIds.length === 0 && selectedFaultIds.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 text-sm text-muted-foreground"
        style={{ minHeight: CHART_MIN_HEIGHT }}
      >
        Select points and/or faults from the dropdowns. Drag the brush below to zoom, Escape to reset.
      </div>
    );
  }
  if (pointIds.length > 0 && error) {
    return (
      <div
        className="flex flex-col items-center justify-center gap-2 rounded-lg border border-amber-200 bg-amber-50/80 p-6 dark:border-amber-800 dark:bg-amber-950/30"
        style={{ minHeight: CHART_MIN_HEIGHT }}
      >
        <p className="text-sm font-medium text-amber-800 dark:text-amber-200">Could not load data</p>
        <p className="text-xs text-amber-700 dark:text-amber-300">Check range and selected points, or try again.</p>
      </div>
    );
  }
  if (loadingPoints || loadingFaultsOnly) {
    return <Skeleton className="w-full rounded-lg" style={{ minHeight: CHART_MIN_HEIGHT }} />;
  }
  if (pointIds.length > 0 && !hasAnyData && !selectedFaultIds.length) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 text-sm text-muted-foreground"
        style={{ minHeight: CHART_MIN_HEIGHT }}
      >
        No point data in this range. Select points or widen the date range. Add faults to see when they fire.
      </div>
    );
  }
  if (pointIds.length === 0 && selectedFaultIds.length > 0 && !faultData?.series?.length) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 text-sm text-muted-foreground"
        style={{ minHeight: CHART_MIN_HEIGHT }}
      >
        No fault activity in this range. Widen the date range or run FDD.
      </div>
    );
  }

  const chartData = displayedData.length > 0 ? displayedData : fullData;
  const hasPointLines = pointIds.length > 0 && keys.length > 0;
  const hasFaultLines = faultKeys.length > 0;
  const chartMarginRight = hasSecondPointAxis ? 80 : hasFaultLines ? 52 : 24;

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="w-full" style={{ height: CHART_MIN_HEIGHT }}>
        <ChartContainer config={config} className="h-full w-full">
          <ResponsiveContainer width="100%" height={CHART_MIN_HEIGHT}>
            <LineChart data={chartData} margin={{ top: 8, right: chartMarginRight, left: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 13% 90% / 0.5)" vertical={false} />
              <XAxis
                dataKey="timestamp"
                type="number"
                domain={["dataMin", "dataMax"]}
                scale="time"
                tickFormatter={timeFormat}
                tick={{ fontSize: 11, fill: "hsl(220 8% 46%)" }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 11, fill: "hsl(220 8% 46%)" }}
                tickLine={false}
                axisLine={false}
              />
              {hasSecondPointAxis && (
                <YAxis
                  yAxisId="right2"
                  orientation="right"
                  tick={{ fontSize: 11, fill: "hsl(220 8% 46%)" }}
                  tickLine={false}
                  axisLine={false}
                />
              )}
              {hasFaultLines && (
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  domain={[0, 1.2]}
                  tick={{ fontSize: 10, fill: "hsl(220 8% 46%)" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => (v === 1 ? "1" : v === 0 ? "0" : "")}
                />
              )}
              <ChartTooltip content={<ChartTooltipContent config={config} formatTime={tooltipFormat} />} />
              <ChartLegend content={<ChartLegendContent config={config} />} />
              {hasPointLines && keys.map((key) => (
                <Line
                  key={key}
                  yAxisId={pointToYAxisId.get(key) ?? "left"}
                  type="monotone"
                  dataKey={key}
                  stroke={config[key]?.color}
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
                  activeDot={{ r: 3, strokeWidth: 0 }}
                />
              ))}
              {hasFaultLines && faultKeys.map((fid) => (
                <Line
                  key={fid}
                  yAxisId="right"
                  type="stepAfter"
                  dataKey={fid}
                  stroke={faultColor(fid)}
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
                  activeDot={{ r: 2, strokeWidth: 0 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </ChartContainer>
      </div>

      {hasAnyData && fullData.length > 0 && (
        <div className="shrink-0 rounded border border-border/60 bg-muted/20 p-1.5">
          <p className="mb-1 text-xs text-muted-foreground">Zoom: drag the handles or the shaded area. Press Escape to reset.</p>
          <ResponsiveContainer width="100%" height={OVERVIEW_HEIGHT}>
            <LineChart data={fullData} syncId="plotsZoom" margin={{ top: 0, right: 4, left: 4, bottom: 0 }}>
              <XAxis dataKey="timestamp" type="number" scale="time" hide />
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Brush
                dataKey="timestamp"
                height={OVERVIEW_HEIGHT - 8}
                stroke="hsl(220 13% 46%)"
                fill="hsl(220 13% 96%)"
                startIndex={brushRange?.startIndex ?? 0}
                endIndex={brushRange?.endIndex ?? fullData.length - 1}
                onChange={handleBrushChange}
              />
              {hasPointLines && keys.map((key) => (
                <Line key={key} type="monotone" dataKey={key} stroke={config[key]?.color} strokeWidth={1} dot={false} isAnimationActive={false} />
              ))}
              {hasFaultLines && faultKeys.map((fid) => (
                <Line key={fid} type="stepAfter" dataKey={fid} stroke={config[fid]?.color} strokeWidth={1} dot={false} isAnimationActive={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export function PlotsPage() {
  const { selectedSiteId } = useSiteContext();
  const { data: points = [], isLoading: ptsLoading } = usePoints(selectedSiteId ?? undefined);
  const { data: equipment = [], isLoading: eqLoading } = useEquipment(selectedSiteId ?? undefined);
  const { data: definitions = [] } = useFaultDefinitions();

  const pollingPoints = useMemo(() => points.filter((p) => p.polling), [points]);

  const [selectedPointIds, setSelectedPointIds] = useState<string[]>([]);
  const [selectedFaultIds, setSelectedFaultIds] = useState<string[]>([]);
  const [downloadLoading, setDownloadLoading] = useState(false);
  /** Time range currently shown on the chart (zoomed when brush active). Used for CSV download. */
  const [displayRange, setDisplayRange] = useState<{ start: string; end: string } | null>(null);

  const [preset, setPreset] = useState<DatePreset>("7d");
  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const [customStart, setCustomStart] = useState(formatLocalDT(weekAgo));
  const [customEnd, setCustomEnd] = useState(formatLocalDT(now));

  const onDisplayRangeChange = useCallback((s: string, e: string) => {
    setDisplayRange((prev) => displayRangeUpdater(prev, s, e));
  }, []);

  const { start, end } = useMemo(() => {
    if (preset === "custom") {
      return {
        start: new Date(customStart).toISOString(),
        end: new Date(customEnd).toISOString(),
      };
    }
    return presetRange(preset);
  }, [preset, customStart, customEnd]);

  async function handleDownloadCsv() {
    if (!selectedSiteId) return;
    setDownloadLoading(true);
    try {
      const range = displayRange ?? { start, end };
      const startDate = range.start.slice(0, 10);
      const endDate = range.end.slice(0, 10);
      const pointIds =
        selectedPointIds.length > 0 ? selectedPointIds : pollingPoints.map((p) => p.id);
      await downloadTimeseriesCsv(
        {
          site_id: selectedSiteId,
          start_date: startDate,
          end_date: endDate,
          format: "wide",
          point_ids: pointIds.length > 0 ? pointIds : undefined,
        },
        `timeseries_${startDate}_${endDate}.csv`,
      );
    } catch (err) {
      console.error("Download failed:", err);
      alert(err instanceof Error ? err.message : "Download failed.");
    } finally {
      setDownloadLoading(false);
    }
  }

  if (!selectedSiteId) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Plots</h1>
        <div className="flex h-72 flex-col items-center justify-center rounded-2xl border border-border/60 bg-card">
          <p className="text-sm font-medium text-foreground">Select a site to view plots</p>
          <p className="mt-1 text-sm text-muted-foreground">Use the site selector in the top bar.</p>
        </div>
      </div>
    );
  }

  if (ptsLoading || eqLoading) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Plots</h1>
        <Skeleton className="h-[400px] w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Plots</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            One trend chart. Select points and/or faults; faults show as vertical bands when they fire. Drag the brush to zoom, Escape to reset.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PointPicker
            points={pollingPoints}
            equipment={equipment}
            selectedIds={selectedPointIds}
            onChange={setSelectedPointIds}
            label="Select points"
          />
          <FaultPicker
            definitions={definitions}
            selectedIds={selectedFaultIds}
            onChange={setSelectedFaultIds}
            label="Add faults"
            data-testid="plots-fault-picker"
          />
          <button
            type="button"
            onClick={handleDownloadCsv}
            disabled={downloadLoading}
            className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-border/60 bg-card px-4 py-2.5 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            title="Download timeseries as CSV (wide format)"
          >
            <Download className="h-4 w-4 shrink-0" />
            {downloadLoading ? "Preparing…" : "Download CSV"}
          </button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-4">
        <DateRangeSelect
          preset={preset}
          onPresetChange={setPreset}
          customStart={customStart}
          customEnd={customEnd}
          onCustomStartChange={setCustomStart}
          onCustomEndChange={setCustomEnd}
        />
      </div>

      <div className="h-[55vh] min-h-[360px] w-full max-h-[800px]" data-testid="plots-chart-container">
        <TrendChart
          siteId={selectedSiteId}
          pointIds={selectedPointIds}
          points={points}
          start={start}
          end={end}
          selectedFaultIds={selectedFaultIds}
          onDisplayRangeChange={onDisplayRangeChange}
        />
      </div>
    </div>
  );
}
