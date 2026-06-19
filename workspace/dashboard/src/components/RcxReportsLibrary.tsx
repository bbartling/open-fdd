import { useCallback, useEffect, useRef, useState } from "react";
import { renderAsync } from "docx-preview";
import {
  deleteRcxReport,
  fetchRcxReportBlob,
  fetchRcxReportList,
  type RcxSavedReport,
} from "../lib/analytics-api";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

type Props = {
  refreshToken?: number;
};

export default function RcxReportsLibrary({ refreshToken = 0 }: Props) {
  const [reports, setReports] = useState<RcxSavedReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchRcxReportList(80);
      setReports(data.reports ?? []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  useEffect(() => {
    if (!previewFile || !previewRef.current) return;
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewError("");
    previewRef.current.innerHTML = "";
    void fetchRcxReportBlob(previewFile)
      .then(async (blob) => {
        if (cancelled || !previewRef.current) return;
        await renderAsync(blob, previewRef.current, undefined, {
          className: "docx-preview-page",
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          breakPages: true,
        });
      })
      .catch((e) => {
        if (!cancelled) setPreviewError(String(e));
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [previewFile]);

  async function onDelete(filename: string) {
    if (!window.confirm(`Delete ${filename}?`)) return;
    try {
      await deleteRcxReport(filename);
      if (previewFile === filename) setPreviewFile(null);
      await load();
    } catch (e) {
      setError(String(e));
    }
  }

  function onDownload(filename: string) {
    void fetchRcxReportBlob(filename)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setError(String(e)));
  }

  return (
    <section className="panel rcx-library-panel">
      <div className="rcx-library-header">
        <div>
          <h2>Saved RCx reports</h2>
          <p className="muted rcx-library-sub">
            Word documents from this UI or AI agents — stored in <code>workspace/reports/rcx</code>.
          </p>
        </div>
        <button type="button" className="btn" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
      {loading && !reports.length ? <p className="muted">Loading reports…</p> : null}
      {!loading && !reports.length ? (
        <p className="muted">No saved reports yet. Generate a DOCX above or via an agent — it will appear here.</p>
      ) : null}

      <ul className="rcx-report-grid">
        {reports.map((r) => (
          <li key={r.filename} className="rcx-report-card">
            <div className="rcx-report-icon" aria-hidden>
              DOCX
            </div>
            <div className="rcx-report-meta">
              <div className="rcx-report-name" title={r.filename}>
                {r.filename}
              </div>
              <div className="muted rcx-report-detail">
                {formatBytes(r.size_bytes)} · {formatWhen(r.saved_at)}
              </div>
            </div>
            <div className="rcx-report-actions">
              <button type="button" className="btn small" onClick={() => setPreviewFile(r.filename)}>
                Preview
              </button>
              <button type="button" className="btn small" onClick={() => onDownload(r.filename)}>
                Download
              </button>
              <button type="button" className="btn small danger" onClick={() => void onDelete(r.filename)}>
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {previewFile ? (
        <div className="rcx-preview-overlay" role="dialog" aria-modal="true" aria-label="RCx report preview">
          <div className="rcx-preview-modal panel">
            <div className="rcx-preview-toolbar">
              <strong>{previewFile}</strong>
              <div className="toolbar-row">
                <button type="button" className="btn small" onClick={() => onDownload(previewFile)}>
                  Download to edit
                </button>
                <button type="button" className="btn small" onClick={() => setPreviewFile(null)}>
                  Close
                </button>
              </div>
            </div>
            <p className="muted rcx-preview-hint">
              Browser preview is read-only. Download and open in Word (or LibreOffice) to edit, then re-upload via
              Generate DOCX.
            </p>
            {previewLoading ? <p className="muted">Rendering document…</p> : null}
            {previewError ? <p className="error-text">{previewError}</p> : null}
            <div className="rcx-preview-body docx" ref={previewRef} />
          </div>
        </div>
      ) : null}
    </section>
  );
}
