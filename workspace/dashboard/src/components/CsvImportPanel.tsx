import { useCallback, useState } from "react";
import { apiFetch, apiUploadRaw } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type JobStatus = {
  ok?: boolean;
  job_id?: string;
  status?: string;
  rows_committed?: number;
  bytes?: number;
  preview?: {
    columns?: string[];
    line_count_estimate?: number;
    sample_rows?: string[][];
  };
  error?: string;
};

type Props = {
  onStatus?: (msg: string) => void;
};

export default function CsvImportPanel({ onStatus }: Props) {
  const [profileId, setProfileId] = useState("default_csv_import");
  const [sourceId, setSourceId] = useState("source:csv-import");
  const [equipmentId, setEquipmentId] = useState("equip:validation");
  const [jobId, setJobId] = useState("");
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState("");
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState("");

  const refreshStatus = useCallback(async (id: string) => {
    const status = await apiFetch<JobStatus>(`/api/import/jobs/${encodeURIComponent(id)}/status`);
    setJob(status);
    return status;
  }, []);

  async function createJob() {
    setError("");
    setBusy("create");
    try {
      const created = await apiFetch<JobStatus>("/api/import/jobs", {
        method: "POST",
        body: JSON.stringify({
          profile_id: profileId,
          source_id: sourceId,
          equipment_id: equipmentId,
        }),
      });
      if (!created.job_id) throw new Error("Job create failed");
      setJobId(created.job_id);
      setJob(created);
      onStatus?.(`Import job ${created.job_id} created`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function uploadFile(file: File) {
    if (!jobId) {
      setError("Create a job first.");
      return;
    }
    setError("");
    setBusy("upload");
    try {
      const text = await file.text();
      const uploaded = await apiUploadRaw<JobStatus>(
        `/api/import/jobs/${encodeURIComponent(jobId)}/upload`,
        text,
        "text/csv",
      );
      setFileName(file.name);
      setJob(uploaded);
      onStatus?.(`Uploaded ${file.name} (${uploaded.bytes ?? text.length} bytes)`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function previewJob() {
    if (!jobId) return;
    setError("");
    setBusy("preview");
    try {
      const preview = await apiFetch<JobStatus>(`/api/import/jobs/${encodeURIComponent(jobId)}/preview`);
      setJob(preview);
      const cols = preview.preview?.columns?.length ?? 0;
      const lines = preview.preview?.line_count_estimate ?? 0;
      onStatus?.(`Preview OK — ${cols} column(s), ~${lines} row(s)`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  async function commitJob() {
    if (!jobId) return;
    setError("");
    setBusy("commit");
    try {
      const committed = await apiFetch<JobStatus>(`/api/import/jobs/${encodeURIComponent(jobId)}/commit`, {
        method: "POST",
        body: "{}",
      });
      setJob(committed);
      await refreshStatus(jobId);
      onStatus?.(`Committed ${committed.rows_committed ?? 0} row(s) to historian`);
      window.dispatchEvent(new CustomEvent("ofdd-dashboard-refresh"));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="card">
      <h2>CSV import</h2>
      <p className="muted">
        Upload large CSV files for historian ingest and FDD/report runs. For recurring sidecar ingest,
        use <code>scripts/openfdd_csv_import_sidecar.sh</code> on a cron interval pointing at the same
        import API.
      </p>
      {error ? <p className="error">{error}</p> : null}
      <div className="form-grid">
        <label className="field">
          <span className="field-label">Profile</span>
          <input value={profileId} onChange={(e) => setProfileId(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Source ID</span>
          <input value={sourceId} onChange={(e) => setSourceId(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Equipment ID</span>
          <input value={equipmentId} onChange={(e) => setEquipmentId(e.target.value)} />
        </label>
      </div>
      <div className="toolbar">
        <button type="button" className="primary-btn" disabled={!!busy} onClick={() => void createJob()}>
          {busy === "create" ? "Creating…" : "1. Create job"}
        </button>
        <label className="secondary-btn" style={{ cursor: "pointer" }}>
          {busy === "upload" ? "Uploading…" : "2. Upload CSV"}
          <input
            type="file"
            accept=".csv,text/csv"
            hidden
            disabled={!jobId || !!busy}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void uploadFile(f);
              e.target.value = "";
            }}
          />
        </label>
        <button
          type="button"
          className="secondary-btn"
          disabled={!jobId || !!busy}
          onClick={() => void previewJob()}
        >
          {busy === "preview" ? "Previewing…" : "3. Preview"}
        </button>
        <button
          type="button"
          className="secondary-btn"
          disabled={!jobId || !!busy}
          onClick={() => void commitJob()}
        >
          {busy === "commit" ? "Committing…" : "4. Commit to historian"}
        </button>
      </div>
      {jobId ? (
        <p className="muted">
          Job <code>{jobId}</code>
          {fileName ? <> · file {fileName}</> : null}
          {job?.status ? <> · status {job.status}</> : null}
          {job?.rows_committed != null ? <> · rows {job.rows_committed}</> : null}
        </p>
      ) : null}
      {job?.preview?.columns?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {job.preview.columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(job.preview.sample_rows ?? []).map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
