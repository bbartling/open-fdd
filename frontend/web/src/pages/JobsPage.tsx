import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { ApiClientError, apiFetch } from "../api/client";

export function JobsPage() {
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiFetch<unknown>("/api/jobs")
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          if (err instanceof ApiClientError) {
            setError(`${err.code}: ${err.message} (request_id=${err.requestId})`);
          } else {
            setError(err instanceof Error ? err.message : String(err));
          }
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell title="Jobs">
      <div className="page-placeholder">
        <h2>Jobs</h2>
        <p>Job list — calls GET /api/jobs when central is available.</p>
        {loading && <p className="loading">Loading jobs…</p>}
        {error && (
          <div className="page-error" data-testid="jobs-error">
            {error}
          </div>
        )}
        {data !== null && (
          <pre className="page-json" data-testid="jobs-json">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </AppShell>
  );
}
