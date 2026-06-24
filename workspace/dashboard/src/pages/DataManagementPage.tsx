import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type StorageSummary = {
  ok?: boolean;
  total_row_count?: number;
  estimated_bytes?: number;
  by_subdir?: Record<string, { row_count?: number; jsonl_bytes?: number }>;
  by_source?: Record<string, { source_id?: string; row_count?: number }>;
  warnings?: string[];
};

type PurgePreview = {
  ok?: boolean;
  matched_row_count?: number;
  matched_byte_estimate?: number;
  matched_sources?: string[];
  warnings?: string[];
  irreversible?: boolean;
};

export default function DataManagementPage() {
  const [summary, setSummary] = useState<StorageSummary | null>(null);
  const [preview, setPreview] = useState<PurgePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [beforeUtc, setBeforeUtc] = useState("");
  const [subdir, setSubdir] = useState("validation");
  const [confirm, setConfirm] = useState("");
  const [jobResult, setJobResult] = useState<string>("");

  const loadSummary = useCallback(async () => {
    setError(null);
    try {
      const data = await apiFetch<StorageSummary>("/api/data-management/summary");
      setSummary(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load storage summary");
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  async function runPreview(all = false) {
    setError(null);
    setPreview(null);
    try {
      const body: Record<string, unknown> = { dry_run: true };
      if (all) body.all = true;
      if (sourceId.trim()) body.source_id = sourceId.trim();
      if (beforeUtc.trim()) body.before_utc = beforeUtc.trim();
      if (subdir.trim()) body.historian_subdir = subdir.trim();
      const data = await apiFetch<PurgePreview>("/api/data-management/purge/preview", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setPreview(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preview failed");
    }
  }

  async function executePurge(all = false) {
    setError(null);
    setJobResult("");
    try {
      const body: Record<string, unknown> = {
        dry_run: false,
        confirmation: confirm,
      };
      if (all) body.all = true;
      if (sourceId.trim()) body.source_id = sourceId.trim();
      if (beforeUtc.trim()) body.before_utc = beforeUtc.trim();
      if (subdir.trim()) body.historian_subdir = subdir.trim();
      const data = await apiFetch<{ ok?: boolean; job_id?: string; rows_removed?: number; error?: string }>(
        "/api/data-management/purge/execute",
        { method: "POST", body: JSON.stringify(body) },
      );
      if (!data.ok) {
        setError(data.error || "Purge failed");
        return;
      }
      setJobResult(`Purge job ${data.job_id}: removed ${data.rows_removed ?? 0} rows`);
      setConfirm("");
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Execute failed");
    }
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <h1>Data management</h1>
        <p>
          Inspect Arrow/Feather historian storage and purge by source, subdir, or date. Purges are
          irreversible — export CSV first via the export APIs or sidecar.
        </p>
      </header>

      {error ? <div className="alert alert-error">{error}</div> : null}
      {jobResult ? <div className="alert alert-ok">{jobResult}</div> : null}

      <section className="card">
        <h2>Storage summary</h2>
        {summary ? (
          <>
            <p>
              Total rows: <strong>{summary.total_row_count ?? 0}</strong> · Estimated bytes:{" "}
              <strong>{summary.estimated_bytes ?? 0}</strong>
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Historian subdir</th>
                    <th>Rows</th>
                    <th>JSONL bytes</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.by_subdir ?? {}).map(([key, row]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td>{row.row_count ?? 0}</td>
                      <td>{row.jsonl_bytes ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p>Loading…</p>
        )}
        <button type="button" className="btn" onClick={() => void loadSummary()}>
          Refresh
        </button>
      </section>

      <section className="card">
        <h2>Purge preview</h2>
        <div className="form-grid">
          <label>
            Source ID contains
            <input value={sourceId} onChange={(e) => setSourceId(e.target.value)} placeholder="source:csv-import" />
          </label>
          <label>
            Before UTC (RFC3339)
            <input value={beforeUtc} onChange={(e) => setBeforeUtc(e.target.value)} placeholder="2026-01-01T00:00:00Z" />
          </label>
          <label>
            Historian subdir
            <input value={subdir} onChange={(e) => setSubdir(e.target.value)} placeholder="validation" />
          </label>
        </div>
        <div className="btn-row">
          <button type="button" className="btn" onClick={() => void runPreview(false)}>
            Preview purge
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => void runPreview(true)}>
            Preview purge all
          </button>
        </div>
        {preview ? (
          <pre className="code-block">{JSON.stringify(preview, null, 2)}</pre>
        ) : null}
      </section>

      <section className="card danger-zone">
        <h2>Execute purge (integrator)</h2>
        <p>Type <code>PURGE HISTORIAN DATA</code> to confirm.</p>
        <label>
          Confirmation phrase
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </label>
        <div className="btn-row">
          <button type="button" className="btn btn-danger" onClick={() => void executePurge(false)}>
            Execute filtered purge
          </button>
          <button type="button" className="btn btn-danger" onClick={() => void executePurge(true)}>
            Purge all historian data
          </button>
        </div>
      </section>
    </div>
  );
}
