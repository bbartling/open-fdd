import { useCallback, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import CsvSessionSidecart from "../components/CsvSessionSidecart";
import { hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  datasetsToCsv,
  downloadCsv,
  fileToDataset,
  mergeDatasets,
  suggestMergeKey,
  type CsvDataset,
  type MergeMode,
} from "../lib/csvWorkbench";
import CsvFusionWiresheet from "../wiresheet/CsvFusionWiresheet";
import {
  datasetFromFusionPreview,
  fetchAgentSessionFusionPreview,
  saveAgentSessionToArrow,
} from "../lib/csvAgentSession";

export default function CsvWorkbenchPage() {
  const [datasets, setDatasets] = useState<CsvDataset[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [mergeKey, setMergeKey] = useState("Date");
  const [mergeMode, setMergeMode] = useState<MergeMode>("append");
  const [ut3SessionId, setUt3SessionId] = useState("");

  const openFusionFromSession = useCallback(async (sessionId: string) => {
    if (!hasToken()) {
      setError("Sign in to load sessions.");
      return;
    }
    setBusy("load");
    setError("");
    try {
      const data = await fetchAgentSessionFusionPreview(sessionId);
      if (!data.ok) throw new Error(data.error ?? "load failed");
      const ds = datasetFromFusionPreview(data, sessionId);
      setUt3SessionId(sessionId);
      setDatasets([ds]);
      setMergeKey(ds.timestampColumn ?? "ts_local");
      setMergeMode("append");
      setStatus(
        `Session ${sessionId} — ${data.row_count?.toLocaleString() ?? ds.rowCount} rows in wiresheet.`,
      );
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, []);

  const merged = useMemo(() => {
    if (!datasets.length) return null;
    try {
      return mergeDatasets(datasets, mergeKey, mergeMode);
    } catch {
      return null;
    }
  }, [datasets, mergeKey, mergeMode]);

  const mergeError = useMemo(() => {
    if (datasets.length < 2) return "";
    try {
      mergeDatasets(datasets, mergeKey, mergeMode);
      return "";
    } catch (e) {
      return formatApiError(e);
    }
  }, [datasets, mergeKey, mergeMode]);

  const ingestFiles = useCallback(async (files: FileList | File[]) => {
    setError("");
    const list = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".csv"));
    if (!list.length) {
      setError("Choose one or more .csv files.");
      return;
    }
    setBusy("parse");
    try {
      const added: CsvDataset[] = [];
      for (const file of list) {
        added.push(fileToDataset(file, await file.text()));
      }
      setDatasets((prev) => {
        const next = [...prev, ...added];
        setMergeKey(suggestMergeKey(next));
        return next;
      });
      setUt3SessionId("");
      setStatus(`Loaded ${added.length} file(s).`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }, []);

  async function saveSessionToArrow() {
    if (!ut3SessionId) {
      setError("Open an import session from the sidecart first.");
      return;
    }
    setBusy("arrow");
    try {
      const out = await saveAgentSessionToArrow(ut3SessionId);
      if (!out.ok) throw new Error(out.error ?? "save failed");
      setStatus(`Saved to Arrow (${out.dataset_id ?? ut3SessionId}). Open Plots to chart.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="page page-wide csv-workbench-page">
      <PageHeader title="CSV Fusion" subtitle="Drop building CSVs · wiresheet merge · save via agent or Arrow store" />

      <div className="csv-page-layout">
        <CsvSessionSidecart activeSessionId={ut3SessionId} onOpenSession={(id) => void openFusionFromSession(id)} />

        <div className="csv-page-main">
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
            <p className="muted">Any wide-format building CSV — site/equip/source derived from filename</p>
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

          {datasets.length > 0 ? (
            <section className="panel csv-fusion-panel">
              <h3 className="panel-title">Fusion wiresheet</h3>
              <CsvFusionWiresheet
                datasets={datasets}
                mergeKey={mergeKey}
                mergeMode={mergeMode}
                onMergeKeyChange={setMergeKey}
                onMergeModeChange={setMergeMode}
              />
              <div className="csv-merge-controls form-grid">
                <label className="field">
                  <span className="field-label">Timestamp column</span>
                  <input value={mergeKey} onChange={(e) => setMergeKey(e.target.value)} />
                </label>
                <label className="field">
                  <span className="field-label">Merge mode</span>
                  <select value={mergeMode} onChange={(e) => setMergeMode(e.target.value as MergeMode)}>
                    <option value="append">Append rows</option>
                    <option value="inner">Join on timestamp</option>
                  </select>
                </label>
              </div>
              <div className="toolbar">
                {ut3SessionId ? (
                  <button type="button" className="primary-btn" disabled={!!busy} onClick={() => void saveSessionToArrow()}>
                    {busy === "arrow" ? "Saving…" : "Save to Arrow store"}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="secondary-btn"
                  disabled={!merged}
                  onClick={() => merged && downloadCsv("openfdd-merged.csv", merged.columns, merged.rows)}
                >
                  Export merged CSV
                </button>
                <a className="secondary-btn" href="/plot">
                  Open Plots
                </a>
                <button
                  type="button"
                  className="linkish-btn"
                  onClick={() => {
                    setDatasets([]);
                    setUt3SessionId("");
                    setStatus("");
                  }}
                >
                  Clear
                </button>
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
