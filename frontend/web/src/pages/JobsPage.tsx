import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { ApiClientError, apiFetch } from "../api/client";
import { useSessionQuery } from "../session";
import { Select } from "../components/widgets";

interface JobRow {
  job_id?: string;
  job_name?: string;
}

interface JobsListBody {
  jobs?: JobRow[];
}

export function JobsPage() {
  const { query, setQuery } = useSessionQuery();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [raw, setRaw] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiFetch<JobsListBody>("/api/jobs")
      .then((body) => {
        if (cancelled) return;
        setRaw(body);
        setJobs(Array.isArray(body.jobs) ? body.jobs : []);
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

  const options = [
    { value: "", label: "— select job —" },
    ...jobs.map((j) => ({
      value: j.job_id ?? "",
      label: j.job_name ? `${j.job_name} (${j.job_id})` : (j.job_id ?? ""),
    })),
  ];

  return (
    <AppShell
      title="Jobs"
      caption="Selection is URL-backed (?job=) for refresh/back/deep-link."
    >
      <div className="page-placeholder">
        <h2>Jobs</h2>
        <p>Job list — calls GET /api/jobs when central is available.</p>
        <Select
          id="jobs-session-select"
          label="Selected job"
          description="Maps Streamlit openfdd_job_id → URL ?job="
          value={query.jobId ?? ""}
          options={options}
          onChange={(value) => setQuery({ jobId: value }, true)}
          testId="jobs-session-select"
        />
        {query.jobId ? (
          <p data-testid="jobs-selected-id">
            Deep-link job: <code>{query.jobId}</code>
          </p>
        ) : null}
        {loading && <p className="loading">Loading jobs…</p>}
        {error && (
          <div className="page-error" data-testid="jobs-error">
            {error}
          </div>
        )}
        {raw !== null && (
          <pre className="page-json" data-testid="jobs-json">
            {JSON.stringify(raw, null, 2)}
          </pre>
        )}
      </div>
    </AppShell>
  );
}
