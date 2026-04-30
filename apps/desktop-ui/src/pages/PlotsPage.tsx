import { useEffect, useMemo, useRef, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";
import { purgeTimeseries } from "../lib/crud-api";
import { PointsTreePanel } from "../components/site/PointsTreePanel";
import { useRulesList } from "../hooks/use-rules";

type PlotFrameResponse = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
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
          xaxis: { title: "Timestamp", automargin: true },
          yaxis: { title: "Value", automargin: true },
          legend: { orientation: "h" },
        },
        { responsive: true, displaylogo: false },
      );
    }
    void draw();
    return () => {
      mounted = false;
    };
  }, [traces, title]);
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
  const [prunePoints, setPrunePoints] = useState(false);
  const [purging, setPurging] = useState(false);
  const [modelPoints, setModelPoints] = useState<ModelExportResponse["points"]>([]);
  const [modelEquipment, setModelEquipment] = useState<ModelExportResponse["equipment"]>([]);
  const [selectedExternalIds, setSelectedExternalIds] = useState<string[]>([]);
  const [runSource, setRunSource] = useState("all");
  const [joinHow, setJoinHow] = useState<"inner" | "left" | "outer" | "right">("outer");
  const [startTs, setStartTs] = useState("");
  const [endTs, setEndTs] = useState("");
  const [boundsStatus, setBoundsStatus] = useState("");
  const [runOutput, setRunOutput] = useState("Use this panel to run/backfill FDD faults over a site/source/time window.");
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

  async function loadData() {
    try {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) {
        setStatus("Set or select a site first.");
        return;
      }
      const out = source === "all"
        ? await desktopFetch<PlotFrameResponse>(
            `/plots/site-frame?site_id=${encodeURIComponent(effectiveSiteId)}&sources=${encodeURIComponent(
              "csv,weather,onboard,bacnet",
            )}&limit=5000`,
          )
        : await desktopFetch<PlotFrameResponse>(
            `/plots/frame?site_id=${encodeURIComponent(effectiveSiteId)}&source=${encodeURIComponent(source)}&limit=5000`,
          );
      setFrame(out);
      const fromTree = resolveColumnsFromExternalIds(out.columns, selectedExternalIds, source);
      const defaults = out.columns.filter((c) => c !== "timestamp").slice(0, 6);
      setYColumns(fromTree.length > 0 ? fromTree : defaults);
      setStatus(`Loaded ${out.rows.length} rows from ${source === "all" ? "all sources (joined)" : source}.`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function purgeSiteTimeseries() {
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Set or select a site first.");
      return;
    }
    const msg = prunePoints
      ? "Purge timeseries for selected site and remove matching model points? This WILL alter the data model and trigger BRICK TTL sync."
      : "Purge timeseries for selected site? This keeps sites/equipment/points and BRICK model/TTL intact.";
    if (!window.confirm(msg)) return;
    try {
      setPurging(true);
      const out = await purgeTimeseries(effectiveSiteId, prunePoints);
      setFrame(null);
      setYColumns([]);
      setStatus(
        `Purged site timeseries: files=${out.files_deleted}, dirs=${out.dirs_deleted}, bytes=${out.bytes_deleted}, points_removed=${out.points_removed}`,
      );
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setPurging(false);
    }
  }

  async function deleteEntireSite() {
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Set or select a site first.");
      return;
    }
    const siteName = siteContext.sites.find((s) => s.id === effectiveSiteId)?.name ?? "selected site";
    if (!window.confirm(`Delete site "${siteName}" and all associated data? This is destructive.`)) return;
    try {
      await desktopFetch(`/sites/${encodeURIComponent(effectiveSiteId)}`, { method: "DELETE" });
      await siteContext.refreshSites();
      setSiteId("");
      setFrame(null);
      setYColumns([]);
      setStatus(`Deleted site "${siteName}" and associated data model rows.`);
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
        }),
      });
      setRunOutput(
        `Input rows: ${out.input_rows}\nOutput rows: ${out.output_rows}\n`
          + `Columns: ${out.columns.join(", ")}\n`
          + `Fault totals: ${JSON.stringify(out.fault_totals, null, 2)}\n\nPreview:\n${out.preview}`,
      );
      // Re-render plot against the same data context after backfill.
      if (runSource !== source) {
        setSource(runSource);
      }
      await loadData();
    } catch (e) {
      setRunOutput(e instanceof Error ? e.message : String(e));
    }
  }

  const traces = useMemo(() => {
    if (!frame || frame.rows.length === 0 || yColumns.length === 0) return [];
    const mode = plotMode === "both" ? "lines+markers" : plotMode === "points" ? "markers" : "lines";
    return yColumns.map((col, idx) => {
      const x: Array<string | number> = [];
      const y: number[] = [];
      for (const row of frame.rows) {
        const xv = row.timestamp;
        const yv = row[col];
        const num = typeof yv === "number" ? yv : Number(yv);
        if ((typeof xv === "string" || typeof xv === "number") && Number.isFinite(num)) {
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
        line: { color: COLORS[idx % COLORS.length], width: 2 },
        marker: { color: COLORS[idx % COLORS.length], size: 5 },
      };
    });
  }, [frame, yColumns, plotMode]);

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Plots</h2>
        <p className="muted">Plotly trend view for Feather-backed site data (single source or joined multi-source).</p>
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
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void loadData()}>Load Site Data (Feather)</button>
          <button className="secondary-btn" onClick={() => void purgeSiteTimeseries()} disabled={purging}>
            {purging ? "Purging..." : "Purge timeseries (site)"}
          </button>
          <button className="danger-btn" onClick={() => void deleteEntireSite()}>
            Delete entire site
          </button>
          <select value={plotMode} onChange={(e) => setPlotMode(e.target.value as PlotMode)} style={{ width: 160 }}>
            <option value="lines">Lines</option>
            <option value="points">Points</option>
            <option value="both">Both</option>
          </select>
        </div>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 8, marginBottom: 2 }}>
          <input
            style={{ width: "auto" }}
            type="checkbox"
            checked={prunePoints}
            onChange={(e) => setPrunePoints(e.target.checked)}
          />
          Also remove matching points from model and resync BRICK TTL (destructive)
        </label>
        {!prunePoints && (
          <p className="muted" style={{ marginTop: 0 }}>
            Default purge is site-scoped timeseries only; data model (sites/equipment/points) is retained. Use Delete entire site for full wipe.
          </p>
        )}
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
            description="Pick grouped points by equipment/site to quickly populate plotted columns."
          />
        </div>
        <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 70 }} />
      </div>

      <div className="card">
        <h3 className="title" style={{ marginBottom: 6 }}>Run / backfill faults</h3>
        <p className="muted">Run FDD rules on a selected source and optional time window for historical backfill.</p>
        <p className="muted">Chunk sizing is automatic and adapts to available local hardware resources.</p>
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
        <div style={{ marginTop: 10 }}>
          <button onClick={() => void runRulesWindow()}>Run FDD backfill</button>
        </div>
        <textarea readOnly value={runOutput} style={{ marginTop: 10, minHeight: 180 }} />
      </div>

      <div className="card">
        {traces.length > 0 ? (
          <PlotlyCanvas traces={traces} title="Open-FDD Trends" />
        ) : (
          <div style={{ minHeight: 360, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
            Load data and select columns to render Plotly charts.
          </div>
        )}
      </div>
    </div>
  );
}
