import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { GridLayout, type Layout, type LayoutItem } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
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
import {
  useFaultTimeseries,
  useFaultDefinitions,
} from "@/hooks/use-faults";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import { PointPicker } from "@/components/site/PointPicker";
import type { Point, Equipment } from "@/types/api";
import { downloadTimeseriesCsv } from "@/lib/csv";
import {
  GripVertical,
  Plus,
  Copy,
  Trash2,
  Download,
  AlertTriangle,
} from "lucide-react";

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

type PanelType = "timeseries" | "faults";

interface DashboardPanel {
  id: string;
  type: PanelType;
  title: string;
  pointIds: string[];
}

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

function pivotFaultSeries(series: { time: string; metric: string; value: number }[]) {
  const byTs = new Map<number, Record<string, number>>();
  for (const r of series) {
    const t = new Date(r.time).getTime();
    if (!byTs.has(t)) byTs.set(t, {});
    byTs.get(t)![r.metric] = r.value;
  }
  return Array.from(byTs.entries())
    .sort(([a], [b]) => a - b)
    .map(([timestamp, rest]) => ({ timestamp, ...rest }));
}

function nextId(panels: DashboardPanel[]): string {
  const nums = panels
    .map((p) => /^panel-(\d+)$/.exec(p.id)?.[1])
    .filter(Boolean)
    .map(Number);
  const max = nums.length ? Math.max(...nums) : 0;
  return `panel-${max + 1}`;
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

// --- Timeseries panel (BACnet + weather points) ---
interface TimeseriesPanelContentProps {
  siteId: string;
  pointIds: string[];
  points: Point[];
  start: string;
  end: string;
  height: number;
}

function TimeseriesPanelContent({
  siteId,
  pointIds,
  points,
  start,
  end,
  height,
}: TimeseriesPanelContentProps) {
  const { data, isLoading, error } = useTrendingData(siteId, pointIds, start, end);
  const pointMap = useMemo(() => new Map(points.map((p) => [p.id, p])), [points]);
  const config: ChartConfig = useMemo(() => {
    const c: ChartConfig = {};
    pointIds.forEach((id, i) => {
      const p = pointMap.get(id);
      const key = p?.external_id ?? id;
      c[key] = {
        label: p?.object_name ?? key,
        color: COLORS[i % COLORS.length],
        unit: p?.unit ?? undefined,
      };
    });
    return c;
  }, [pointIds, pointMap]);

  const keys = pointIds.map((id) => pointMap.get(id)?.external_id ?? id).filter(Boolean);

  if (pointIds.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted-foreground"
        style={{ height: Math.max(120, height - 80) }}
      >
        Add series using the dropdown above.
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="flex items-center justify-center text-sm text-destructive"
        style={{ height: Math.max(120, height - 80) }}
      >
        Failed to load data.
      </div>
    );
  }
  if (isLoading) {
    return <Skeleton className="w-full" style={{ height: Math.max(120, height - 80) }} />;
  }
  if (!data?.length) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted-foreground"
        style={{ height: Math.max(120, height - 80) }}
      >
        No data in this range.
      </div>
    );
  }

  return (
    <ChartContainer config={config} className="h-full w-full">
      <ResponsiveContainer width="100%" height={Math.max(120, height - 80)}>
        <LineChart data={data}>
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
            tick={{ fontSize: 11, fill: "hsl(220 8% 46%)" }}
            tickLine={false}
            axisLine={false}
          />
          <ChartTooltip content={<ChartTooltipContent config={config} formatTime={tooltipFormat} />} />
          <ChartLegend content={<ChartLegendContent config={config} />} />
          {keys.map((key) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={config[key]?.color}
              strokeWidth={1.5}
              dot={false}
              connectNulls
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

// --- Faults panel ---
interface FaultsPanelContentProps {
  siteId: string;
  start: string;
  end: string;
  height: number;
}

function FaultsPanelContent({ siteId, start, end, height }: FaultsPanelContentProps) {
  const bucket =
    start &&
    end &&
    new Date(end).getTime() - new Date(start).getTime() < 2 * 24 * 60 * 60 * 1000
      ? "hour"
      : "day";
  const { data, isLoading, error } = useFaultTimeseries(siteId, start, end, bucket);
  const { data: definitions = [] } = useFaultDefinitions();

  const chartData = useMemo(() => (data?.series ? pivotFaultSeries(data.series) : []), [data]);
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

  if (error) {
    return (
      <div
        className="flex items-center justify-center text-sm text-destructive"
        style={{ height: Math.max(120, height - 80) }}
      >
        Failed to load fault history.
      </div>
    );
  }
  if (isLoading) {
    return <Skeleton className="w-full" style={{ height: Math.max(120, height - 80) }} />;
  }
  if (chartData.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-sm text-muted-foreground"
        style={{ height: Math.max(120, height - 80) }}
      >
        No fault data in this period.
      </div>
    );
  }

  return (
    <ChartContainer config={config} className="h-full w-full">
      <ResponsiveContainer width="100%" height={Math.max(120, height - 80)}>
        <LineChart data={chartData}>
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
            tick={{ fontSize: 11, fill: "hsl(220 8% 46%)" }}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <ChartTooltip content={<ChartTooltipContent config={config} formatTime={tooltipFormat} />} />
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
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartContainer>
  );
}

// --- Single dashboard panel (card with header + body) ---
const ROW_HEIGHT = 80;
const DEFAULT_PANEL_W = 12;
const DEFAULT_PANEL_H = 5;

interface DashboardPanelCardProps {
  panel: DashboardPanel;
  layoutH: number;
  siteId: string;
  points: Point[];
  pollingPoints: Point[];
  equipment: Equipment[];
  start: string;
  end: string;
  onTitleChange: (id: string, title: string) => void;
  onPointIdsChange: (id: string, pointIds: string[]) => void;
  onDuplicate: (id: string) => void;
  onRemove: (id: string) => void;
}

function DashboardPanelCard({
  panel,
  layoutH,
  siteId,
  points,
  pollingPoints,
  equipment,
  start,
  end,
  onTitleChange,
  onPointIdsChange,
  onDuplicate,
  onRemove,
}: DashboardPanelCardProps) {
  const contentHeight = layoutH * ROW_HEIGHT - 52;

  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-card shadow-sm">
      <div className="panel-drag-handle flex flex-shrink-0 items-center gap-2 border-b border-border bg-muted/40 px-3 py-2">
        <GripVertical className="h-4 w-4 shrink-0 cursor-grab text-muted-foreground active:cursor-grabbing" aria-hidden />
        <input
          type="text"
          value={panel.title}
          onChange={(e) => onTitleChange(panel.id, e.target.value)}
          className="min-w-0 flex-1 rounded border-0 bg-transparent px-1 py-0.5 text-sm font-semibold text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="Panel title"
        />
        {panel.type === "timeseries" && (
          <div className="flex-shrink-0">
            <PointPicker
              points={pollingPoints}
              equipment={equipment}
              selectedIds={panel.pointIds}
              onChange={(ids) => onPointIdsChange(panel.id, ids)}
            />
          </div>
        )}
        {panel.type === "faults" && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5" />
            Faults
          </span>
        )}
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            onClick={() => onDuplicate(panel.id)}
            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title="Duplicate panel"
          >
            <Copy className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onRemove(panel.id)}
            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
            title="Remove panel"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {panel.type === "timeseries" && (
          <TimeseriesPanelContent
            siteId={siteId}
            pointIds={panel.pointIds}
            points={points}
            start={start}
            end={end}
            height={contentHeight}
          />
        )}
        {panel.type === "faults" && (
          <FaultsPanelContent siteId={siteId} start={start} end={end} height={contentHeight} />
        )}
      </div>
    </div>
  );
}

