"use client";

import { useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import type { ChartConfig } from "@/components/ui/chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Cloud, Thermometer, Droplets, Wind, Gauge, CloudRain } from "lucide-react";
import { useSiteContext } from "@/contexts/site-context";
import { usePoints, useEquipment, useSites } from "@/hooks/use-sites";
import { useTrendingData } from "@/hooks/use-trending";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import type { PivotRow } from "@/lib/csv";

const WEATHER_EXTERNAL_IDS = [
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
];

const WEATHER_LABELS: Record<string, string> = {
  temp_f: "Temperature (°F)",
  rh_pct: "Relative humidity (%)",
  dewpoint_f: "Dew point (°F)",
  wind_mph: "Wind speed (mph)",
  gust_mph: "Wind gust (mph)",
  wind_dir_deg: "Wind direction (°)",
  shortwave_wm2: "Shortwave radiation (W/m²)",
  direct_wm2: "Direct radiation (W/m²)",
  diffuse_wm2: "Diffuse radiation (W/m²)",
  gti_wm2: "Global tilted irradiance (W/m²)",
  cloud_pct: "Cloud cover (%)",
};

const WEATHER_ICONS: Record<string, typeof Thermometer> = {
  temp_f: Thermometer,
  rh_pct: Droplets,
  dewpoint_f: Droplets,
  wind_mph: Wind,
  gust_mph: Wind,
  wind_dir_deg: Wind,
  shortwave_wm2: Gauge,
  direct_wm2: Gauge,
  diffuse_wm2: Gauge,
  gti_wm2: Gauge,
  cloud_pct: CloudRain,
};

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

function WeatherUnitChart({
  data,
  dataKey,
  label,
  color,
}: {
  data: PivotRow[];
  dataKey: string;
  label: string;
  color: string;
}) {
  const chartConfig: ChartConfig = useMemo(
    () => ({ [dataKey]: { label, color } }),
    [dataKey, label, color],
  );
  const filled = useMemo(
    () => data.map((r) => ({ ...r, [dataKey]: (r[dataKey] as number) ?? 0 })),
    [data, dataKey],
  );
  if (filled.length === 0) return null;
  return (
    <ChartContainer config={chartConfig} className="h-[220px] w-full">
      <LineChart data={filled} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
        <XAxis
          dataKey="timestamp"
          type="number"
          scale="time"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(ts) =>
            new Date(ts).toLocaleDateString([], { month: "short", day: "numeric", hour: "2-digit" })
          }
        />
        <YAxis tickFormatter={(v) => String(v)} />
        <ChartTooltip
          content={
            <ChartTooltipContent
              config={chartConfig}
              formatTime={(ts) => new Date(ts).toLocaleString()}
            />
          }
        />
        <Line
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={2}
          dot={false}
          connectNulls
        />
      </LineChart>
    </ChartContainer>
  );
}

export function WebWeatherPage() {
  const { selectedSiteId } = useSiteContext();
  const { data: sites = [] } = useSites();
  const siteId = selectedSiteId ?? (sites.length > 0 ? sites[0].id : undefined);
  const { data: points = [] } = usePoints(siteId);
  const { data: equipment = [] } = useEquipment(siteId);

  const openMeteoEquip = useMemo(
    () => equipment.find((e) => e.name === "Open-Meteo" || e.equipment_type === "Weather_Service"),
    [equipment],
  );
  const weatherPoints = useMemo(() => {
    const byExt = new Map<string, { id: string; external_id: string }>();
    points.forEach((p) => {
      if (WEATHER_EXTERNAL_IDS.includes(p.external_id)) byExt.set(p.external_id, { id: p.id, external_id: p.external_id });
    });
    if (openMeteoEquip) {
      points
        .filter((p) => p.equipment_id === openMeteoEquip.id)
        .forEach((p) => byExt.set(p.external_id, { id: p.id, external_id: p.external_id }));
    }
    return Array.from(byExt.values());
  }, [points, openMeteoEquip]);

  const [preset, setPreset] = useState<DatePreset>("7d");
  const defaultRange = useMemo(() => presetRange("7d"), []);
  const [customStart, setCustomStart] = useState(defaultRange.start.slice(0, 16));
  const [customEnd, setCustomEnd] = useState(defaultRange.end.slice(0, 16));
  const range = useMemo(() => {
    if (preset === "custom") {
      return { start: new Date(customStart).toISOString(), end: new Date(customEnd).toISOString() };
    }
    return presetRange(preset);
  }, [preset, customStart, customEnd]);
  const pointIds = useMemo(() => weatherPoints.map((p) => p.id), [weatherPoints]);

  const { data: pivotData, isLoading, error } = useTrendingData(
    siteId,
    pointIds,
    range.start,
    range.end,
  );

  const colors = useMemo(
    () =>
      [
        "hsl(215, 60%, 42%)",
        "hsl(190, 70%, 40%)",
        "hsl(142, 71%, 35%)",
        "hsl(38, 92%, 50%)",
        "hsl(262, 52%, 50%)",
        "hsl(338, 65%, 48%)",
        "hsl(60, 65%, 38%)",
        "hsl(330, 55%, 45%)",
        "hsl(0, 70%, 50%)",
        "hsl(180, 60%, 45%)",
        "hsl(280, 50%, 55%)",
      ],
    [],
  );

  if (!siteId) {
    return (
      <div>
        <h1 className="mb-6 flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Cloud className="h-7 w-7" />
          Web weather
        </h1>
        <p className="text-sm text-muted-foreground">Select a site or add a site to view Open-Meteo weather charts.</p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-6 flex items-center gap-2 text-2xl font-semibold tracking-tight">
        <Cloud className="h-7 w-7" />
        Web weather
      </h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Open-Meteo data (temp_f, rh_pct, wind, solar, etc.) from timeseries. One chart per weather variable.
      </p>

      <div className="mb-6 flex flex-wrap items-center gap-4">
        <DateRangeSelect
          preset={preset}
          onPresetChange={setPreset}
          customStart={customStart}
          customEnd={customEnd}
          onCustomStartChange={setCustomStart}
          onCustomEndChange={setCustomEnd}
        />
      </div>

      {isLoading && <Skeleton className="mb-6 h-64 w-full rounded-2xl" />}
      {error && (
        <p className="mb-6 text-sm text-destructive">Failed to load weather data. Ensure Open-Meteo is enabled and data exists for the range.</p>
      )}

      {!isLoading && pivotData && (
        <div className="grid gap-6 sm:grid-cols-1 lg:grid-cols-2">
          {WEATHER_EXTERNAL_IDS.map((key, i) => {
            const hasData = pivotData.some((r) => r[key] != null && Number.isFinite(r[key]));
            if (!hasData) return null;
            const Icon = WEATHER_ICONS[key] ?? Cloud;
            return (
              <Card key={key}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Icon className="h-5 w-5 text-muted-foreground" />
                    {WEATHER_LABELS[key] ?? key}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <WeatherUnitChart
                    data={pivotData}
                    dataKey={key}
                    label={WEATHER_LABELS[key] ?? key}
                    color={colors[i % colors.length]}
                  />
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {!isLoading && !error && pivotData?.length === 0 && weatherPoints.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No Open-Meteo points found for this site. Enable Open-Meteo in Config and run the FDD loop or weather scraper to populate data.
        </p>
      )}
      {!isLoading && !error && pivotData?.length === 0 && weatherPoints.length > 0 && (
        <p className="text-sm text-muted-foreground">No timeseries data for the selected range. Try a different range or run a fetch.</p>
      )}
    </div>
  );
}
