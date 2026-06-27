import { useCallback, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { apiFetch, apiUploadRaw, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  downloadCsv,
  fileToDataset,
  mergeDatasets,
  numericColumns,
  numericSeries,
  type CsvDataset,
  type MergeMode,
} from "../lib/csvWorkbench";

type JobStatus = {
  ok?: boolean;
  job_id?: string;
  status?: string;
  rows_committed?: number;
  bytes?: number;
};

export default function CsvWorkbenchPage() {
  const [datasets, setDatasets] = useState<CsvDataset[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [mergeKey, setMergeKey] = useState("Date");
  const [mergeMode, setMergeMode] = useState<MergeMode>("inner");
  const [chartX, setChartX] = useState("");
  const [chartY, setChartY] = useState("");

  const merged = useMemo(() => {
    if (!datasets.length) return null;
    try {
      return mergeDatasets(datasets, mergeKey, mergeMode);
    } catch (e) {
      return null;
    }
  }, [datasets, mergeKey, mergeMode]);

  const mergeError = useMemo(() => {
    if (!datasets.length || datasets.length === 1) return "";
    try {
      mergeDatasets(datasets, mergeKey, mergeMode);
      return "";
    } catch (e) {
      return formatApiError(e);
    }
  }, [datasets, mergeKey, mergeMode]);

  const numericCols = useMemo(
    () => (merged ? numericColumns(merged.columns, merged.rows) : []),
    [merged],
  );

  const chartSeries = useMemo(() => {
    if (!merged || !chartX || !chartY) return null;
    return numericSeries(merged.columns, merged.rows, chartX, chartY);
  }, [merged, chartX, chartY]);

  const ingestFiles = useCallback(async (files: FileList | File[]) => {
    setError("");
    const list = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".csv") || f.type.includes("csv"));
    if (!list.length) {
      setError("Drop or pick one or more .csv files.");
      return;
    }
    setBusy("parse");
    try {
      const added: CsvDataset[] = [];
      for (const file of list) {
        const text = await file.text();
        const ds = fileToDataset(file, text);
        added.push(ds);
      }
      setDatasets((prev) => [...prev, ...added]);
      if (added[0]?.timestampColumn) setMergeKey(added[0].timestampColumn);
      if (added[0]?.columns.length) {
        const nums = numericColumns(added[0].columns, added[0].rows);
        setChartX(added[0].timestampColumn || added[0].columns[0] || "");
        setChartY(nums[0] || added[0].columns[1] || "");
      }
      setStatus(`Loaded ${added.length} file(s) — preview shows first ~500 rows per file.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, []);

  async function commitToHistorian() {
    if (!datasets.length) {
      setError("Load a CSV file first.");
      return;
    }
    if (!hasToken()) {
      setError("Sign in as integrator to commit CSV to the historian.");
      return;
    }
    setBusy("commit");
    setError("");
    try {
      let csvBody: string;
      if (datasets.length === 1) {
        csvBody = datasets[0].fullText;
      } else if (merged) {
        csvBody = [
          merged.columns.join(","),
          ...merged.rows.map((r) =>
            r.map((c) => (c.includes(",") || c.includes('"') ? `"${c.replace(/"/g, '""')}"` : c)).join(","),
          ),
        ].join("\n");
        setStatus("Note: merged commit uses all merged rows from loaded files.");
      } else {
        throw new Error("Nothing to commit");
      }
      const sourceFilename = datasets.length === 1 ? datasets[0].name : "openfdd-merged.csv";
      const created = await apiFetch<JobStatus>("/api/import/jobs", {
        method: "POST",
        body: JSON.stringify({ source_filename: sourceFilename }),
      });
      if (!created.job_id) throw new Error("Could not create import job");
      await apiUploadRaw(`/api/import/jobs/${encodeURIComponent(created.job_id)}/upload`, csvBody, "text/csv");
      await apiFetch(`/api/import/jobs/${encodeURIComponent(created.job_id)}/preview`);
      const committed = await apiFetch<JobStatus>(
        `/api/import/jobs/${encodeURIComponent(created.job_id)}/commit`,
        { method: "POST", body: "{}" },
      );
      setStatus(
        `Historian commit OK — ${committed.rows_committed ?? 0} rows from ${sourceFilename} (Haystack model updated automatically).`,
      );
      window.dispatchEvent(new CustomEvent("ofdd-dashboard-refresh"));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function createRcxReport() {
    if (!hasToken()) {
      setError("Sign in to generate RCx PDF reports.");
      return;
    }
    setBusy("report");
    setError("");
    try {
      const draft = await apiFetch<{ report_id?: string }>("/api/reports/draft", {
        method: "POST",
        body: JSON.stringify({
          template_id: "rcx-universal-3",
          title: "RCx Universal 3 — CSV Workbench Report",
        }),
      });
      if (!draft.report_id) throw new Error("Report draft failed");
      await apiFetch(`/api/reports/${draft.report_id}/render/pdf`, { method: "POST" });
      setStatus(`Report ${draft.report_id} — open Reports tab to preview/download PDF.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  function removeDataset(id: string) {
    setDatasets((prev) => prev.filter((d) => d.id !== id));
  }

  return (
    <div className="page page-wide csv-workbench-page">
      <PageHeader
        title="CSV workbench"
        subtitle="Drag CSV files, preview and merge on time, chart trends, export merged CSV, or commit to the historian — Haystack sites, equipment, and points are created automatically from the file name and columns."
      />

      {error ? <p className="error">{error}</p> : null}
      {mergeError ? <p className="error">{mergeError}</p> : null}
      {status ? <p className="ok">{status}</p> : null}

      <div
        className={`csv-drop-zone${dragOver ? " csv-drop-zone-active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void ingestFiles(e.dataTransfer.files);
        }}
      >
        <p className="csv-drop-title">Drop CSV files here</p>
        <p className="muted">LBNL MZVAV, trend exports, or any wide-format building CSV</p>
        <label className="primary-btn csv-drop-btn">
          {busy === "parse" ? "Parsing…" : "Choose files"}
          <input
            type="file"
            accept=".csv,text/csv"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files?.length) void ingestFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      {datasets.length ? (
        <section className="panel">
          <h3 className="panel-title">Loaded datasets ({datasets.length})</h3>
          <ul className="csv-dataset-list">
            {datasets.map((ds) => (
              <li key={ds.id}>
                <strong>{ds.name}</strong>
                <span className="muted">
                  {" "}
                  — {ds.rowCount.toLocaleString()} rows · {ds.columns.length} cols ·{" "}
                  {(ds.bytes / 1024).toFixed(0)} KB
                </span>
                <button type="button" className="linkish-btn" onClick={() => removeDataset(ds.id)}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <div className="form-grid">
            <label className="field">
              <span className="field-label">Merge key</span>
              <input value={mergeKey} onChange={(e) => setMergeKey(e.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">Merge mode</span>
              <select value={mergeMode} onChange={(e) => setMergeMode(e.target.value as MergeMode)}>
                <option value="inner">Inner join on key (UT3 combine)</option>
                <option value="append">Append rows (stack datasets)</option>
              </select>
            </label>
          </div>
          <div className="toolbar">
            <button
              type="button"
              className="secondary-btn"
              disabled={!merged}
              onClick={() =>
                merged && downloadCsv("openfdd-merged.csv", merged.columns, merged.rows)
              }
            >
              Export merged CSV
            </button>
            <button type="button" className="secondary-btn" disabled={!!busy || !datasets.length} onClick={() => void commitToHistorian()}>
              {busy === "commit" ? "Committing…" : "Commit merged → historian"}
            </button>
            <button type="button" className="secondary-btn" disabled={!!busy} onClick={() => void createRcxReport()}>
              {busy === "report" ? "Creating…" : "Draft RCx PDF report"}
            </button>
            <button type="button" className="linkish-btn" onClick={() => setDatasets([])}>
              Clear all
            </button>
          </div>
        </section>
      ) : null}

      {merged && merged.columns.length ? (
        <>
          <section className="panel">
            <h3 className="panel-title">
              Merged preview ({merged.rowCount.toLocaleString()} rows in sample)
            </h3>
            <div className="table-wrap csv-preview-table">
              <table>
                <thead>
                  <tr>
                    {merged.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {merged.rows.slice(0, 12).map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <h3 className="panel-title">Quick trend chart</h3>
            <div className="form-grid">
              <label className="field">
                <span className="field-label">X axis</span>
                <select value={chartX} onChange={(e) => setChartX(e.target.value)}>
                  {merged.columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Y axis (numeric)</span>
                <select value={chartY} onChange={(e) => setChartY(e.target.value)}>
                  {numericCols.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {chartSeries && chartSeries.y.length ? (
              <div className="csv-spark-chart" aria-label="Trend preview">
                <svg viewBox="0 0 400 120" preserveAspectRatio="none">
                  <polyline
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth="1.5"
                    points={chartSeries.y
                      .map((v, i) => {
                        const min = Math.min(...chartSeries.y);
                        const max = Math.max(...chartSeries.y);
                        const span = max - min || 1;
                        const x = (i / Math.max(chartSeries.y.length - 1, 1)) * 400;
                        const y = 110 - ((v - min) / span) * 100;
                        return `${x},${y}`;
                      })
                      .join(" ")}
                  />
                </svg>
                <p className="muted">
                  {chartY} vs {chartX} ({chartSeries.y.length} points sampled)
                </p>
              </div>
            ) : (
              <p className="muted">Select numeric columns to preview a trend.</p>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
