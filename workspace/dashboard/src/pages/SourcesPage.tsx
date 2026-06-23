import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import ActionButton from "../components/ActionButton";
import Spinner from "../components/Spinner";
import { apiDownloadBlob, apiFetch, fetchAuthMe } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  canMutateSources,
  healthTone,
  type BackfillJob,
  type SourceRecord,
  SOURCES_PANEL_TITLE,
  formatSourceType,
} from "../lib/sources";

type SourceDetail = {
  source: SourceRecord;
  config: Record<string, unknown>;
};

export default function SourcesPage() {
  const { sourceId } = useParams();
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [catalog, setCatalog] = useState<Array<Record<string, unknown>>>([]);
  const [sample, setSample] = useState<unknown>(null);
  const [jobs, setJobs] = useState<BackfillJob[]>([]);
  const [role, setRole] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const canMutate = canMutateSources(role);

  const refreshList = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [list, me] = await Promise.all([
        apiFetch<{ sources: SourceRecord[] }>("/api/sources"),
        fetchAuthMe().catch(() => null),
      ]);
      setSources(list.sources ?? []);
      setRole(me?.role ?? null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshDetail = useCallback(async (id: string) => {
    setBusy(true);
    setError("");
    try {
      const resp = await apiFetch<SourceDetail>(`/api/sources/${id}`);
      setDetail(resp);
      const cat = await apiFetch<{ points?: Array<Record<string, unknown>> }>(`/api/sources/${id}/catalog`);
      setCatalog(cat.points ?? []);
      const health = await apiFetch<{ health?: Record<string, unknown> }>(`/api/sources/${id}/health`);
      setStatus(String(health.health?.message ?? ""));
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    if (sourceId) {
      void refreshDetail(sourceId);
    } else {
      setDetail(null);
      setCatalog([]);
      setSample(null);
      setJobs([]);
    }
  }, [sourceId, refreshDetail]);

  const selected = useMemo(
    () => sources.find((s) => s.source_id === sourceId) ?? detail?.source ?? null,
    [sources, sourceId, detail],
  );

  async function runAction(label: string, fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      setStatus(`${label} succeeded`);
      if (sourceId) await refreshDetail(sourceId);
      await refreshList();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page sources-page">
      <PageHeader
        title={SOURCES_PANEL_TITLE}
        subtitle="Configure external JSON APIs, read-only Postgres lakes, and simulation sources. Private credentials stay in gitignored workspace files."
      />

      {error ? <p className="error-banner">{error}</p> : null}
      {status ? <p className="muted panel-help">{status}</p> : null}

      <div className="sources-layout">
        <section className="panel sources-list-panel" aria-label="Configured sources">
          <h3 className="panel-title">Configured sources</h3>
          {loading ? <Spinner label="Loading sources…" /> : null}
          <ul className="sources-list">
            {sources.map((source) => {
              const tone = healthTone(source.health?.status);
              return (
                <li key={source.source_id} className={source.source_id === sourceId ? "active" : ""}>
                  <Link to={`/sources/${source.source_id}`} className="sources-list-link">
                    <strong>{source.display_name}</strong>
                    <span className="muted">{formatSourceType(source.source_type)}</span>
                    <span className={`health-chip health-${tone}`}>{source.health?.status ?? "unknown"}</span>
                    <span className="muted">Rows: {source.row_count ?? 0}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="panel sources-detail-panel" aria-label="Source detail">
          {!selected ? (
            <p className="muted">Select a source to inspect configuration, mappings, samples, and backfill jobs.</p>
          ) : (
            <>
              <h3 className="panel-title">{selected.display_name}</h3>
              <p className="muted panel-help">
                Source ID: {selected.source_id} · Type: {formatSourceType(selected.source_type)} · Site:{" "}
                {selected.site_id ?? "—"}
              </p>

              <div className="panel-actions">
                <ActionButton
                  label="Test connection"
                  disabled={busy}
                  onClick={() =>
                    void runAction("Test connection", async () => {
                      await apiFetch(`/api/sources/${selected.source_id}/test`, { method: "POST", body: "{}" });
                    })
                  }
                />
                <ActionButton
                  label="Discover catalog"
                  disabled={busy}
                  onClick={() =>
                    void runAction("Discover", async () => {
                      await apiFetch(`/api/sources/${selected.source_id}/discover`, { method: "POST", body: "{}" });
                    })
                  }
                />
                <ActionButton
                  label="Poll once → historian"
                  disabled={busy || !canMutate}
                  title={canMutate ? undefined : "Integrator or agent role required"}
                  onClick={() =>
                    void runAction("Poll once", async () => {
                      await apiFetch(`/api/sources/${selected.source_id}/poll-once`, { method: "POST", body: "{}" });
                    })
                  }
                />
                <ActionButton
                  label="Run backfill (24h demo)"
                  disabled={busy || !canMutate}
                  onClick={() =>
                    void runAction("Backfill", async () => {
                      const end = new Date();
                      const start = new Date(end.getTime() - 24 * 3600 * 1000);
                      const job = await apiFetch<BackfillJob>(`/api/sources/${selected.source_id}/backfill`, {
                        method: "POST",
                        body: JSON.stringify({
                          start_ts: start.toISOString(),
                          end_ts: end.toISOString(),
                          chunk_hours: 6,
                        }),
                      });
                      setJobs((prev) => [job, ...prev]);
                    })
                  }
                />
                <ActionButton
                  label="Export historian CSV"
                  disabled={busy}
                  onClick={() =>
                    void runAction("Export CSV", async () => {
                      const { blob, filename } = await apiDownloadBlob("/api/export/historian.csv");
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = filename;
                      a.click();
                      URL.revokeObjectURL(url);
                    })
                  }
                />
              </div>

              {detail?.config ? (
                <div className="source-config-summary">
                  <h4>Configuration (secrets redacted)</h4>
                  <pre className="code-block">{JSON.stringify(detail.config, null, 2)}</pre>
                </div>
              ) : null}

              <div className="source-catalog">
                <h4>Discovered points ({catalog.length})</h4>
                <ul className="source-point-list">
                  {catalog.map((p) => (
                    <li key={String(p.point_id)}>
                      <strong>{String(p.point_name ?? p.point_id)}</strong>
                      <span className="muted">{String(p.point_id)}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="source-mapping">
                <h4>Mapping workflow</h4>
                <p className="muted panel-help">
                  AI-suggested mappings require human review before applied status. Use pending → accepted → applied.
                </p>
                <ActionButton
                  label="Save demo mapping (pending review)"
                  disabled={busy || !canMutate || catalog.length === 0}
                  onClick={() =>
                    void runAction("Save mapping", async () => {
                      const point = catalog[0];
                      await apiFetch(`/api/sources/${selected.source_id}/mappings`, {
                        method: "POST",
                        body: JSON.stringify({
                          source_id: selected.source_id,
                          source_point_id: point.point_id,
                          model_point_id: "point:outside_air_temp",
                          review_status: "pending",
                          ai_suggested: true,
                        }),
                      });
                    })
                  }
                />
              </div>

              <div className="source-sample">
                <h4>Sample data</h4>
                <ActionButton
                  label="Load sample preview"
                  disabled={busy}
                  onClick={() =>
                    void runAction("Sample", async () => {
                      const resp = await apiFetch<{ sample?: unknown }>(`/api/sources/${selected.source_id}/sample`);
                      setSample(resp.sample ?? resp);
                    })
                  }
                />
                {sample ? <pre className="code-block">{JSON.stringify(sample, null, 2)}</pre> : null}
              </div>

              {jobs.length > 0 ? (
                <div className="source-backfill-jobs">
                  <h4>Backfill jobs</h4>
                  <ul>
                    {jobs.map((job) => (
                      <li key={job.job_id}>
                        {job.job_id} — {job.status} — rows written {job.rows_written ?? 0}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
