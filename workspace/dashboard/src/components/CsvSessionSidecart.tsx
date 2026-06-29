import { useCallback, useEffect, useState } from "react";
import { apiFetch, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type SessionRow = { session_id?: string; created_at?: string; status?: string };
type DatasetRow = { id?: string; name?: string; row_count?: number };

type Props = {
  activeSessionId?: string;
  onOpenSession: (sessionId: string) => void;
};

export default function CsvSessionSidecart({ activeSessionId, onOpenSession }: Props) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [datasets, setDatasets] = useState<DatasetRow[]>([]);
  const [error, setError] = useState("");

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
                <li key={id}>
                  <button
                    type="button"
                    className={`csv-sidecart-item${activeSessionId === id ? " csv-sidecart-item--active" : ""}`}
                    onClick={() => onOpenSession(id)}
                  >
                    <span className="csv-sidecart-item-id">{id}</span>
                    {s.status ? <span className="muted"> · {s.status}</span> : null}
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
            {datasets.map((d) => (
              <li key={d.id ?? d.name}>
                <span className="csv-sidecart-item-id">{d.name ?? d.id}</span>
                {d.row_count != null ? <span className="muted"> · {d.row_count} rows</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
