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
import { useSiteContext } from "@/contexts/site-context";
import { usePoints } from "@/hooks/use-sites";
import { useTrendingData } from "@/hooks/use-trending";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import type { Point } from "@/types/api";

const WEATHER_EXTERNAL_IDS = new Set([
  "temp_f",
  "rh_pct",
  "dewpoint_f",
  "wind_mph",
  "gust_mph",
  "wind_dir_deg",
  "shortwave_wm2",
  "direct_wm2",
  "diffuse_wm2",
  "gti_wm2",
  "cloud_pct",
]);

/** Grafana-style panel groups: same units plotted together. */
const WEATHER_GROUPS: { title: string; externalIds: string[]; yAxisLabel?: string }[] = [
  { title: "Weather — Temp / RH / Dewpoint", externalIds: ["temp_f", "dewpoint_f", "rh_pct"], yAxisLabel: "°F / %" },
  { title: "Weather — Wind (Speed / Gust / Direction)", externalIds: ["wind_mph", "gust_mph", "wind_dir_deg"], yAxisLabel: "mph / °" },
  { title: "Weather — Solar / Radiation (W/m²)", externalIds: ["shortwave_wm2", "direct_wm2", "diffuse_wm2", "gti_wm2"], yAxisLabel: "W/m²" },
  { title: "Weather — Cloud Cover (%)", externalIds: ["cloud_pct"], yAxisLabel: "%" },
];

const COLORS = [
  "hsl(215, 60%, 42%)",
  "hsl(338, 65%, 48%)",
  "hsl(142, 71%, 35%)",
  "hsl(38, 92%, 50%)",
  "hsl(262, 52%, 50%)",
  "hsl(190, 70%, 40%)",
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

const CHART_HEIGHT = 280;

interface WeatherChartPanelProps {
  siteId: string;
  pointIds: string[];
  points: Point[];
  start: string;
  end: string;
  title: string;
  yAxisLabel?: string;
}

function WeatherChartPanel({
  siteId,
  pointIds,
  points,
  start,
  end,
  title,
  yAxisLabel,
}: WeatherChartPanelProps) {
  const { data, isLoading, error } = useTrendingData(siteId, pointIds, start, end);
  const pointMap = useMemo(() => new Map(points.map((p) => [p.id, p])), [points]);
  const config: ChartConfig = useMemo(() => {
    const c: ChartConfig = {};
    pointIds.forEach((id, i) => {
      const p = pointMap.get(id);
      c[id] = {
        label: p?.external_id ?? id,
        color: COLORS[i % COLORS.length],
      };
    });
    return c;
  }, [pointIds, pointMap]);
  const keys = pointIds.filter(Boolean);

  if (pointIds.length === 0) return null;

  if (isLoading) {
    return (
      <div className="w-full rounded-lg border border-border/60 bg-card p-4">
        <p className="mb-2 text-sm font-medium text-foreground">{title}</p>
        <Skeleton className="h-[280px] w-full rounded-lg" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="w-full rounded-lg border border-border/60 bg-card p-4">
        <p className="mb-2 text-sm font-medium text-foreground">{title}</p>
        <div className="flex h-[200px] items-center justify-center rounded-lg border border-amber-200 bg-amber-50/80 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
          Could not load data
        </div>
      </div>
    );
  }
  const chartData = data?.length ? data : [];
  if (chartData.length === 0) {
    return (
      <div className="w-full rounded-lg border border-border/60 bg-card p-4">
        <p className="mb-2 text-sm font-medium text-foreground">{title}</p>
        <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 text-sm text-muted-foreground">
          No data in this range
        </div>
      </div>
    );
  }

  return (
    <div className="w-full rounded-lg border border-border/60 bg-card p-4">
      <p className="mb-2 text-sm font-medium text-foreground">{title}</p>
      {yAxisLabel && (
        <p className="mb-1 text-xs text-muted-foreground">{yAxisLabel}</p>
      )}
      <ChartContainer config={config} className="h-full w-full">
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <LineChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
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
    </div>
  );
}

export function WeatherDataPage() {
  const { selectedSiteId } = useSiteContext();
  const { data: points = [], isLoading: pointsLoading } = usePoints(selectedSiteId ?? undefined);

  const weatherPoints = useMemo(
    () => points.filter((p) => p.external_id && WEATHER_EXTERNAL_IDS.has(p.external_id)),
    [points],
  );
  const externalToPoint = useMemo(() => new Map(weatherPoints.map((p) => [p.external_id!, p])), [weatherPoints]);

  const now = new Date();
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const [preset, setPreset] = useState<DatePreset>("7d");
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

  const panels = useMemo(() => {
    return WEATHER_GROUPS.map((group) => {
      const pointIds = group.externalIds
        .map((extId) => externalToPoint.get(extId)?.id)
        .filter(Boolean) as string[];
      const panelPoints = pointIds.map((id) => weatherPoints.find((p) => p.id === id)).filter(Boolean) as Point[];
      return { ...group, pointIds, panelPoints };
    }).filter((p) => p.pointIds.length > 0);
  }, [externalToPoint, weatherPoints]);

  if (!selectedSiteId) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Weather data</h1>
        <div className="flex h-72 flex-col items-center justify-center rounded-2xl border border-border/60 bg-card">
          <p className="text-sm font-medium text-foreground">Select a site to view weather data</p>
          <p className="mt-1 text-sm text-muted-foreground">Use the site selector in the top bar.</p>
        </div>
      </div>
    );
  }

  if (pointsLoading) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Weather data</h1>
        <Skeleton className="h-[400px] w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Weather data</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Open-Meteo weather by unit group — same layout as Grafana weather dashboard. Data with the same units are plotted together.
          </p>
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

      {panels.length === 0 ? (
        <div className="flex h-72 flex-col items-center justify-center rounded-2xl border border-border/60 bg-card">
          <p className="text-sm font-medium text-foreground">No weather points for this site</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Ensure Open-Meteo is enabled and the weather scraper has run (points: temp_f, rh_pct, wind_mph, etc.).
          </p>
        </div>
      ) : (
        <div className="w-full space-y-6">
          {panels.map((panel) => (
            <WeatherChartPanel
              key={panel.title}
              siteId={selectedSiteId}
              pointIds={panel.pointIds}
              points={panel.panelPoints}
              start={start}
              end={end}
              title={panel.title}
              yAxisLabel={panel.yAxisLabel}
            />
          ))}
        </div>
      )}
    </div>
  );
}
