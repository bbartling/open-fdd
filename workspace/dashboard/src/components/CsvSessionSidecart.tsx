import { useCallback, useEffect, useState, type MouseEvent } from "react";
import { apiFetch, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { fetchAgentSessionFusionPreview } from "../lib/csvAgentSession";
import CsvDataPreview from "./CsvDataPreview";

type SessionRow = { session_id?: string; created_at?: string; status?: string };
type DatasetRow = { id?: string; name?: string; row_count?: number };

type PreviewState =
  | { kind: "none" }
  | { kind: "session"; id: string; title: string; columns: string[]; rows: string[][]; rowCount?: number; meta?: string }
  | { kind: "dataset"; id: string; title: string; columns: string[]; rows: Record<string, unknown>[]; rowCount?: number; meta?: string };

type Props = {
  activeSessionId?: string;
  onOpenSession: (sessionId: string) => void;
};

export default function CsvSessionSidecart({ activeSessionId, onOpenSession }: Props) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [datasets, setDatasets] = useState<DatasetRow[]>([]);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<PreviewState>({ kind: "none" });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");

  const refresh = useCallback(async () => {
    if (!hasToken()) return;
    setError("");
    try {
      const [sess, ds] = await Promise.all([
        apiFetch<{ ok?: boolean; sessions?: SessionRow[] }>("/api/csv/import/sessions?limit=12"),
        apiFetch<{ ok?: boolean; datasets?: DatasetRow[] }>("/api/datasets"),
      ]);
      setSessions(sess.sessions ?? []);
      setDatasets(ds.datasets ?? []);
    } catch (e) {
      setError(formatApiError(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function previewSession(sessionId: string, e: MouseEvent) {
    e.stopPropagation();
    setPreviewLoading(true);
    setPreviewError("");
    setPreview({ kind: "none" });
    try {
      const data = await fetchAgentSessionFusionPreview(sessionId, 20);
      if (!data.ok) throw new Error(data.error ?? "preview failed");
      setPreview({
        kind: "session",
        id: sessionId,
        title: `Session ${sessionId}`,
        columns: data.columns ?? [],
        rows: data.rows ?? [],
        rowCount: data.row_count,
        meta: data.truncated ? `Preview truncated · ${data.row_count?.toLocaleString() ?? "?"} total rows` : undefined,
      });
    } catch (err) {
      setPreviewError(formatApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function previewDataset(datasetId: string, name: string) {
    setPreviewLoading(true);
    setPreviewError("");
    setPreview({ kind: "none" });
    try {
      const data = await apiFetch<{
        ok?: boolean;
        error?: string;
        rows?: Record<string, unknown>[];
        metadata?: Record<string, unknown>;
        dataset_id?: string;
      }>(`/api/datasets/${encodeURIComponent(datasetId)}/preview?limit=20`);
      if (!data.ok) throw new Error(data.error ?? "preview failed");
      const meta = data.metadata ?? {};
      const cols = Array.isArray(meta.value_columns)
        ? (meta.value_columns as string[])
        : data.rows?.[0]
          ? Object.keys(data.rows[0])
          : ["ts_local", "ts_utc"];
      const allCols = ["ts_local", ...cols.filter((c) => c !== "ts_local" && c !== "ts_utc")];
      setPreview({
        kind: "dataset",
        id: datasetId,
        title: name || datasetId,
        columns: allCols,
        rows: data.rows ?? [],
        rowCount: typeof meta.row_count === "number" ? meta.row_count : undefined,
        meta: typeof meta.time_range === "string" ? meta.time_range : undefined,
      });
    } catch (err) {
      setPreviewError(formatApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  }

  return (
    <aside className="csv-sidecart" aria-label="CSV sessions and datasets">
      <h3 className="csv-sidecart-title">Sessions & datasets</h3>
      <button type="button" className="linkish-btn csv-sidecart-refresh" onClick={() => void refresh()}>
        Refresh
      </button>
      {error ? <p className="error csv-sidecart-error">{error}</p> : null}

      <div className="csv-sidecart-section">
        <h4>Import sessions</h4>
        {!hasToken() ? (
          <p className="muted">Sign in to see agent/UT3 sessions.</p>
        ) : sessions.length === 0 ? (
          <p className="muted">No sessions yet — MCP or agent upload creates these.</p>
        ) : (
          <ul className="csv-sidecart-list">
            {sessions.map((s) => {
              const id = s.session_id ?? "";
              return (
                <li key={id} className="csv-sidecart-row">
                  <button
                    type="button"
                    className={`csv-sidecart-item${activeSessionId === id ? " csv-sidecart-item--active" : ""}`}
                    onClick={() => onOpenSession(id)}
                  >
                    <span className="csv-sidecart-item-id">{id}</span>
                    {s.status ? <span className="muted"> · {s.status}</span> : null}
                  </button>
                  <button
                    type="button"
                    className="linkish-btn csv-sidecart-preview-btn"
                    onClick={(e) => void previewSession(id, e)}
                  >
                    Preview
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="csv-sidecart-section">
        <h4>Saved datasets</h4>
        {datasets.length === 0 ? (
          <p className="muted">No Arrow datasets yet.</p>
        ) : (
          <ul className="csv-sidecart-list">
            {datasets.map((d) => {
              const id = d.id ?? d.name ?? "";
              const name = d.name ?? d.id ?? "";
              return (
                <li key={id}>
                  <button
                    type="button"
                    className="csv-sidecart-item csv-sidecart-item--dataset"
                    onClick={() => void previewDataset(id, name)}
                  >
                    <span className="csv-sidecart-item-id">{name}</span>
                    {d.row_count != null ? <span className="muted"> · {d.row_count} rows</span> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {(preview.kind !== "none" || previewLoading || previewError) && (
        <CsvDataPreview
          title={preview.kind !== "none" ? preview.title : "Preview"}
          columns={preview.kind !== "none" ? preview.columns : []}
          rows={preview.kind !== "none" ? preview.rows : []}
          rowCount={preview.kind !== "none" ? preview.rowCount : undefined}
          meta={preview.kind !== "none" ? preview.meta : undefined}
          loading={previewLoading}
          error={previewError}
          onClose={() => {
            setPreview({ kind: "none" });
            setPreviewError("");
          }}
        />
      )}
    </aside>
  );
}
