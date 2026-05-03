import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";
import { PointsTreePanel } from "../components/site/PointsTreePanel";
import { useRulesList } from "../hooks/use-rules";
import { parsePlotsSearch } from "../lib/plots-url";

type PlotReadiness = {
  ok: boolean;
  summary: string;
  recommend_clean_metrics: boolean;
  row_count?: number;
  metric_columns_not_plot_ready?: number;
  columns?: Array<{
    name: string;
    role?: string;
    plot_line_ready: boolean;
    quality?: string;
    recommend_clean_metrics?: boolean;
    hint?: string;
  }>;
};

type PlotFrameResponse = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  sources?: string[];
  fault_totals?: Record<string, number>;
  readiness?: PlotReadiness;
};

type PlotShareRecord = {
  site_id?: string;
  rules_path?: string;
  sources?: string[];
  limit?: number;
  join_how?: string;
  start_ts?: string | null;
  end_ts?: string | null;
  rule_files?: string[] | null;
  skip_missing_columns?: boolean;
  chunk_rows?: number;
};

type ModelExportResponse = {
  equipment: Array<{ id?: string; site_id?: string; name?: string; equipment_type?: string | null }>;
  points: Array<{
    id?: string;
    site_id?: string;
    equipment_id?: string | null;
    external_id?: string;
    brick_type?: string | null;
    metadata?: Record<string, unknown> | null;
  }>;
};

type PlotMode = "lines" | "points" | "both";
type BoundsResponse = { start: string | null; end: string | null };

type CleanMetricsPayload = {
  ok?: boolean;
  committed?: boolean;
  error?: string;
  message?: string;
  applied_columns?: string[];
  storage_path?: string;
  row_count?: number;
};

const COLORS = ["#1d4ed8", "#be185d", "#15803d", "#d97706", "#7c3aed", "#0891b2"];

function isFaultColumn(name: string) {
  const n = name.toLowerCase();
  return n.endsWith("_flag") || n.endsWith("_fault");
}

function coerceFaultY(yv: unknown): number | null {
  if (yv === true || yv === "true" || yv === 1 || yv === "1") return 1;
  if (yv === false || yv === "false" || yv === 0 || yv === "0") return 0;
  if (yv === "" || yv === null || yv === undefined) return null;
  const n = typeof yv === "number" ? yv : Number(yv);
  if (!Number.isFinite(n)) return null;
  return n > 0 ? 1 : 0;
}

function resolveColumnsFromExternalIds(columns: string[], externalIds: string[], currentSource: string): string[] {
  const set = new Set<string>();
  const baseName = (col: string) => {
    const idx = col.lastIndexOf("_");
    return idx > 0 ? col.slice(0, idx) : col;
  };
  for (const ext of externalIds) {
    if (currentSource === "all") {
      for (const col of columns) {
        if (col === ext || baseName(col) === ext) {
          set.add(col);
        }
      }
    } else if (columns.includes(ext)) {
      set.add(ext);
    }
  }
  return Array.from(set);
}

function PlotlyCanvas({
  traces,
  title,
  secondaryAxis,
}: {
  traces: Record<string, unknown>[];
  title: string;
  secondaryAxis: boolean;
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
          margin: { t: 50, r: secondaryAxis ? 72 : 24, b: 48, l: 56 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          xaxis: { title: "Timestamp", automargin: true },
          yaxis: {
            title: secondaryAxis ? "Sensors" : "Value",
            automargin: true,
          },
          ...(secondaryAxis
            ? {
                yaxis2: {
                  title: "Faults (0/1)",
                  overlaying: "y",
                  side: "right",
                  range: [-0.08, 1.08],
                  tickmode: "array",
                  tickvals: [0, 1],
                  ticktext: ["false", "true"],
                  automargin: true,
                },
              }
            : {}),
          legend: { orientation: "h" },
        },
        { responsive: true, displaylogo: false },
      );
    }
    void draw();
    return () => {
      mounted = false;
    };
  }, [traces, title, secondaryAxis]);
  return <div ref={ref} style={{ height: "62vh", minHeight: 420, border: "1px solid var(--border)", borderRadius: 10 }} />;
}

