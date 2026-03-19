import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useSiteContext } from "@/contexts/site-context";
import { usePoints, useEquipment } from "@/hooks/use-sites";
import { useFaultDefinitions, useFaultTimeseries } from "@/hooks/use-faults";
import { DateRangeSelect } from "@/components/site/DateRangeSelect";
import type { DatePreset } from "@/components/site/DateRangeSelect";
import { PointPicker } from "@/components/site/PointPicker";
import { FaultPicker } from "@/components/site/FaultPicker";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchCsv } from "@/lib/csv";
import {
  inferXColumn,
  inferYColumns,
  joinFaultSignals,
  parseCsvText,
  pickFaultBucket,
  toCsvText,
  type ParsedCsv,
} from "@/lib/plots-csv";
import { Download, Upload, Database, ChartLine, RefreshCw } from "lucide-react";

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
type SourceMode = "openfdd" | "upload";

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 100);
}

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
  const { data: definitions = [] } = useFaultDefinitions();
  const pollingPoints = useMemo(() => points.filter((p) => p.polling), [points]);

  const [sourceMode, setSourceMode] = useState<SourceMode>("openfdd");
  const [plotMode, setPlotMode] = useState<PlotMode>("lines");
  const [showFaultOverlays, setShowFaultOverlays] = useState(true);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [selectedPointIds, setSelectedPointIds] = useState<string[]>([]);
  const [selectedFaultIds, setSelectedFaultIds] = useState<string[]>([]);
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [loadingCsv, setLoadingCsv] = useState(false);
  const [parsedCsv, setParsedCsv] = useState<ParsedCsv | null>(null);
  const [xColumn, setXColumn] = useState<string>("");
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

  const pointIdsForExport =
    selectedPointIds.length > 0 ? selectedPointIds : pollingPoints.map((p) => p.id);
  const faultBucket = pickFaultBucket(start, end);
  const { data: faultData } = useFaultTimeseries(
    selectedSiteId && selectedFaultIds.length > 0 ? selectedSiteId : undefined,
    start,
    end,
    faultBucket,
  );

  const onCsvLoaded = useCallback((text: string) => {
    const parsed = parseCsvText(text);
    setParsedCsv(parsed);
    const x = inferXColumn(parsed.headers) ?? "";
    setXColumn(x);
    setYColumns(inferYColumns(parsed, x));
    setError(null);
  }, []);

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
      setSourceMode("openfdd");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load CSV from Open-FDD.");
    } finally {
      setLoadingCsv(false);
    }
  }, [selectedSiteId, start, end, pointIdsForExport, onCsvLoaded]);

  async function handleJoinFaultCsvExport() {
    if (!parsedCsv || !xColumn) return;
    setDownloadLoading(true);
    try {
      const faults = (faultData?.series ?? []).filter((f) => selectedFaultIds.includes(String(f.metric)));
      const joined = joinFaultSignals(parsedCsv, xColumn, faults, faultBucket);
      downloadText(
        `plot_data_with_faults_${toDateOnly(start)}_${toDateOnly(end)}.csv`,
        toCsvText(joined),
      );
    } finally {
      setDownloadLoading(false);
    }
  }

  function handleRawCsvExport() {
    if (!parsedCsv) return;
    downloadText(`plot_data_${Date.now()}.csv`, toCsvText(parsedCsv));
  }

  function onFileChosen(file: File | null) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onCsvLoaded(String(reader.result ?? ""));
    reader.onerror = () => setError("Failed to read the selected CSV file.");
    reader.readAsText(file);
    setSourceMode("upload");
  }

  const traces = useMemo(() => {
    if (!parsedCsv || !xColumn || yColumns.length === 0) return [];
    const mode = plotMode === "both" ? "lines+markers" : plotMode === "points" ? "markers" : "lines";
    const rows = parsedCsv.rows;
    const out: Record<string, unknown>[] = [];
    yColumns.forEach((col, i) => {
      const x: Array<string | number> = [];
      const y: number[] = [];
      for (const row of rows) {
        const xv = row[xColumn];
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
    if (showFaultOverlays && selectedFaultIds.length > 0 && faultData?.series?.length) {
      selectedFaultIds.forEach((faultId, i) => {
        const series = faultData.series.filter((s) => String(s.metric) === faultId);
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
          name: `fault:${faultId}`,
          line: { shape: "hv", width: 1.5, dash: "dot", color: PLOT_COLORS[(yColumns.length + i) % PLOT_COLORS.length] },
          yaxis: "y2",
        });
      });
    }
    return out;
  }, [parsedCsv, xColumn, yColumns, plotMode, selectedFaultIds, faultData, showFaultOverlays]);

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
            CSV Plotter workbench: load from Open-FDD or drag/drop CSV, then plot instantly with Plotly.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setSourceMode("openfdd")}
            className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${sourceMode === "openfdd" ? "bg-primary text-primary-foreground" : "bg-card"}`}
          >
            <Database className="h-4 w-4" /> Open-FDD source
          </button>
          <button
            type="button"
            onClick={() => setSourceMode("upload")}
            className={`inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${sourceMode === "upload" ? "bg-primary text-primary-foreground" : "bg-card"}`}
          >
            <Upload className="h-4 w-4" /> Upload CSV
          </button>
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

      {sourceMode === "openfdd" && (
        <div className="rounded-lg border border-border/60 bg-card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={loadOpenFddCsv}
              disabled={loadingCsv}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" />
              {loadingCsv ? "Loading CSV..." : "Load CSV from Open-FDD"}
            </button>
            <button
              type="button"
              onClick={handleRawCsvExport}
              disabled={!parsedCsv}
              className="inline-flex items-center gap-2 rounded-lg border border-border/60 px-4 py-2 text-sm disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              Export current CSV
            </button>
            <button
              type="button"
              onClick={handleJoinFaultCsvExport}
              disabled={!parsedCsv || !xColumn || selectedFaultIds.length === 0 || downloadLoading}
              className="inline-flex items-center gap-2 rounded-lg border border-border/60 px-4 py-2 text-sm disabled:opacity-50"
              title="Append fault_<fault_id> 0/1 columns and export"
            >
              <Download className="h-4 w-4" />
              {downloadLoading ? "Preparing..." : "Export CSV + fault signals"}
            </button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Fault join uses /analytics/fault-timeseries ({faultBucket}) and appends `fault_*` columns as 0/1 over the plotted timestamps.
          </p>
        </div>
      )}

      {sourceMode === "upload" && (
        <div
          className={`rounded-lg border-2 border-dashed p-8 text-center ${isDragging ? "border-primary bg-primary/5" : "border-border/60 bg-card"}`}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setIsDragging(false);
            const file = e.dataTransfer.files?.[0] ?? null;
            onFileChosen(file);
          }}
        >
          <Upload className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
          <p className="text-sm font-medium">Drag & drop a CSV file here</p>
          <p className="mt-1 text-xs text-muted-foreground">or click to choose a file</p>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="mt-3 rounded-lg border border-border/60 px-3 py-1.5 text-sm"
          >
            Choose CSV
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => onFileChosen(e.target.files?.[0] ?? null)}
          />
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {parsedCsv && (
        <div className="rounded-lg border border-border/60 bg-card p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">X-axis column</label>
              <select
                value={xColumn}
                onChange={(e) => setXColumn(e.target.value)}
                className="h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm"
              >
                {parsedCsv.headers.map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>
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
                {parsedCsv.headers.filter((h) => h !== xColumn).map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Loaded {parsedCsv.rows.length.toLocaleString()} rows, {parsedCsv.headers.length} columns.
          </p>
        </div>
      )}

      <div className="w-full" data-testid="plots-chart-container">
        {traces.length > 0 ? (
          <PlotlyCanvas
            traces={traces}
            title={`CSV Plotter (${sourceMode === "openfdd" ? "Open-FDD export" : "Uploaded CSV"})`}
          />
        ) : (
          <div className="flex h-[50vh] min-h-[360px] items-center justify-center rounded-lg border border-dashed border-border bg-muted/20 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              <ChartLine className="h-4 w-4" />
              Load a CSV and pick X/Y columns to plot.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