export function PlotsPage() {
  const { selectedSiteId } = useSiteContext();
  const { data: points = [], isLoading: ptsLoading } = usePoints(selectedSiteId ?? undefined);
  const { data: equipment = [], isLoading: eqLoading } = useEquipment(selectedSiteId ?? undefined);

  const [panels, setPanels] = useState<DashboardPanel[]>(() => [
    { id: "panel-1", type: "timeseries", title: "Time series", pointIds: [] },
    { id: "panel-2", type: "faults", title: "Faults", pointIds: [] },
  ]);
  const [layout, setLayout] = useState<Layout>(() => [
    { i: "panel-1", x: 0, y: 0, w: DEFAULT_PANEL_W, h: DEFAULT_PANEL_H },
    { i: "panel-2", x: 12, y: 0, w: DEFAULT_PANEL_W, h: DEFAULT_PANEL_H },
  ]);
  const [downloadLoading, setDownloadLoading] = useState(false);
  const gridContainerRef = useRef<HTMLDivElement>(null);
  const [gridWidth, setGridWidth] = useState(1200);

  useEffect(() => {
    const el = gridContainerRef.current;
    if (!el) return;
    const update = () => setGridWidth(el.getBoundingClientRect().width);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const [preset, setPreset] = useState<DatePreset>("7d");
  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const [customStart, setCustomStart] = useState(formatLocalDT(weekAgo));
  const [customEnd, setCustomEnd] = useState(formatLocalDT(now));

  const pollingPoints = useMemo(() => points.filter((p) => p.polling), [points]);

  const { start, end } = useMemo(() => {
    if (preset === "custom") {
      return {
        start: new Date(customStart).toISOString(),
        end: new Date(customEnd).toISOString(),
      };
    }
    return presetRange(preset);
  }, [preset, customStart, customEnd]);

  const layoutMap = useMemo(
    () => new Map<string, LayoutItem>(layout.map((l: LayoutItem) => [l.i, l])),
    [layout],
  );

  const addPanel = useCallback(
    (type: PanelType) => {
      const newId = nextId(panels);
      const maxY = layout.length
        ? Math.max(...layout.map((l: LayoutItem) => l.y + l.h))
        : 0;
      setPanels((prev: DashboardPanel[]) => [
        ...prev,
        {
          id: newId,
          type,
          title: type === "faults" ? "Faults" : "New panel",
          pointIds: [],
        },
      ]);
      setLayout((prev: Layout) => [
        ...prev,
        { i: newId, x: 0, y: maxY, w: DEFAULT_PANEL_W, h: DEFAULT_PANEL_H },
      ]);
    },
    [panels, layout],
  );

  const duplicatePanel = useCallback(
    (id: string) => {
      const panel = panels.find((p) => p.id === id);
      if (!panel) return;
      const newId = nextId(panels);
      const layoutItem = layout.find((l: LayoutItem) => l.i === id);
      const maxY = layout.length ? Math.max(...layout.map((l: LayoutItem) => l.y + l.h)) : 0;
      setPanels((prev: DashboardPanel[]) => [...prev, { ...panel, id: newId, title: `${panel.title} (copy)` }]);
      setLayout((prev: Layout) => [
        ...prev,
        {
          i: newId,
          x: layoutItem?.x ?? 0,
          y: maxY,
          w: layoutItem?.w ?? DEFAULT_PANEL_W,
          h: layoutItem?.h ?? DEFAULT_PANEL_H,
        },
      ]);
    },
    [panels, layout],
  );

  const removePanel = useCallback((id: string) => {
    setPanels((prev: DashboardPanel[]) => prev.filter((p) => p.id !== id));
    setLayout((prev: Layout) => prev.filter((l: LayoutItem) => l.i !== id));
  }, []);

  const onTitleChange = useCallback((id: string, title: string) => {
    setPanels((prev) => prev.map((p) => (p.id === id ? { ...p, title } : p)));
  }, []);

  const onPointIdsChange = useCallback((id: string, pointIds: string[]) => {
    setPanels((prev) => prev.map((p) => (p.id === id ? { ...p, pointIds } : p)));
  }, []);

  const onLayoutChange = useCallback((newLayout: Layout) => {
    setLayout(newLayout);
  }, []);

  async function handleDownloadCsv() {
    if (!selectedSiteId) return;
    setDownloadLoading(true);
    try {
      const startDate = start.slice(0, 10);
      const endDate = end.slice(0, 10);
      const pointIdsFromPanels = panels
        .filter((p) => p.type === "timeseries")
        .flatMap((p) => p.pointIds);
      const pointIds =
        pointIdsFromPanels.length > 0 ? pointIdsFromPanels : pollingPoints.map((p) => p.id);
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
        <Skeleton className="h-72 w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Plots</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Dashboard: add panels, drag to rearrange, resize, and add series from the dropdown.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-muted/30 px-2 py-1">
            <span className="text-xs font-medium text-muted-foreground">Add panel</span>
            <button
              type="button"
              onClick={() => addPanel("timeseries")}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              <Plus className="h-4 w-4" />
              Time series
            </button>
            <button
              type="button"
              onClick={() => addPanel("faults")}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            >
              <Plus className="h-4 w-4" />
              Faults
            </button>
          </div>
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

      <div ref={gridContainerRef} className="min-h-[400px] flex-1 overflow-auto">
        <GridLayout
          className="layout"
          layout={layout}
          onLayoutChange={onLayoutChange}
          cols={24}
          rowHeight={ROW_HEIGHT}
          width={gridWidth}
          draggableHandle=".panel-drag-handle"
          isDraggable
          isResizable
          compactType="vertical"
          preventCollision={false}
        >
          {panels.map((panel) => {
            const item: LayoutItem | undefined = layoutMap.get(panel.id);
            const h = item?.h ?? DEFAULT_PANEL_H;
            return (
              <div key={panel.id}>
                <DashboardPanelCard
                  panel={panel}
                  layoutH={h}
                  siteId={selectedSiteId}
                  points={points}
                  pollingPoints={pollingPoints}
                  equipment={equipment}
                  start={start}
                  end={end}
                  onTitleChange={onTitleChange}
                  onPointIdsChange={onPointIdsChange}
                  onDuplicate={duplicatePanel}
                  onRemove={removePanel}
                />
              </div>
            );
          })}
        </GridLayout>
      </div>
    </div>
  );
}
