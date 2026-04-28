import { useEffect, useMemo, useRef, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useOptionalSite } from "../contexts/site-context";
import { purgeTimeseries } from "../lib/crud-api";

type PlotFrameResponse = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
};

type PlotMode = "lines" | "points" | "both";

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
  const siteContext = useOptionalSite();
  const [siteId, setSiteId] = useState(() => siteContext?.selectedSiteId ?? "");
  const [source, setSource] = useState("csv");
  const [plotMode, setPlotMode] = useState<PlotMode>("lines");
  const [frame, setFrame] = useState<PlotFrameResponse | null>(null);
  const [yColumns, setYColumns] = useState<string[]>([]);
  const [status, setStatus] = useState("Load data, choose columns, then plot.");
  const [prunePoints, setPrunePoints] = useState(false);
  const [purging, setPurging] = useState(false);

  useEffect(() => {
    if (!siteId && siteContext?.selectedSiteId) {
      setSiteId(siteContext.selectedSiteId);
    }
  }, [siteId, siteContext?.selectedSiteId]);

  async function loadData() {
    try {
      const effectiveSiteId = siteId || siteContext?.selectedSiteId || "";
      if (!effectiveSiteId) {
        setStatus("Set or select a site first.");
        return;
      }
      const out = await desktopFetch<PlotFrameResponse>(
        `/plots/frame?site_id=${encodeURIComponent(effectiveSiteId)}&source=${encodeURIComponent(source)}&limit=5000`,
      );
      setFrame(out);
      const defaults = out.columns.filter((c) => c !== "timestamp").slice(0, 6);
      setYColumns(defaults);
      setStatus(`Loaded ${out.rows.length} rows from ${source}.`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function purgeSiteTimeseries() {
    const effectiveSiteId = siteId || siteContext?.selectedSiteId || "";
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
        <p className="muted">AFDD-style Plotly trend view for desktop timeseries.</p>
        <div className="grid-two">
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="site id" />
          <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="source (csv/weather/onboard)" />
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void loadData()}>Load Data from Database</button>
          <button className="secondary-btn" onClick={() => void purgeSiteTimeseries()} disabled={purging}>
            {purging ? "Purging..." : "Purge timeseries (site)"}
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
            Default purge is site-scoped timeseries only; data model (sites/equipment/points) is retained.
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
        <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 70 }} />
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