function initialPlotsFromLocation(): ReturnType<typeof parsePlotsSearch> {
  if (typeof window === "undefined") return {};
  return parsePlotsSearch(window.location.search);
}

function shareIdFromLocation(): string {
  if (typeof window === "undefined") return "";
  return (new URLSearchParams(window.location.search).get("share") || "").trim();
}

export function PlotsPage() {
  const siteContext = useSite();
  const shareFromUrl = useMemo(() => shareIdFromLocation(), []);
  const initialPlots = useMemo(() => initialPlotsFromLocation(), []);
  const [siteId, setSiteId] = useState(
    () => initialPlots.siteId || siteContext.selectedSiteId || "",
  );
  const [plotMode, setPlotMode] = useState<PlotMode>("lines");
  const [frame, setFrame] = useState<PlotFrameResponse | null>(null);
  const [status, setStatus] = useState(
    "Pick a site, choose sensors in the tree, configure source/rules below, then Run FDD & refresh chart.",
  );
  const [modelPoints, setModelPoints] = useState<ModelExportResponse["points"]>([]);
  const [modelEquipment, setModelEquipment] = useState<ModelExportResponse["equipment"]>([]);
  const [selectedExternalIds, setSelectedExternalIds] = useState<string[]>([]);
  const [runSource, setRunSource] = useState(() => initialPlots.runSource || "csv");
  const [joinHow, setJoinHow] = useState<"inner" | "left" | "outer" | "right">(
    () => initialPlots.joinHow || "outer",
  );
  const [startTs, setStartTs] = useState("");
  const [endTs, setEndTs] = useState("");
  const [boundsStatus, setBoundsStatus] = useState("");
  const [runOutput, setRunOutput] = useState(
    "After a successful run, fault totals and column names appear here. For reopenable handoffs, use the bridge POST /plots/share (same JSON as POST /plots/fdd-frame).",
  );
  const [selectedRuleFiles, setSelectedRuleFiles] = useState<string[]>([]);
  const [skipMissingRules, setSkipMissingRules] = useState(() => initialPlots.skipMissingRules !== false);
  const { data: rulesData, isLoading: rulesLoading, error: rulesListError, refresh: refreshRulesList } = useRulesList();
  const [cleanBusy, setCleanBusy] = useState(false);
  const [cleanMsg, setCleanMsg] = useState<string | null>(null);

  const effectiveSiteId = useMemo(() => (siteId || siteContext.selectedSiteId || "").trim(), [siteId, siteContext.selectedSiteId]);

  const toggleRuleFileForBackfill = useCallback((name: string) => {
    setSelectedRuleFiles((prev) => (prev.includes(name) ? prev.filter((f) => f !== name) : [...prev, name]));
  }, []);
  const urlAutoFddPending = useRef(Boolean(initialPlots.autoFddOverlay) && !shareFromUrl);
  const shareHydrated = useRef(false);

  const plotColumns = useMemo(() => {
    if (!frame?.columns?.length) return [];
    const overlay = runSource === "all" ? "all" : runSource;
    const fromTree = resolveColumnsFromExternalIds(frame.columns, selectedExternalIds, overlay);
    const faultCols = frame.columns.filter((c) => isFaultColumn(c));
    const metrics = fromTree.filter((c) => !isFaultColumn(c));
    if (metrics.length === 0) {
      const fallback = frame.columns.filter((c) => c !== "timestamp" && !isFaultColumn(c));
      return [...fallback.slice(0, 8), ...faultCols];
    }
    return [...metrics, ...faultCols];
  }, [frame, selectedExternalIds, runSource]);

  useEffect(() => {
    if (!siteId && siteContext.selectedSiteId) {
      setSiteId(siteContext.selectedSiteId);
    }
  }, [siteId, siteContext.selectedSiteId]);

  useEffect(() => {
    void (async () => {
      try {
        const model = await desktopFetch<ModelExportResponse>("/model/export");
        setModelPoints(model.points || []);
        setModelEquipment(model.equipment || []);
      } catch {
        // non-fatal for plots UX
      }
    })();
  }, []);

  useEffect(() => {
    async function loadBounds() {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) return;
      try {
        if (runSource === "all") {
          setBoundsStatus("Joined source mode uses combined window; bounds auto-population is source-specific.");
          setStartTs("");
          setEndTs("");
          return;
        }
        const bounds = await desktopFetch<BoundsResponse>("/timeseries/bounds", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ site_id: effectiveSiteId, source: runSource }),
        });
        const start = String(bounds.start || "");
        const end = String(bounds.end || "");
        setStartTs(start);
        setEndTs(end);
        setBoundsStatus(start && end ? "Auto-populated from loaded dataset bounds." : "No bounds found yet.");
      } catch (e) {
        setBoundsStatus(e instanceof Error ? e.message : String(e));
      }
    }
    void loadBounds();
  }, [siteId, siteContext.selectedSiteId, runSource]);

  useEffect(() => {
    const files = rulesData?.files ?? [];
    setSelectedRuleFiles((prev) => prev.filter((f) => files.includes(f)));
  }, [rulesData?.files]);

  const loadAndPlotNoFdd = useCallback(async () => {
    try {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) {
        setStatus("Set or select a site first.");
        return;
      }
      let url: string;
      if (runSource === "all") {
        const p = new URLSearchParams({
          site_id: effectiveSiteId,
          sources: "csv,weather,onboard,bacnet",
          limit: "5000",
          join_how: joinHow,
          include_readiness: "true",
        });
        if (startTs.trim()) p.set("start_ts", startTs.trim());
        if (endTs.trim()) p.set("end_ts", endTs.trim());
        url = `/plots/site-frame?${p.toString()}`;
      } else {
        const p = new URLSearchParams({
          site_id: effectiveSiteId,
          source: runSource,
          limit: "5000",
          include_readiness: "true",
        });
        url = `/plots/frame?${p.toString()}`;
      }
      const out = await desktopFetch<PlotFrameResponse>(url);
      setFrame(out);
      const r = out.readiness;
      if (r) {
        const extra = r.recommend_clean_metrics
          ? " Run POST /timeseries/clean-metrics (preview then commit) so Plotly and FDD see plain floats."
          : "";
        setStatus(`${r.summary} Rows: ${out.rows.length}. readiness.ok=${String(r.ok)}.${extra}`);
      } else {
        setStatus(`Loaded ${out.rows.length} rows (no readiness in response — update bridge).`);
      }
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }, [siteId, siteContext.selectedSiteId, runSource, joinHow, startTs, endTs]);

  const runCleanMetricsForPlots = useCallback(
    async (commit: boolean) => {
      if (!effectiveSiteId) {
        setCleanMsg("Select a site first.");
        return;
      }
      if (runSource === "all") {
        setCleanMsg("Choose a single source (e.g. CSV) — cleaning updates one Feather store per driver.");
        return;
      }
      if (commit) {
        const ok = window.confirm(
          "Save cleaned numeric columns to Feather for this site and source? Replaces stored files for that driver.",
        );
        if (!ok) return;
      }
      setCleanBusy(true);
      setCleanMsg(null);
      try {
        const out = await desktopFetch<CleanMetricsPayload>("/timeseries/clean-metrics", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            site_id: effectiveSiteId,
            source: runSource,
            commit,
            preview_limit: 12,
          }),
        });
        if (out.ok === false || out.error) {
          setCleanMsg(`${out.error ?? "error"}: ${out.message ?? JSON.stringify(out)}`);
          return;
        }
        const cols = (out.applied_columns ?? []).length ? out.applied_columns!.join(", ") : "(none)";
        const path = out.storage_path ? `\n${out.storage_path}` : "";
        setCleanMsg(
          `${commit ? "Saved." : "Preview OK — no Feather write yet."} Columns: ${cols}. Rows: ${out.row_count ?? "—"}${path}`,
        );
        if (commit) {
          await loadAndPlotNoFdd();
        }
      } catch (e) {
        setCleanMsg(e instanceof Error ? e.message : String(e));
      } finally {
        setCleanBusy(false);
      }
    },
    [effectiveSiteId, runSource, loadAndPlotNoFdd],
  );

  const refreshFddChart = useCallback(async (): Promise<PlotFrameResponse | null> => {
    try {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) {
        setStatus("Set or select a site first.");
        return null;
      }
      const rulesPath = rulesData?.rules_dir || "";
      if (!rulesPath) {
        setStatus("Rules directory is not ready yet (FDD Rule Setup).");
        return null;
      }
      const sources = runSource === "all" ? ["csv", "weather", "onboard", "bacnet"] : [runSource];
      const out = await desktopFetch<PlotFrameResponse>("/plots/fdd-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          rules_path: rulesPath,
          sources,
          limit: 5000,
          join_how: runSource === "all" ? joinHow : "outer",
          start_ts: startTs || null,
          end_ts: endTs || null,
          rule_files: selectedRuleFiles.length > 0 ? selectedRuleFiles : null,
          skip_missing_columns: skipMissingRules,
        }),
      });
      setFrame(out);
      const overlaySource = runSource === "all" ? "all" : runSource;
      const ft =
        out.fault_totals && Object.keys(out.fault_totals).length > 0
          ? ` Fault totals: ${JSON.stringify(out.fault_totals)}`
          : "";
      setStatus(
        `Loaded ${out.rows.length} rows with FDD (${overlaySource}).${ft} Chart uses the points tree (and all fault columns).`,
      );
      return out;
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, [
    siteId,
    siteContext.selectedSiteId,
    runSource,
    joinHow,
    rulesData?.rules_dir,
    selectedRuleFiles,
    skipMissingRules,
    startTs,
    endTs,
  ]);

  useEffect(() => {
    if (!shareFromUrl || shareHydrated.current) return;
    shareHydrated.current = true;
    let cancelled = false;
    void (async () => {
      try {
        const rec = await desktopFetch<PlotShareRecord>(`/plots/share/${encodeURIComponent(shareFromUrl)}`);
        if (cancelled) return;
        const sid = String(rec.site_id || "").trim();
        const rulesPath = String(rec.rules_path || "").trim();
        if (!sid || !rulesPath) {
          setStatus("Saved plot share is missing site_id or rules_path.");
          return;
        }
        const srcs = Array.isArray(rec.sources) && rec.sources.length > 0 ? rec.sources.map(String) : ["csv"];
        setSiteId(sid);
        setRunSource(srcs.length > 1 ? "all" : srcs[0]);
        const jh = String(rec.join_how || "outer").toLowerCase();
        const joinResolved = (["inner", "left", "outer", "right"].includes(jh) ? jh : "outer") as
          "inner" | "left" | "outer" | "right";
        setJoinHow(joinResolved);
        setSkipMissingRules(rec.skip_missing_columns !== false);
        setStartTs(rec.start_ts ? String(rec.start_ts) : "");
        setEndTs(rec.end_ts ? String(rec.end_ts) : "");
        const rf = Array.isArray(rec.rule_files) ? rec.rule_files.filter(Boolean).map(String) : [];
        setSelectedRuleFiles(rf);
        const out = await desktopFetch<PlotFrameResponse>("/plots/fdd-frame", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            site_id: sid,
            rules_path: rulesPath,
            sources: srcs,
            limit: Math.min(Math.max(Number(rec.limit) || 5000, 1), 20_000),
            join_how: joinResolved,
            start_ts: rec.start_ts ?? null,
            end_ts: rec.end_ts ?? null,
            rule_files: rf.length > 0 ? rf : null,
            skip_missing_columns: rec.skip_missing_columns !== false,
            chunk_rows: Number(rec.chunk_rows || 0),
          }),
        });
        if (cancelled) return;
        setFrame(out);
        const overlaySource = srcs.length > 1 ? "all" : srcs[0];
        const ft =
          out.fault_totals && Object.keys(out.fault_totals).length > 0
            ? ` Fault totals: ${JSON.stringify(out.fault_totals)}`
            : "";
        setStatus(`Restored share ${shareFromUrl}: ${out.rows.length} rows with FDD (${overlaySource}).${ft}`);
        if (typeof window !== "undefined") {
          const u = new URL(window.location.href);
          u.searchParams.delete("share");
          const s = u.searchParams.toString();
          window.history.replaceState({}, "", `${u.pathname}${s ? `?${s}` : ""}`);
        }
      } catch (e) {
        if (!cancelled) {
          setStatus(e instanceof Error ? e.message : String(e));
          shareHydrated.current = false;
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [shareFromUrl]);

  useEffect(() => {
    if (!urlAutoFddPending.current) return;
    if (rulesLoading || !rulesData?.rules_dir) return;
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus(
        "This URL requests an FDD chart (?fdd=1) but no site was selected. Add ?site_id=<uuid> or pick a site, then use Run FDD & refresh chart below.",
      );
      urlAutoFddPending.current = false;
      return;
    }
    urlAutoFddPending.current = false;
    void (async () => {
      const out = await refreshFddChart();
      if (out && typeof window !== "undefined") {
        const u = new URL(window.location.href);
        if (u.searchParams.get("fdd") === "1" || u.searchParams.get("overlay") === "1") {
          u.searchParams.delete("fdd");
          u.searchParams.delete("overlay");
          const s = u.searchParams.toString();
          window.history.replaceState({}, "", `${u.pathname}${s ? `?${s}` : ""}`);
        }
      }
    })();
  }, [rulesLoading, rulesData?.rules_dir, siteId, siteContext.selectedSiteId, refreshFddChart]);

  async function runFddAndRefreshChart() {
    const out = await refreshFddChart();
    if (!out) {
      setRunOutput("Chart refresh failed — see the Plots status message above for the bridge error.");
      return;
    }
    setRunOutput(
      `Rows: ${out.rows.length}\nColumns: ${out.columns.join(", ")}\n\nFault totals:\n${JSON.stringify(out.fault_totals ?? {}, null, 2)}`,
    );
  }

  const { traces, secondaryAxis } = useMemo(() => {
    if (!frame || frame.rows.length === 0 || plotColumns.length === 0) {
      return { traces: [] as Record<string, unknown>[], secondaryAxis: false };
    }
    const mode = plotMode === "both" ? "lines+markers" : plotMode === "points" ? "markers" : "lines";
    const hasFaultAxis = plotColumns.some((c) => isFaultColumn(c));
    const built = plotColumns.map((col, idx) => {
      const faultCol = isFaultColumn(col);
      const x: Array<string | number> = [];
      const y: number[] = [];
      for (const row of frame.rows) {
        const xv = row.timestamp;
        if (typeof xv !== "string" && typeof xv !== "number") continue;
        if (faultCol) {
          const fv = coerceFaultY(row[col]);
          if (fv === null) continue;
          x.push(xv);
          y.push(fv);
        } else {
          const yv = row[col];
          const num = typeof yv === "number" ? yv : Number(yv);
          if (!Number.isFinite(num)) continue;
          x.push(xv);
          y.push(num);
        }
      }
      return {
        x,
        y,
        type: "scatter",
        mode,
        name: col,
        yaxis: faultCol && hasFaultAxis ? "y2" : "y",
        line: {
          color: COLORS[idx % COLORS.length],
          width: 2,
          ...(faultCol ? { shape: "hv" as const } : {}),
        },
        marker: { color: COLORS[idx % COLORS.length], size: faultCol ? 6 : 5 },
      };
    });
    return { traces: built, secondaryAxis: hasFaultAxis };
  }, [frame, plotColumns, plotMode]);

  const plotDebugJson = useMemo(() => {
    if (!frame) {
      return "";
    }
    const sampleN = Math.min(8, frame.rows.length);
    const sampleRows = frame.rows.slice(0, sampleN);
    const tracePreview = traces.map((t) => {
      const x = t.x;
      const y = t.y;
      const xa = Array.isArray(x) ? x : [];
      const ya = Array.isArray(y) ? y : [];
      return {
        type: t.type,
        mode: t.mode,
        name: t.name,
        yaxis: t.yaxis,
        x_len: xa.length,
        y_len: ya.length,
        x_head: xa.slice(0, 5),
        y_head: ya.slice(0, 5),
      };
    });
    return JSON.stringify(
      {
        note:
          "API frame from /plots/frame, /plots/site-frame, or POST /plots/fdd-frame. Traces are built in the browser for Plotly (numeric coercion / fault axis). To normalize messy string metrics before plotting or FDD, use bridge POST /timeseries/clean-metrics (preview then commit).",
        columns: frame.columns,
        row_count: frame.rows.length,
        sample_rows: sampleRows,
        readiness: frame.readiness ?? null,
        fault_totals: frame.fault_totals ?? null,
        sources: frame.sources ?? null,
        plot_columns_used: plotColumns,
        plotly_traces_preview: tracePreview,
      },
      null,
      2,
    );
  }, [frame, traces, plotColumns]);

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Plots</h2>
        <p className="muted">
          Plotly trends from Feather data. Fault columns (<code>_fault</code> / <code>_flag</code>) use a right-hand 0/1 axis when present.
        </p>
        <p className="muted">
          Destructive storage and model cleanup lives under <strong>Data &amp; model maintenance</strong> in the sidebar.
        </p>
        <div className="grid-two">
          <select value={siteId || siteContext.selectedSiteId || ""} onChange={(e) => setSiteId(e.target.value)}>
            {siteContext.sites.length === 0 && <option value="">No sites</option>}
            {siteContext.sites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </select>
          <select value={plotMode} onChange={(e) => setPlotMode(e.target.value as PlotMode)}>
            <option value="lines">Lines</option>
            <option value="points">Points</option>
            <option value="both">Both</option>
          </select>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
          <button type="button" onClick={() => void loadAndPlotNoFdd()}>
            Load &amp; plot (no FDD)
          </button>
          <span className="muted" style={{ fontSize: 12 }}>
            Same source/join/window as the panel below. Response includes a typed <code>readiness</code> object when{" "}
            <code>include_readiness=true</code> on the bridge.
          </span>
        </div>
        <div style={{ marginTop: 10 }}>
          <PointsTreePanel
            points={modelPoints}
            equipment={modelEquipment}
            selectedSiteId={siteId || siteContext.selectedSiteId || ""}
            selectedExternalIds={selectedExternalIds}
            onSelectedExternalIdsChange={setSelectedExternalIds}
            title="Points tree"
            description={
              "Check sensors to plot (matched to frame columns by external_id). Leave empty to auto-pick the first metrics plus all fault columns after a run. "
              + "Rules bind via BRICK / TTL / model maps; joined drivers may suffix columns (e.g. _csv)."
            }
          />
          <details style={{ marginTop: 12 }} className="plots-raw-debug">
            <summary className="muted" style={{ cursor: "pointer", fontSize: 13 }}>
              Raw plot data (JSON) — frame + Plotly trace preview
            </summary>
            <p className="muted" style={{ marginTop: 8, marginBottom: 6, fontSize: 12 }}>
              Shown after <strong>Load &amp; plot</strong> or <strong>Run FDD &amp; refresh chart</strong>. First rows
              and per-trace samples only; full frames stay on the bridge. Clean string metrics via{" "}
              <code>POST /timeseries/clean-metrics</code> (same site/source) if readiness warns.
            </p>
            <textarea
              readOnly
              value={plotDebugJson || "(Run a chart load above — no frame loaded yet.)"}
              spellCheck={false}
              style={{
                marginTop: 4,
                width: "100%",
                minHeight: 220,
                maxHeight: "42vh",
                boxSizing: "border-box",
                overflow: "auto",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                fontSize: 12,
                padding: 10,
                border: "1px solid var(--border)",
                borderRadius: 8,
                background: "var(--input-bg)",
              }}
            />
          </details>
        </div>
        <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 70 }} />
        {effectiveSiteId && runSource !== "all" ? (
          <details
            data-testid="plots-clean-metrics-panel"
            className="plots-clean-metrics-details"
            style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}
          >
            <summary className="muted" style={{ cursor: "pointer", fontSize: 13, lineHeight: 1.5, userSelect: "none" }}>
              <strong>Optional</strong> — clean string metrics on this page (same <code className="inline-code">POST /timeseries/clean-metrics</code> as
              readiness / Local Codex). Expand if you want buttons instead of the API or chat.
            </summary>
            <p className="muted" style={{ fontSize: 12, margin: "10px 0 8px", lineHeight: 1.5 }}>
              Targets values like <code className="inline-code">17.8 psi</code> for the <strong>selected site</strong> and source <strong>{runSource}</strong>.
              Preview does not write; save updates Feather then reloads the chart above.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              <button type="button" className="secondary-btn" disabled={cleanBusy} onClick={() => void runCleanMetricsForPlots(false)}>
                {cleanBusy ? "…" : "Preview string-metric fix"}
              </button>
              <button type="button" disabled={cleanBusy} onClick={() => void runCleanMetricsForPlots(true)}>
                {cleanBusy ? "…" : "Save to Feather & reload chart"}
              </button>
            </div>
            {cleanMsg ? (
              <pre
                style={{
                  marginTop: 10,
                  padding: 10,
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  background: "var(--panel-soft)",
                  fontSize: 12,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  maxHeight: 120,
                  overflow: "auto",
                }}
              >
                {cleanMsg}
              </pre>
            ) : null}
          </details>
        ) : runSource === "all" ? (
          <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
            For <strong>All sources</strong>, switch to one driver here to run string-metric cleaning (one Feather store per source).
          </p>
        ) : null}
      </div>

      <div className="card">
        {traces.length > 0 ? (
          <PlotlyCanvas traces={traces} title="Open-FDD Trends" secondaryAxis={secondaryAxis} />
        ) : (
          <div
            style={{
              minHeight: 360,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--muted)",
              textAlign: "center",
              padding: 16,
            }}
          >
            Configure source and rules in the panel below, pick sensors in the tree (optional), then use{" "}
            <strong>Run FDD &amp; refresh chart</strong>.
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="title" style={{ marginBottom: 6 }}>Run FDD &amp; chart</h3>
        <p className="muted">
          Use <strong>Load &amp; plot (no FDD)</strong> above to preview raw Feather columns first. This section runs rules and refreshes the chart (same pipeline as bridge{" "}
          <code>POST /plots/fdd-frame</code>). For automation-only checks without rows, call{" "}
          <code>POST /timeseries/plot-readiness</code> (Pydantic JSON).
        </p>
        <p className="muted">
          Pick specific rule YAML files to narrow a test, or leave all unchecked to run the full pack. Grafana-style
          string numerics are coerced in bounds/flatline checks; values with units still embedded as text should use{" "}
          <code>POST /timeseries/clean-metrics</code> first.
        </p>
        <p className="muted">
          <strong>Auto-populated bounds:</strong> when a single source is selected (not joined <strong>All sources</strong>
          ), start/end timestamps are filled from Feather for that source after you pick a site.
        </p>
        {boundsStatus ? <p className="muted">{boundsStatus}</p> : null}
        <div className="grid-two">
          <div>
            <label>Source</label>
            <select value={runSource} onChange={(e) => setRunSource(e.target.value)}>
              <option value="all">All sources (joined)</option>
              <option value="csv">CSV</option>
              <option value="weather">Weather</option>
              <option value="onboard">Onboard</option>
              <option value="bacnet">BACnet</option>
            </select>
          </div>
          {runSource === "all" ? (
            <div>
              <label>Join mode (joined sources)</label>
              <select value={joinHow} onChange={(e) => setJoinHow(e.target.value as "inner" | "left" | "outer" | "right")}>
                <option value="outer">outer</option>
                <option value="inner">inner</option>
                <option value="left">left</option>
                <option value="right">right</option>
              </select>
            </div>
          ) : (
            <div>
              <label>Rules</label>
              <input readOnly value="Loaded from FDD Rule Setup" />
            </div>
          )}
          <div>
            <label>Start timestamp (optional, ISO)</label>
            <input value={startTs} onChange={(e) => setStartTs(e.target.value)} placeholder="2026-03-01T00:00:00Z" />
          </div>
          <div>
            <label>End timestamp (optional, ISO)</label>
            <input value={endTs} onChange={(e) => setEndTs(e.target.value)} placeholder="2026-03-31T23:59:59Z" />
          </div>
        </div>
        {(rulesData?.files?.length ?? 0) > 0 ? (
          <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <h3 className="title" style={{ marginBottom: 6 }}>FDD rule files (YAML)</h3>
            <p className="muted">
              Same managed pack as <strong>FDD Rule Setup</strong>. Checked names limit the run; empty = all files.
            </p>
            {rulesListError ? <p style={{ color: "var(--danger)", marginTop: 6 }}>{rulesListError}</p> : null}
            <p className="muted" style={{ marginTop: 8 }}>
              {rulesData?.rules_dir || "Loading rules directory..."}
            </p>
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button type="button" className="secondary-btn" onClick={() => void refreshRulesList()}>
                Refresh
              </button>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setSelectedRuleFiles([...(rulesData?.files ?? [])])}
              >
                Select all
              </button>
              <button type="button" className="secondary-btn" onClick={() => setSelectedRuleFiles([])}>
                Clear selection
              </button>
            </div>
            <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {rulesLoading && <span className="muted">Loading files...</span>}
              {(rulesData?.files ?? []).map((name) => (
                <span
                  key={name}
                  style={{
                    display: "inline-flex",
                    gap: 6,
                    alignItems: "center",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "4px 8px",
                  }}
                >
                  <label
                    style={{
                      display: "inline-flex",
                      gap: 8,
                      alignItems: "center",
                      cursor: "pointer",
                      margin: 0,
                      fontWeight: 400,
                    }}
                  >
                    <input
                      type="checkbox"
                      style={{ width: "auto" }}
                      checked={selectedRuleFiles.includes(name)}
                      onChange={() => toggleRuleFileForBackfill(name)}
                    />
                    <span
                      style={{
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                        fontSize: 13,
                      }}
                    >
                      {name}
                    </span>
                  </label>
                </span>
              ))}
            </div>
            <p className="muted" style={{ marginTop: 8 }}>
              No files checked = run every <code>.yaml</code> / <code>.yml</code> in the managed directory.
            </p>
          </div>
        ) : (
          <p className="muted" style={{ marginTop: 10 }}>
            No rule files in the managed directory yet — add some under FDD Rule Setup.
          </p>
        )}
        <label style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 10 }}>
          <input
            style={{ width: "auto" }}
            type="checkbox"
            checked={skipMissingRules}
            onChange={(e) => setSkipMissingRules(e.target.checked)}
          />
          Skip rules whose sensors are missing from this source/window (log warning, no 400)
        </label>
        <div style={{ marginTop: 10 }}>
          <button type="button" onClick={() => void runFddAndRefreshChart()}>
            Run FDD &amp; refresh chart
          </button>
        </div>
        <textarea readOnly value={runOutput} style={{ marginTop: 10, minHeight: 180 }} />
      </div>
    </div>
  );
}
