import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useSiteContext } from "@/contexts/site-context";
import { usePoints, useEquipment } from "@/hooks/use-sites";
import { useFaultTimeseries, useFaultState } from "@/hooks/use-faults";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchCsv } from "@/lib/csv";
import {
  inferYColumns,
  joinFaultSignals,
  parseCsvText,
  pickFaultBucket,
  type ParsedCsv,
} from "@/lib/plots-csv";
import { ChartLine, RefreshCw } from "lucide-react";

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

const PLOT_COLORS = [
  "#1d4ed8",
  "#be185d",
  "#15803d",
  "#d97706",
  "#7c3aed",
  "#0891b2",
  "#b91c1c",
  "#4d7c0f",
];

type PlotMode = "lines" | "points" | "both";
function toDateOnly(iso: string): string {
  return iso.slice(0, 10);
}

function PlotlyCanvas({
  traces,
  title,
}: {
  traces: Record<string, unknown>[];
  title: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    let mounted = true;
    async function draw() {
      if (!ref.current) return;
      const Plotly = (await import("plotly.js-dist-min")).default as {
        react: (el: HTMLDivElement, data: unknown[], layout: unknown, config: unknown) => void;
      };
      if (!mounted || !ref.current) return;
      Plotly.react(
        ref.current,
        traces,
        {
          title,
          autosize: true,
          margin: { t: 50, r: 24, b: 48, l: 56 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          xaxis: { title: "X", automargin: true },
          yaxis: { title: "Value", automargin: true },
          yaxis2: { title: "Fault 0/1", overlaying: "y", side: "right", range: [0, 1.1] },
          legend: { orientation: "h" },
        },
        {
          responsive: true,
          displaylogo: false,
          modeBarButtonsToRemove: ["lasso2d", "select2d"],
        },
      );
    }
    void draw();
    return () => {
      mounted = false;
    };
  }, [traces, title]);
  return <div ref={ref} className="h-[62vh] min-h-[420px] w-full rounded-lg border border-border/60 bg-card" />;
}

