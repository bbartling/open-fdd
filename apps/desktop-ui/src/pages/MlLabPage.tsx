import { useEffect, useMemo, useRef, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";

type PlotFrameResponse = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
};

type MlTrainResponse = {
  rows_train: number;
  rows_test: number;
  rows_scored: number;
  model_name: string;
  mae: number;
  rmse: number;
  r2: number;
  residual_threshold: number;
  output_source: string;
  storage_ref: string;
  overlap_with_rule_flag: number;
};

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
          yaxis: { title: "Value / Flag", automargin: true },
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

function parseCsvList(value: string): string[] | null {
  const parts = value.split(",").map((v) => v.trim()).filter(Boolean);
  return parts.length > 0 ? parts : null;
}

function detectTimeKey(frame: PlotFrameResponse | null): string | null {
  if (!frame || frame.rows.length === 0) return null;
  const first = frame.rows[0];
  const keys = Object.keys(first);
  const exact = keys.find((k) => k === "timestamp" || k === "time");
  if (exact) return exact;
  const fuzzy = keys.find((k) => /time|timestamp/i.test(k));
  return fuzzy ?? null;
}

export function MlLabPage() {
  const siteContext = useSite();
  const [siteId, setSiteId] = useState(() => siteContext.selectedSiteId ?? "");
  const [source, setSource] = useState("csv");
  const [targetCol, setTargetCol] = useState("");
  const [featureCols, setFeatureCols] = useState("");
  const [lagCols, setLagCols] = useState("");
  const [ruleFlagCol, setRuleFlagCol] = useState("");
  const [residualQuantile, setResidualQuantile] = useState("0.95");
  const [outputSource, setOutputSource] = useState("");
  const [status, setStatus] = useState("Train ML baseline and compare ML fault flags against rule fault flags.");
  const [trainOut, setTrainOut] = useState<MlTrainResponse | null>(null);
  const [frame, setFrame] = useState<PlotFrameResponse | null>(null);
  const [compareColumns, setCompareColumns] = useState<string[]>([]);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);

  useEffect(() => {
    if (!siteId && siteContext.selectedSiteId) {
      setSiteId(siteContext.selectedSiteId);
    }
  }, [siteId, siteContext.selectedSiteId]);

  useEffect(() => {
    void (async () => {
      const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
      if (!effectiveSiteId) return;
      try {
        const out = await desktopFetch<PlotFrameResponse>(
          `/plots/frame?site_id=${encodeURIComponent(effectiveSiteId)}&source=${encodeURIComponent(source)}&limit=2000`,
        );
        const cols = out.columns.filter((c) => c !== "timestamp");
        setSourceColumns(cols);
      } catch {
        setSourceColumns([]);
      }
    })();
  }, [siteId, source, siteContext.selectedSiteId]);

  async function runTraining() {
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    if (!targetCol.trim()) {
      setStatus("Set target column before training.");
      return;
    }
    const qRaw = (residualQuantile || "").trim();
    const q = Number(qRaw || "0.95");
    if (!Number.isFinite(q) || q <= 0 || q >= 1) {
      setStatus("Residual quantile must be a number strictly between 0 and 1 (for example 0.95).");
      return;
    }
    try {
      const out = await desktopFetch<MlTrainResponse>("/ml/train", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          source,
          target_col: targetCol.trim(),
          feature_cols: parseCsvList(featureCols),
          lag_cols: parseCsvList(lagCols),
          residual_quantile: q,
          rule_flag_col: ruleFlagCol.trim() || null,
          output_source: outputSource.trim() || null,
        }),
      });
      setTrainOut(out);
      setStatus(`ML train complete. model=${out.model_name}, r2=${out.r2.toFixed(3)}, output=${out.output_source}.`);
      await loadComparison(out.output_source);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function loadComparison(mlSourceFromTrain?: string) {
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    const mlSource = mlSourceFromTrain || trainOut?.output_source || outputSource.trim();
    if (!effectiveSiteId || !mlSource) {
      setStatus("Train ML first or provide output source to compare.");
      return;
    }
    try {
      const out = await desktopFetch<PlotFrameResponse>("/timeseries/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          sources: [source, mlSource],
          join_on_timestamp: true,
          join_how: "outer",
          limit: 5000,
        }),
      });
      setFrame(out);
      const mlFault = out.columns.find((c) => c.includes("ml_residual_fault")) || "";
      const ruleFault = out.columns.find((c) => c.includes("_flag") && !c.includes("ml_residual_fault")) || "";
      const target = out.columns.find((c) => c.includes("target_actual")) || "";
      const prediction = out.columns.find((c) => c.includes("ml_prediction")) || "";
      const defaults = [target, prediction, ruleFault, mlFault].filter(Boolean);
      const timeKey = detectTimeKey(out);
      setCompareColumns(defaults.length > 0 ? defaults : out.columns.filter((c) => c !== timeKey).slice(0, 6));
      setStatus(`Loaded ${out.rows.length} joined rows for rule-vs-ML comparison.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  const traces = useMemo(() => {
    if (!frame || frame.rows.length === 0 || compareColumns.length === 0) return [];
    const timeKey = detectTimeKey(frame);
    if (!timeKey) return [];
    return compareColumns.map((col, idx) => {
      const x: Array<string | number> = [];
      const y: number[] = [];
      for (const row of frame.rows) {
        const xv = row[timeKey];
        const yv = row[col];
        const num = typeof yv === "number" ? yv : Number(yv);
        if ((typeof xv === "string" || typeof xv === "number") && Number.isFinite(num)) {
          x.push(xv);
          y.push(num);
        }
      }
      const isFlag = col.includes("_flag") || col.includes("ml_residual_fault");
      return {
        x,
        y,
        type: "scatter",
        mode: isFlag ? "lines+markers" : "lines",
        name: col,
        line: { color: COLORS[idx % COLORS.length], width: isFlag ? 2.5 : 2 },
        marker: { color: COLORS[idx % COLORS.length], size: isFlag ? 6 : 4 },
      };
    });
  }, [frame, compareColumns]);

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">ML Lab</h2>
        <p className="muted">Train baseline ML faults and compare against rule-based fault flags in one chart.</p>
        <div className="grid-two">
          <div>
            <label>Site</label>
            <select value={siteId || siteContext.selectedSiteId || ""} onChange={(e) => setSiteId(e.target.value)}>
              {siteContext.sites.length === 0 && <option value="">No sites</option>}
              {siteContext.sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label>Training source</label>
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="csv">CSV</option>
              <option value="weather">Weather</option>
              <option value="onboard">Onboard</option>
              <option value="bacnet">BACnet</option>
            </select>
          </div>
          <div>
            <label>Target column</label>
            <input value={targetCol} onChange={(e) => setTargetCol(e.target.value)} placeholder="sat or SAT_1" />
          </div>
          <div>
            <label>Residual quantile (0-1)</label>
            <input value={residualQuantile} onChange={(e) => setResidualQuantile(e.target.value)} placeholder="0.95" />
          </div>
          <div>
            <label>Feature columns (comma-separated, optional)</label>
            <input value={featureCols} onChange={(e) => setFeatureCols(e.target.value)} placeholder="oat,damper_position,fan_speed" />
          </div>
          <div>
            <label>Lag columns (comma-separated, optional)</label>
            <input value={lagCols} onChange={(e) => setLagCols(e.target.value)} placeholder="sat,oat" />
          </div>
          <div>
            <label>Rule flag column (optional)</label>
            <input value={ruleFlagCol} onChange={(e) => setRuleFlagCol(e.target.value)} placeholder="economizer_fault_flag" />
          </div>
          <div>
            <label>Output source (optional)</label>
            <input value={outputSource} onChange={(e) => setOutputSource(e.target.value)} placeholder="ml_sat_custom" />
          </div>
        </div>
        {sourceColumns.length > 0 ? (
          <p className="muted" style={{ marginTop: 8 }}>
            Available columns in source preview: {sourceColumns.slice(0, 20).join(", ")}
            {sourceColumns.length > 20 ? " ..." : ""}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void runTraining()}>Train ML baseline</button>
          <button className="secondary-btn" onClick={() => void loadComparison()}>
            Load rule vs ML comparison
          </button>
        </div>
        {trainOut ? (
          <div className="grid-two" style={{ marginTop: 10 }}>
            <div className="card" style={{ padding: 10 }}>
              <strong>Model</strong>: {trainOut.model_name}
            </div>
            <div className="card" style={{ padding: 10 }}>
              <strong>R2</strong>: {trainOut.r2.toFixed(4)}
            </div>
            <div className="card" style={{ padding: 10 }}>
              <strong>MAE</strong>: {trainOut.mae.toFixed(4)}
            </div>
            <div className="card" style={{ padding: 10 }}>
              <strong>RMSE</strong>: {trainOut.rmse.toFixed(4)}
            </div>
            <div className="card" style={{ padding: 10 }}>
              <strong>Threshold</strong>: {trainOut.residual_threshold.toFixed(4)}
            </div>
            <div className="card" style={{ padding: 10 }}>
              <strong>Rule/ML overlap</strong>: {trainOut.overlap_with_rule_flag}
            </div>
          </div>
        ) : null}
        {frame && frame.columns.length > 0 ? (
          <div style={{ marginTop: 10 }}>
            <label>Comparison columns (multi-select)</label>
            {(() => {
              const timeKey = detectTimeKey(frame);
              const selectable = frame.columns.filter((c) => c !== timeKey);
              return (
            <select
              multiple
              value={compareColumns}
              onChange={(e) => setCompareColumns(Array.from(e.target.selectedOptions).map((opt) => opt.value))}
              style={{ minHeight: 120 }}
            >
              {selectable.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
              );
            })()}
          </div>
        ) : null}
        <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 80 }} />
      </div>
      <div className="card">
        {traces.length > 0 ? (
          <PlotlyCanvas traces={traces} title="Rule-based vs ML-based fault comparison" />
        ) : (
          <div style={{ minHeight: 360, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
            Train model and load comparison to render chart.
          </div>
        )}
      </div>
    </div>
  );
}

