import { useEffect, useMemo, useRef, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";
import { PointsTreePanel } from "../components/site/PointsTreePanel";
import { useRulesList } from "../hooks/use-rules";

type PlotFrameResponse = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  sources?: string[];
  fault_totals?: Record<string, number>;
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
  const parts = name.split("_").map((p) => p.toLowerCase());
  return parts.some((p) => p === "flag" || p === "fault");
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

export function PlotsPage() {
  const siteContext = useSite();
  const [siteId, setSiteId] = useState(() => siteContext.selectedSiteId ?? "");
  const [source, setSource] = useState("all");
  const [plotMode, setPlotMode] = useState<PlotMode>("lines");
  const [frame, setFrame] = useState<PlotFrameResponse | null>(null);
  const [yColumns, setYColumns] = useState<string[]>([]);
  const [status, setStatus] = useState("Load data, choose columns, then plot.");
  const [modelPoints, setModelPoints] = useState<ModelExportResponse["points"]>([]);
  const [modelEquipment, setModelEquipment] = useState<ModelExportResponse["equipment"]>([]);
  const [selectedExternalIds, setSelectedExternalIds] = useState<string[]>([]);
  const [runSource, setRunSource] = useState("all");
  const [joinHow, setJoinHow] = useState<"inner" | "left" | "outer" | "right">("outer");
  const [startTs, setStartTs] = useState("");
  const [endTs, setEndTs] = useState("");
  const [boundsStatus, setBoundsStatus] = useState("");
  const [runOutput, setRunOutput] = useState("Use this panel to run/backfill FDD faults over a site/source/time window.");
  const [selectedRuleFiles, setSelectedRuleFiles] = useState<string[]>([]);
  const [skipMissingRules, setSkipMissingRules] = useState(false);
  const { data: rulesData } = useRulesList();

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

  async function loadDataWithFddOverlay() {
    try {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) {
        setStatus("Set or select a site first.");
        return;
      }
      const rulesPath = rulesData?.rules_dir || "";
      if (!rulesPath) {
        setStatus("Rules directory is not ready yet (FDD Rule Setup).");
        return;
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
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

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
          Plotly trend view for Feather-backed site data (single source or joined multi-source). Columns whose names contain
          {" "}
          <code>fault</code> or <code>flag</code> as underscore-separated tokens render on a right-hand 0/1 axis so they align with sensor trends.
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
          <div style={{ marginTop: 12 }}>
            <label>Rule YAML files (optional)</label>
            <select
              multiple
              value={selectedRuleFiles}
              onChange={(e) => setSelectedRuleFiles(Array.from(e.target.selectedOptions).map((opt) => opt.value))}
              style={{ minHeight: 100, width: "100%", maxWidth: 560 }}
            >
              {(rulesData?.files ?? []).map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
            <p className="muted" style={{ marginTop: 4 }}>
              None selected = run every <code>.yaml</code> / <code>.yml</code> in the pack. Hold Ctrl/Cmd to pick several.
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