export function PlotsPage() {
  const { selectedSiteId } = useSiteContext();
  const { data: points = [], isLoading: ptsLoading } = usePoints(selectedSiteId ?? undefined);
  const { data: equipment = [], isLoading: eqLoading } = useEquipment(selectedSiteId ?? undefined);
  const { data: faultState = [] } = useFaultState(selectedSiteId ?? undefined);
  const pollingPoints = useMemo(() => points.filter((p) => p.polling), [points]);

  const [plotMode, setPlotMode] = useState<PlotMode>("lines");
  const [showFaultOverlays, setShowFaultOverlays] = useState(true);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [selectedPointIds, setSelectedPointIds] = useState<string[]>([]);
  const [selectedFaultId, setSelectedFaultId] = useState<string>("");
  const [loadingCsv, setLoadingCsv] = useState(false);
  const [parsedCsv, setParsedCsv] = useState<ParsedCsv | null>(null);
  const [yColumns, setYColumns] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [preset, setPreset] = useState<DatePreset>("7d");
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

  const deviceOptions = useMemo(() => {
    const map = new Map<string, { label: string }>();
    for (const p of pollingPoints) {
      if (!p.bacnet_device_id) continue;
      const eq = equipment.find((e) => e.id === p.equipment_id);
      const label = eq ? `${p.bacnet_device_id} - ${eq.name}` : p.bacnet_device_id;
      map.set(p.bacnet_device_id, { label });
    }
    return Array.from(map.entries())
      .map(([id, v]) => ({ id, label: v.label }))
      .sort((a, b) => a.id.localeCompare(b.id));
  }, [pollingPoints, equipment]);

  const pointsForDevice = useMemo(
    () => pollingPoints.filter((p) => p.bacnet_device_id === selectedDeviceId),
    [pollingPoints, selectedDeviceId],
  );

  /** All equipment IDs tied to the selected BACnet device (one device can span multiple equipment records). */
  const selectedDeviceEquipmentIds = useMemo(() => {
    if (!selectedDeviceId) return new Set<string>();
    const ids = new Set<string>();
    for (const p of pollingPoints) {
      if (p.bacnet_device_id !== selectedDeviceId) continue;
      if (p.equipment_id) ids.add(p.equipment_id);
    }
    return ids;
  }, [pollingPoints, selectedDeviceId]);

  const faultIdsForDevice = useMemo(() => {
    if (selectedDeviceEquipmentIds.size === 0) return [];
    const set = new Set(
      faultState
        .filter((f) => f.equipment_id && selectedDeviceEquipmentIds.has(f.equipment_id))
        .map((f) => String(f.fault_id))
        .filter(Boolean),
    );
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [faultState, selectedDeviceEquipmentIds]);

  const pointIdsForExport = selectedPointIds.length > 0 ? selectedPointIds : pointsForDevice.map((p) => p.id);
  const pointSelectionKey = useMemo(() => {
    const ids = selectedPointIds.length > 0 ? selectedPointIds : pointsForDevice.map((p) => p.id);
    return [...ids].sort().join("\0");
  }, [selectedPointIds, pointsForDevice]);
  const faultBucket = pickFaultBucket(start, end);
  /** Equipment rows tied to the selected BACnet device — backend must filter fault_results, not only site + fault_id. */
  const equipmentIdsForFaultOverlay = useMemo(
    () => Array.from(selectedDeviceEquipmentIds).sort(),
    [selectedDeviceEquipmentIds],
  );
  const { data: faultData } = useFaultTimeseries(selectedSiteId ?? undefined, start, end, faultBucket, {
    enabled: !!(
      selectedSiteId &&
      selectedFaultId &&
      start &&
      end &&
      equipmentIdsForFaultOverlay.length > 0
    ),
    equipmentIds: equipmentIdsForFaultOverlay,
  });

  const onCsvLoaded = useCallback((text: string) => {
    const parsed = parseCsvText(text);
    setParsedCsv(parsed);
    const x = "timestamp";
    setYColumns(inferYColumns(parsed, x));
    setError(null);
  }, []);

  /** Drop loaded CSV when load inputs change so we never join fault data onto a stale export. */
  useEffect(() => {
    setParsedCsv(null);
    setYColumns([]);
  }, [selectedSiteId, selectedDeviceId, start, end, pointSelectionKey]);

  const loadOpenFddCsv = useCallback(async () => {
    if (!selectedSiteId) return;
    setLoadingCsv(true);
    try {
      const csv = await fetchCsv({
        site_id: selectedSiteId,
        start_date: toDateOnly(start),
        end_date: toDateOnly(end),
        format: "wide",
        point_ids: pointIdsForExport.length > 0 ? pointIdsForExport : undefined,
      });
      onCsvLoaded(csv);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load CSV from Open-FDD.");
    } finally {
      setLoadingCsv(false);
    }
  }, [selectedSiteId, start, end, pointIdsForExport, onCsvLoaded]);
  const effectiveCsv = useMemo(() => {
    if (!parsedCsv || !selectedFaultId) return parsedCsv;
    const faults = (faultData?.series ?? []).filter((f) => String(f.metric) === selectedFaultId);
    return joinFaultSignals(parsedCsv, "timestamp", faults, faultBucket);
  }, [parsedCsv, selectedFaultId, faultData, faultBucket]);

  const traces = useMemo(() => {
    if (!effectiveCsv || yColumns.length === 0) return [];
    const mode = plotMode === "both" ? "lines+markers" : plotMode === "points" ? "markers" : "lines";
    const rows = effectiveCsv.rows;
    const out: Record<string, unknown>[] = [];
    yColumns.forEach((col, i) => {
      const x: Array<string | number> = [];
      const y: number[] = [];
      for (const row of rows) {
        const xv = row.timestamp;
        const yv = row[col];
        const yNum = typeof yv === "number" ? yv : Number(yv);
        if (xv == null || xv === "" || !Number.isFinite(yNum)) continue;
        x.push(xv as string | number);
        y.push(yNum);
      }
      out.push({
        x,
        y,
        type: "scatter",
        mode,
        name: col,
        line: { width: 2, color: PLOT_COLORS[i % PLOT_COLORS.length] },
        marker: { size: 5, color: PLOT_COLORS[i % PLOT_COLORS.length] },
      });
    });
    if (showFaultOverlays && selectedFaultId && faultData?.series?.length) {
      const series = faultData.series.filter((s) => String(s.metric) === selectedFaultId);
      const x: string[] = [];
      const y: number[] = [];
      for (const s of series) {
        x.push(s.time);
        y.push(s.value > 0 ? 1 : 0);
      }
      out.push({
        x,
        y,
        type: "scatter",
        mode: "lines",
        name: `fault:${selectedFaultId}`,
        line: { shape: "hv", width: 1.5, dash: "dot", color: PLOT_COLORS[yColumns.length % PLOT_COLORS.length] },
        yaxis: "y2",
      });
    }
    return out;
  }, [effectiveCsv, yColumns, plotMode, selectedFaultId, faultData, showFaultOverlays]);

  useEffect(() => {
    if (deviceOptions.length === 0) {
      if (selectedDeviceId) setSelectedDeviceId("");
      return;
    }
    const stillValid = deviceOptions.some((o) => o.id === selectedDeviceId);
    if (!stillValid || !selectedDeviceId) {
      setSelectedDeviceId(deviceOptions[0].id);
    }
  }, [selectedDeviceId, deviceOptions]);

  const pollingPointsRef = useRef(pollingPoints);
  pollingPointsRef.current = pollingPoints;

  useEffect(() => {
    if (!selectedDeviceId) return;
    const forDevice = pollingPointsRef.current.filter(
      (p) => p.bacnet_device_id === selectedDeviceId,
    );
    setSelectedPointIds(forDevice.slice(0, 4).map((p) => p.id));
  }, [selectedDeviceId]);

  useEffect(() => {
    if (faultIdsForDevice.length === 0) {
      setSelectedFaultId("");
      return;
    }
    if (!faultIdsForDevice.includes(selectedFaultId)) {
      setSelectedFaultId(faultIdsForDevice[0]);
    }
  }, [faultIdsForDevice, selectedFaultId]);

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
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Plots</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Plot BACnet device trends with fault overlays.
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
        <label className="text-sm">Mode:</label>
        <select
          value={plotMode}
          onChange={(e) => setPlotMode(e.target.value as PlotMode)}
          className="h-9 rounded-lg border border-border/60 bg-background px-3 text-sm"
        >
          <option value="lines">Lines</option>
          <option value="points">Points</option>
          <option value="both">Both</option>
        </select>
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showFaultOverlays}
            onChange={(e) => setShowFaultOverlays(e.target.checked)}
          />
          Show fault overlays
        </label>
      </div>

      <div className="rounded-lg border border-border/60 bg-card p-4">
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">BACnet device instance ID</label>
            <select
              value={selectedDeviceId}
              onChange={(e) => setSelectedDeviceId(e.target.value)}
              className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm"
            >
              {deviceOptions.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Points (for selected device)</label>
            <select
              multiple
              value={selectedPointIds}
              onChange={(e) => setSelectedPointIds(Array.from(e.target.selectedOptions).map((o) => o.value))}
              className="h-28 w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm"
            >
              {pointsForDevice.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.object_name ?? p.external_id}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Faults (for selected device)</label>
            <select
              value={selectedFaultId}
              onChange={(e) => setSelectedFaultId(e.target.value)}
              className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm"
              disabled={faultIdsForDevice.length === 0}
            >
              {faultIdsForDevice.length === 0 ? (
                <option value="">None available</option>
              ) : (
                faultIdsForDevice.map((faultId) => (
                  <option key={faultId} value={faultId}>
                    {faultId}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={loadOpenFddCsv}
            disabled={loadingCsv || !selectedDeviceId || pointIdsForExport.length === 0}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            <RefreshCw className="h-4 w-4" />
            {loadingCsv ? "Loading..." : "Load Data from Database"}
          </button>
          <span className="text-xs text-muted-foreground">Timestamp is fixed to `timestamp`; fault data is joined automatically when available.</span>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {effectiveCsv && (
        <div className="rounded-lg border border-border/60 bg-card p-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Y columns (multi-select)</label>
            <select
              multiple
              value={yColumns}
              onChange={(e) => {
                const vals = Array.from(e.target.selectedOptions).map((o) => o.value);
                setYColumns(vals);
              }}
              className="h-28 w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm"
            >
              {effectiveCsv.headers.filter((h) => h !== "timestamp").map((h) => (
                <option key={h} value={h}>{h}</option>
              ))}
            </select>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Loaded {effectiveCsv.rows.length.toLocaleString()} rows, {effectiveCsv.headers.length} columns.
          </p>
        </div>
      )}

      <div className="w-full" data-testid="plots-chart-container">
        {traces.length > 0 ? (
          <PlotlyCanvas
            traces={traces}
            title="Open-FDD Trends"
          />
        ) : (
          <div className="flex h-[50vh] min-h-[360px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              <ChartLine className="h-4 w-4" />
              Select a BACnet device, choose points, then load data to plot.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
