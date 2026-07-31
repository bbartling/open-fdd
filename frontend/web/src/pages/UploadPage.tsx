import { useEffect, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import { FileUpload, Button, InlineAlert } from "../components/widgets";
import { useSessionQuery } from "../session";
import {
  uploadPackage,
  packageDatasetId,
  type PackageImportResponse,
} from "../api/uploadApi";
import { ApiClientError } from "../api/client";
import { getJob, type JobMeta } from "../api/jobsApi";

export function UploadPage() {
  const { query } = useSessionQuery();
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PackageImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobMeta, setJobMeta] = useState<JobMeta | null>(null);

  useEffect(() => {
    if (!query.jobId) {
      setJobMeta(null);
      return;
    }
    let cancelled = false;
    getJob(query.jobId)
      .then((job) => {
        if (!cancelled) setJobMeta(job);
      })
      .catch(() => {
        if (!cancelled) setJobMeta(null);
      });
    return () => {
      cancelled = true;
    };
  }, [query.jobId]);

  const onUpload = async () => {
    const file = files[0];
    if (!file) {
      setError("Choose a .zip package first");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const body = await uploadPackage(file);
      setResult(body);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(`${err.code}: ${err.message}`);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  };

  const datasetId = result ? packageDatasetId(result) : undefined;

  return (
    <AppShell
      title="Upload"
      caption="Package ZIP → central Rust ingest (hostile paths rejected)."
    >
      <div className="page-placeholder">
        <h2>Upload</h2>
        <p>
          Posts to <code>POST /api/csv/import/package</code>. Selection via{" "}
          <code>?job=</code> is context-only — upload does not yet associate
          packages with jobs.
        </p>
        {query.jobId ? (
          <p data-testid="upload-job-context">
            Selected job: <code>{jobMeta?.job_name ?? query.jobId}</code>
            {jobMeta?.job_name ? ` (${query.jobId})` : null}
          </p>
        ) : (
          <p className="loading">No job selected (optional).</p>
        )}

        <FileUpload
          id="package-zip"
          label="Building package zip"
          description="openfdd_package_v1 zip; traversal/absolute/symlink members are rejected by Rust."
          accept=".zip,application/zip"
          files={files}
          onChange={setFiles}
          loading={loading}
          testId="upload-file"
        />

        <div style={{ marginTop: "1rem" }}>
          <Button
            id="upload-submit"
            label={loading ? "Uploading…" : "Import package"}
            loading={loading}
            disabled={files.length === 0}
            onClick={() => void onUpload()}
            testId="upload-submit"
          />
        </div>

        {error ? (
          <div style={{ marginTop: "1rem" }}>
            <InlineAlert
              id="upload-error"
              variant="danger"
              title="Upload error"
              testId="upload-error"
            >
              {error}
            </InlineAlert>
          </div>
        ) : null}

        {result?.ok ? (
          <div style={{ marginTop: "1rem" }}>
            <InlineAlert
              id="upload-success"
              variant="success"
              title="Upload ok"
              testId="upload-success"
            >
              Imported building {String(result.building_id ?? "unknown")}
              {datasetId ? ` · dataset ${datasetId}` : ""}
            </InlineAlert>
            {datasetId ? (
              <p>
                <Link to={`/mapping?site=${encodeURIComponent(datasetId)}`}>
                  Continue to mapping
                </Link>
              </p>
            ) : null}
            <pre className="page-json" data-testid="upload-result-json">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
