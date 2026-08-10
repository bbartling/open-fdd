import { useEffect, useRef, useState } from "react";
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
  const { query, setQuery } = useSessionQuery();
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [result, setResult] = useState<PackageImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobMeta, setJobMeta] = useState<JobMeta | null>(null);
  const startedAt = useRef<number | null>(null);

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

  useEffect(() => {
    if (!loading) {
      startedAt.current = null;
      return;
    }
    startedAt.current = Date.now();
    setElapsedSec(0);
    const id = window.setInterval(() => {
      if (startedAt.current != null) {
        setElapsedSec(
          Math.max(0, Math.round((Date.now() - startedAt.current) / 1000)),
        );
      }
    }, 250);
    return () => window.clearInterval(id);
  }, [loading]);

  const onUpload = async () => {
    const file = files[0];
    if (!file) {
      setError("Choose a .zip package first");
      return;
    }
    if (files.length > 1) {
      setError("Upload one openfdd_package_v1 zip at a time.");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const body = await uploadPackage(file);
      setResult(body);
      const bid = body.building_id || "";
      if (bid) {
        setQuery({ siteId: bid }, true);
        try {
          window.dispatchEvent(
            new CustomEvent("openfdd:package-loaded", {
              detail: { buildingId: bid },
            }),
          );
        } catch {
          /* ignore */
        }
      }
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
      activeSectionId="upload"
    >
      <div className="page-stack" data-testid="upload-page">
        <h2>Upload package</h2>
        <p>
          Prefer the sidebar <strong>Load package</strong> control on Overview —
          same ingest path and active-site handoff.
        </p>
        {query.jobId ? (
          <p data-testid="upload-job-context">
            Selected job: <code>{jobMeta?.job_name ?? query.jobId}</code>
            {jobMeta?.job_name ? ` (${query.jobId})` : null}
          </p>
        ) : (
          <p className="oracle-sidebar__caption">
            No job selected (optional context only — upload does not attach the
            package to a job yet).
          </p>
        )}

        <FileUpload
          id="package-zip"
          label="Building package zip"
          description="One openfdd_package_v1 zip. Traversal/absolute/symlink members are rejected by Rust."
          accept=".zip,application/zip"
          files={files.slice(0, 1)}
          onChange={(next) => setFiles(next.slice(0, 1))}
          loading={loading}
          testId="upload-file"
        />

        <div style={{ marginTop: "1rem" }}>
          <Button
            id="upload-submit"
            label={loading ? `Importing… ${elapsedSec}s` : "Import package"}
            loading={loading}
            disabled={files.length === 0}
            onClick={() => void onUpload()}
            testId="upload-submit"
          />
        </div>

        {loading ? (
          <p
            className="oracle-sidebar__busy"
            data-testid="upload-busy"
            role="status"
          >
            Importing into central historian… <strong>{elapsedSec}s</strong>{" "}
            elapsed.
          </p>
        ) : null}

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
              title="Package imported"
              testId="upload-success"
            >
              Building <code>{String(result.building_id ?? "unknown")}</code>
              {result.equipment_written != null
                ? ` · ${result.equipment_written} equipment`
                : ""}
              {result.total_rows != null
                ? ` · ${result.total_rows.toLocaleString()} rows`
                : ""}
              {result.total_ms != null ? ` · ${result.total_ms} ms` : ""}
              {datasetId ? ` · dataset ${datasetId}` : ""}
            </InlineAlert>
            <p className="overview-rule-run__row">
              {datasetId ? (
                <Link
                  to={`/?site=${encodeURIComponent(datasetId)}`}
                  data-testid="upload-goto-overview"
                >
                  Open Overview charts
                </Link>
              ) : null}
              {datasetId ? (
                <Link to={`/mapping?site=${encodeURIComponent(datasetId)}`}>
                  Continue to mapping
                </Link>
              ) : null}
            </p>
            <pre className="page-json" data-testid="upload-result-json">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
