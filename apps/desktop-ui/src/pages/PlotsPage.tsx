import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";
import { PointsTreePanel } from "../components/site/PointsTreePanel";
import { useRulesList } from "../hooks/use-rules";
import { parsePlotsSearch } from "../lib/plots-url";

type PlotFrameResponse = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  sources?: string[];
  fault_totals?: Record<string, number>;
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

type PlotShareCreateResponse = PlotFrameResponse & {
  share_id?: string;
  plots_open_url?: string;
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
  const [source, setSource] = useState("all");
  const [plotMode, setPlotMode] = useState<PlotMode>("lines");
  const [frame, setFrame] = useState<PlotFrameResponse | null>(null);
  const [yColumns, setYColumns] = useState<string[]>([]);
  const [status, setStatus] = useState("Load data, choose columns, then plot.");
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
  const [runOutput, setRunOutput] = useState("Use this panel to run/backfill FDD faults over a site/source/time window.");
  const [selectedRuleFiles, setSelectedRuleFiles] = useState<string[]>([]);
  /** Default true so mixed rule packs (VAV + AHU) do not 400 when a site lacks zone points. */
  const [skipMissingRules, setSkipMissingRules] = useState(() => initialPlots.skipMissingRules !== false);
  const { data: rulesData, isLoading: rulesLoading, error: rulesListError, refresh: refreshRulesList } = useRulesList();

  const toggleRuleFileForBackfill = useCallback((name: string) => {
    setSelectedRuleFiles((prev) => (prev.includes(name) ? prev.filter((f) => f !== name) : [...prev, name]));
  }, []);
  /** One-shot FDD overlay from `?fdd=1` / `?overlay=1` after rules list is ready (not used with `?share=`). */
  const urlAutoFddPending = useRef(Boolean(initialPlots.autoFddOverlay) && !shareFromUrl);
  const shareHydrated = useRef(false);

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
        const fromTree = resolveColumnsFromExternalIds(out.columns, selectedExternalIds, overlaySource);
        const faultCols = out.columns.filter((c) => isFaultColumn(c));
        const defaultYs = [...fromTree.filter((c) => !isFaultColumn(c)).slice(0, 4), ...faultCols.slice(0, 3)];
        const fallback = [...out.columns.filter((c) => c !== "timestamp" && !isFaultColumn(c)).slice(0, 4), ...faultCols];
        setYColumns(defaultYs.length > 0 ? defaultYs : fallback);
        setSource(srcs.length > 1 ? "all" : srcs[0]);
        const ft = out.fault_totals && Object.keys(out.fault_totals).length > 0
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

  async function savePlotFddHandoff() {
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    const rulesPath = rulesData?.rules_dir || "";
    if (!effectiveSiteId || !rulesPath) {
      setStatus("Select a site and wait for the rules directory (FDD Rule Setup) before saving a share.");
      return;
    }
    const sources = runSource === "all" ? ["csv", "weather", "onboard", "bacnet"] : [runSource];
    try {
      const out = await desktopFetch<PlotShareCreateResponse>("/plots/share", {
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
      const url = out.plots_open_url || "";
      setStatus(
        url
          ? `Saved plot+FDD handoff (paste into Open-FDD Claw or chat). ${url}`
          : `Share created (share_id=${String(out.share_id || "")}).`,
      );
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function loadData(sourceOverride?: string) {
    try {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) {
        setStatus("Set or select a site first.");
        return;
      }
      const sourceToLoad = sourceOverride ?? source;
      const out = sourceToLoad === "all"
        ? await desktopFetch<PlotFrameResponse>(
            `/plots/site-frame?site_id=${encodeURIComponent(effectiveSiteId)}&sources=${encodeURIComponent(
              "csv,weather,onboard,bacnet",
            )}&limit=5000`,
          )
        : await desktopFetch<PlotFrameResponse>(
            `/plots/frame?site_id=${encodeURIComponent(effectiveSiteId)}&source=${encodeURIComponent(sourceToLoad)}&limit=5000`,
          );
      setFrame(out);
      const fromTree = resolveColumnsFromExternalIds(out.columns, selectedExternalIds, sourceToLoad);
      const defaults = out.columns.filter((c) => c !== "timestamp").slice(0, 6);
      setYColumns(fromTree.length > 0 ? fromTree : defaults);
      setStatus(`Loaded ${out.rows.length} rows from ${sourceToLoad === "all" ? "all sources (joined)" : sourceToLoad}.`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  const loadDataWithFddOverlay = useCallback(async (): Promise<boolean> => {
    try {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) {
        setStatus("Set or select a site first.");
        return false;
      }
      const rulesPath = rulesData?.rules_dir || "";
      if (!rulesPath) {
        setStatus("Rules directory is not ready yet (FDD Rule Setup).");
        return false;
      }
      const sources =
        runSource === "all" ? ["csv", "weather", "onboard", "bacnet"] : [runSource];
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
      const fromTree = resolveColumnsFromExternalIds(out.columns, selectedExternalIds, overlaySource);
      const faultCols = out.columns.filter((c) => isFaultColumn(c));
      const defaultYs = [...fromTree.filter((c) => !isFaultColumn(c)).slice(0, 4), ...faultCols.slice(0, 3)];
      const fallback = [...out.columns.filter((c) => c !== "timestamp" && !isFaultColumn(c)).slice(0, 4), ...faultCols];
      setYColumns(defaultYs.length > 0 ? defaultYs : fallback);
      const ft = out.fault_totals && Object.keys(out.fault_totals).length > 0
        ? ` Fault totals: ${JSON.stringify(out.fault_totals)}`
        : "";
      setStatus(
        `Loaded ${out.rows.length} rows with FDD columns (${overlaySource}).${ft} Pick Y columns to plot sensors and faults together.`,
      );
      if (runSource !== source) {
        setSource(runSource === "all" ? "all" : runSource);
      }
      return true;
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
      return false;
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
    selectedExternalIds,
    source,
  ]);

  useEffect(() => {
    if (!urlAutoFddPending.current) return;
    if (rulesLoading || !rulesData?.rules_dir) return;
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus(
        "This URL requests an FDD overlay (?fdd=1) but no site was selected. Add ?site_id=<uuid> or pick a site, then use Load + FDD overlay.",
      );
      urlAutoFddPending.current = false;
      return;
    }
    urlAutoFddPending.current = false;
    void (async () => {
      const ok = await loadDataWithFddOverlay();
      if (ok && typeof window !== "undefined") {
        const u = new URL(window.location.href);
        if (u.searchParams.get("fdd") === "1" || u.searchParams.get("overlay") === "1") {
          u.searchParams.delete("fdd");
          u.searchParams.delete("overlay");
          const s = u.searchParams.toString();
          window.history.replaceState({}, "", `${u.pathname}${s ? `?${s}` : ""}`);
        }
      }
    })();
  }, [
    rulesLoading,
    rulesData?.rules_dir,
    siteId,
    siteContext.selectedSiteId,
    loadDataWithFddOverlay,
  ]);

  async function runRulesWindow() {
    try {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) {
        setRunOutput("Select a site first.");
        return;
      }
      const rulesPath = rulesData?.rules_dir || "";
      if (!rulesPath) {
        setRunOutput("Rules directory is not ready yet. Load YAML files in FDD Rule Setup and refresh.");
        return;
      }
      const out = await desktopFetch<{
        input_rows: number;
        output_rows: number;
        columns: string[];
        fault_totals: Record<string, number>;
        preview: string;
        rule_files_filter?: string[] | null;
        skip_missing_columns?: boolean;
      }>("/rules/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          source: runSource === "all" ? "csv" : runSource,
          sources: runSource === "all" ? ["csv", "weather", "onboard", "bacnet"] : undefined,
          join_how: runSource === "all" ? joinHow : undefined,
          rules_path: rulesPath,
          chunk_rows: 0,
          start_ts: startTs || null,
          end_ts: endTs || null,
          rule_files: selectedRuleFiles.length > 0 ? selectedRuleFiles : undefined,
          skip_missing_columns: skipMissingRules,
        }),
      });
      const filterLine = out.rule_files_filter?.length
        ? `Rule files: ${out.rule_files_filter.join(", ")}\n`
        : "Rule files: (all YAML in pack)\n";
      const skipLine = `Skip missing columns: ${out.skip_missing_columns ? "yes" : "no"}\n`;
      setRunOutput(
        `${filterLine}${skipLine}\n`
          + `Input rows: ${out.input_rows}\nOutput rows: ${out.output_rows}\n`
          + `Columns: ${out.columns.join(", ")}\n`
          + `Fault totals: ${JSON.stringify(out.fault_totals, null, 2)}\n\nPreview:\n${out.preview}`,
      );
      if (runSource !== source) {
        setSource(runSource);
      }
      await loadData(runSource);
    } catch (e) {
      setRunOutput(e instanceof Error ? e.message : String(e));
    }
  }

  const { traces, secondaryAxis } = useMemo(() => {
    if (!frame || frame.rows.length === 0 || yColumns.length === 0) {
      return { traces: [] as Record<string, unknown>[], secondaryAxis: false };
    }
    const mode = plotMode === "both" ? "lines+markers" : plotMode === "points" ? "markers" : "lines";
    const hasFaultAxis = yColumns.some((c) => isFaultColumn(c));
    const built = yColumns.map((col, idx) => {
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
  }, [frame, yColumns, plotMode]);

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Plots</h2>
        <p className="muted">
          Plotly trend view for Feather-backed site data (single source or joined multi-source).           Columns whose names end with <code>_fault</code> or <code>_flag</code> (same convention as the bridge fault totals) render on a right-hand 0/1 axis so they align with sensor trends.
        </p>
        <p className="muted">
          Destructive storage and model cleanup lives under{" "}
          <strong>Data &amp; model maintenance</strong> in the sidebar.
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
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="all">All sources (joined)</option>
            <option value="csv">CSV</option>
            <option value="weather">Weather</option>
            <option value="onboard">Onboard</option>
            <option value="bacnet">BACnet</option>
          </select>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
          <button type="button" onClick={() => void loadData()}>Load Site Data (Feather)</button>
          <button type="button" className="secondary-btn" onClick={() => void loadDataWithFddOverlay()}>
            Load + FDD overlay
          </button>
          <button type="button" className="secondary-btn" onClick={() => void savePlotFddHandoff()}>
            Save plot+FDD handoff (share link)
          </button>
          <span className="muted" style={{ fontSize: 12 }}>
            Overlay uses the <strong>Run / backfill</strong> source/join, time window, rule file filter, and skip-missing settings below.
          </span>
          <select value={plotMode} onChange={(e) => setPlotMode(e.target.value as PlotMode)} style={{ width: 160 }}>
            <option value="lines">Lines</option>
            <option value="points">Points</option>
            <option value="both">Both</option>
          </select>
        </div>
        {frame && frame.columns.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <label>Y columns (multi-select)</label>
            <select
              multiple
              value={yColumns}
              onChange={(e) => setYColumns(Array.from(e.target.selectedOptions).map((opt) => opt.value))}
              style={{ minHeight: 120 }}
            >
              {frame.columns.filter((c) => c !== "timestamp").map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          <PointsTreePanel
            points={modelPoints}
            equipment={modelEquipment}
            selectedSiteId={siteId || siteContext.selectedSiteId || ""}
            selectedExternalIds={selectedExternalIds}
            onSelectedExternalIdsChange={(ids) => {
              setSelectedExternalIds(ids);
              if (frame) {
                const matched = resolveColumnsFromExternalIds(frame.columns, ids, source);
                if (matched.length > 0) setYColumns(matched);
              }
            }}
            title="Points tree (quick pick)"
            description={
              "Pick sensors by equipment to set plotted Y columns. "
              + "Unassigned means the point has no equipment_id or the UUID is not in the model—assign equipment in Data Model BRICK or import so equipment[].id matches. "
              + "Second line shows brick_type; rules resolve columns via TTL maps (ofdd:mapsToRuleInput) and these labels. "
              + "If joined backfill fails with a missing name, use Data Model Testing → lineage or align external_id with the Feather column (see _csv suffixes when multiple drivers load)."
            }
          />
        </div>
        <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 70 }} />
      </div>

      <div className="card">
        {traces.length > 0 ? (
          <PlotlyCanvas traces={traces} title="Open-FDD Trends" secondaryAxis={secondaryAxis} />
        ) : (
          <div style={{ minHeight: 360, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
            Load data and select columns to render Plotly charts.
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="title" style={{ marginBottom: 6 }}>Run / backfill faults</h3>
        <p className="muted">Run FDD rules on a selected source and optional time window for historical backfill.</p>
        <p className="muted">Chunk sizing is automatic and adapts to available local hardware resources.</p>
        <p className="muted">
          Pick specific rule YAML files to test one fault at a time, or leave the list empty to run the whole pack.
          Use <strong>All sources (joined)</strong> when a rule needs columns from more than one driver. Enable skip-missing
          to run every selected rule that can bind to your frame and quietly skip the rest (good for wide packs while the model is incomplete).
        </p>
        <p className="muted">
          <strong>Auto-populated from loaded dataset bounds:</strong> when a single timeseries source is selected (not joined{" "}
          <strong>All sources</strong>), start and end timestamps below are filled from the Feather time range for that source after you pick a site
          (change them before backfill if you need a narrower window).
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
              <label>Rules directory</label>
              <input readOnly value="From FDD Rule Setup (see file list below)" />
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
              Same managed pack as <strong>FDD Rule Setup</strong>. Check rules to include in this backfill only; leave all unchecked to run the whole pack.
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
          <p className="muted" style={{ marginTop: 10 }}>No rule files in the managed directory yet — add some under FDD Rule Setup.</p>
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
          <button type="button" onClick={() => void runRulesWindow()}>Run FDD backfill</button>
        </div>
        <textarea readOnly value={runOutput} style={{ marginTop: 10, minHeight: 180 }} />
      </div>
    </div>
  );
}
