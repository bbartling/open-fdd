import { useCallback, useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
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

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

export default function DataManagementPage() {
  const [summary, setSummary] = useState<StorageSummary | null>(null);
  const [preview, setPreview] = useState<PurgePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [beforeUtc, setBeforeUtc] = useState("");
  const [subdir, setSubdir] = useState("validation");
  const [confirm, setConfirm] = useState("");
  const [jobResult, setJobResult] = useState("");

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
      setJobResult(`Removed ${data.rows_removed ?? 0} rows (job ${data.job_id ?? "—"})`);
      setConfirm("");
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Execute failed");
    }
  }

  const sources = Object.entries(summary?.by_source ?? {});

  return (
    <div className="page-stack data-mgmt-page">
      <PageHeader
        title="Historian storage"
        subtitle="Inspect Arrow/Feather partitions and purge by source or date. Export CSV before destructive purges."
      />

      {error ? <div className="alert alert-error">{error}</div> : null}
      {jobResult ? <div className="alert alert-ok">{jobResult}</div> : null}

      <section className="panel">
        <div className="panel-head-row">
          <h2 className="panel-title">Storage summary</h2>
          <button type="button" className="secondary-btn" onClick={() => void loadSummary()}>
            Refresh
          </button>
        </div>
        {summary ? (
          <>
            <p className="storage-summary-line">
              <strong>{summary.total_row_count?.toLocaleString() ?? 0}</strong> historian rows ·{" "}
              <strong>{formatBytes(summary.estimated_bytes ?? 0)}</strong> estimated
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Partition</th>
                    <th>Rows</th>
                    <th>Size</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(summary.by_subdir ?? {}).map(([key, row]) => (
                    <tr key={key}>
                      <td><code>{key}</code></td>
                      <td>{row.row_count?.toLocaleString() ?? 0}</td>
                      <td>{formatBytes(row.jsonl_bytes ?? 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {sources.length ? (
              <>
                <h3 className="panel-subtitle">By source</h3>
                <ul className="source-chip-list">
                  {sources.map(([key, row]) => (
                    <li key={key}>
                      <code>{row.source_id ?? key}</code>
                      <span className="muted">{row.row_count?.toLocaleString() ?? 0} rows</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ) : (
          <p className="muted">Loading…</p>
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">Purge preview</h2>
        <p className="muted">Dry-run first — previews matched row counts without deleting data.</p>
        <div className="form-grid form-grid-3">
          <label className="field">
            <span className="field-label">Source ID contains</span>
            <input value={sourceId} onChange={(e) => setSourceId(e.target.value)} placeholder="source:csv-import" />
          </label>
          <label className="field">
            <span className="field-label">Before UTC</span>
            <input value={beforeUtc} onChange={(e) => setBeforeUtc(e.target.value)} placeholder="2026-01-01T00:00:00Z" />
          </label>
          <label className="field">
            <span className="field-label">Historian partition</span>
            <input value={subdir} onChange={(e) => setSubdir(e.target.value)} placeholder="validation" />
          </label>
        </div>
        <div className="action-bar action-bar-spaced">
          <button type="button" className="primary-btn" onClick={() => void runPreview(false)}>
            Preview matched rows
          </button>
          <button type="button" className="secondary-btn" onClick={() => void runPreview(true)}>
            Preview purge all
          </button>
        </div>
        {preview ? (
          <div className="purge-preview-card">
            <p>
              <strong>{preview.matched_row_count?.toLocaleString() ?? 0}</strong> rows matched · ~
              {formatBytes(preview.matched_byte_estimate ?? 0)}
            </p>
            {preview.matched_sources?.length ? (
              <p className="muted">Sources: {preview.matched_sources.slice(0, 8).join(", ")}</p>
            ) : null}
            {preview.warnings?.length ? (
              <ul className="warn-list">
                {preview.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="panel danger-zone">
        <h2 className="panel-title">Execute purge</h2>
        <p className="muted">Integrator role required. Type the confirmation phrase exactly.</p>
        <label className="field">
          <span className="field-label">Confirmation phrase</span>
          <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="PURGE HISTORIAN DATA" />
        </label>
        <div className="action-bar action-bar-spaced">
          <button type="button" className="btn-danger" onClick={() => void executePurge(false)}>
            Execute filtered purge
          </button>
          <button type="button" className="btn-danger" onClick={() => void executePurge(true)}>
            Purge all historian data
          </button>
        </div>
      </section>
    </div>
  );
}
