import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { apiDownloadBlob, apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type ReportSection = {
  id: string;
  type: string;
  title: string;
  visible?: boolean;
  order?: number;
  content?: Record<string, unknown>;
};

type ReportDoc = {
  ok?: boolean;
  report_id?: string;
  title?: string;
  template_id?: string;
  sections?: ReportSection[];
  metadata?: Record<string, unknown>;
};

function ReportSectionCard({
  section,
  onMoveUp,
  onMoveDown,
  onToggle,
  onTitle,
}: {
  section: ReportSection;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onToggle: () => void;
  onTitle: (title: string) => void;
}) {
  return (
    <div className={`report-section-card${section.visible === false ? " muted" : ""}`}>
      <div className="report-section-toolbar">
        <span className="report-section-type">{section.type}</span>
        <button type="button" className="secondary-btn" onClick={onMoveUp} aria-label="Move up">
          ↑
        </button>
        <button type="button" className="secondary-btn" onClick={onMoveDown} aria-label="Move down">
          ↓
        </button>
        <label className="report-section-visible">
          <input type="checkbox" checked={section.visible !== false} onChange={onToggle} />
          Show
        </label>
      </div>
      <input
        className="report-section-title"
        value={section.title}
        onChange={(e) => onTitle(e.target.value)}
      />
      {section.type === "rule_explanation" && section.content ? (
        <div className="report-rule-block">
          <p>{String(section.content.explanation ?? "")}</p>
          <pre>{String(section.content.sql ?? "")}</pre>
        </div>
      ) : null}
    </div>
  );
}

export default function ReportBuilderPage() {
  const [report, setReport] = useState<ReportDoc | null>(null);
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    try {
      const res = await apiFetch<{ records?: Array<Record<string, unknown>> }>("/api/reports");
      setReports(res.records ?? []);
    } catch (e) {
      setError(formatApiError(e));
    }
  }, []);

  const sections = useMemo(
    () => [...(report?.sections ?? [])].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
    [report?.sections],
  );

  const createDraft = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const draft = await apiFetch<ReportDoc>("/api/reports/draft", {
        method: "POST",
        body: JSON.stringify({
          template_id: "validation-summary",
          title: "Open-FDD Validation Report",
        }),
      });
      setReport(draft);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void createDraft();
    void loadReports();
  }, [createDraft, loadReports]);

  async function deleteReport(reportId: string) {
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/api/reports/${reportId}`, { method: "DELETE" });
      await loadReports();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function downloadListedReport(reportId: string) {
    setBusy(true);
    setError("");
    try {
      const { blob, filename } = await apiDownloadBlob(`/api/reports/${reportId}/download.pdf`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || `${reportId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function persistSections(next: ReportSection[]) {
    if (!report?.report_id) return;
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch<{ ok?: boolean; report?: ReportDoc }>(
        `/api/reports/${report.report_id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ sections: next }),
        },
      );
      setReport(res.report ?? report);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  function updateSection(idx: number, patch: Partial<ReportSection>) {
    const next = sections.map((s, i) => (i === idx ? { ...s, ...patch } : s));
    void persistSections(next);
  }

  function moveSection(idx: number, dir: -1 | 1) {
    const j = idx + dir;
    if (j < 0 || j >= sections.length) return;
    const next = [...sections];
    [next[idx], next[j]] = [next[j], next[idx]];
    next.forEach((s, i) => {
      s.order = i;
    });
    void persistSections(next);
  }

  async function renderPreview() {
    if (!report?.report_id) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/api/reports/${report.report_id}/render/pdf`, { method: "POST" });
      const { blob } = await apiDownloadBlob(`/api/reports/${report.report_id}/download.pdf`);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    if (!report?.report_id) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/api/reports/${report.report_id}/render/pdf`, { method: "POST" });
      const { blob, filename } = await apiDownloadBlob(`/api/reports/${report.report_id}/download.pdf`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || `${report.report_id}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="report-builder-page">
      <PageHeader
        title="Report Builder"
        subtitle="Model-driven auto-report from Haystack model, historian, FDD rules, and faults. Reorder sections, edit titles, preview and download PDF."
      />

      {error ? <div className="error-banner">{error}</div> : null}

      <section className="panel">
        <h2>Validation reports</h2>
        {reports.length === 0 ? (
          <p className="hint">No reports yet. Run a validation workflow from Reports or complete a site validation harness to generate a PDF.</p>
        ) : (
          <ul className="report-list">
            {reports.map((r) => {
              const id = String(r.report_id ?? "");
              return (
                <li key={id} className="report-list-row">
                  <span className={`badge ${r.status === "pass" ? "ok" : r.status === "fail" ? "bad" : ""}`}>
                    {String(r.status ?? "draft")}
                  </span>
                  <strong>{String(r.title ?? id)}</strong>
                  <span className="muted">{String(r.created_at ?? "—")}</span>
                  <span className="muted">{Number(r.size_bytes ?? 0) > 0 ? `${r.size_bytes} B` : "no PDF"}</span>
                  <button type="button" className="secondary-btn" disabled={busy} onClick={() => void downloadListedReport(id)}>
                    Download PDF
                  </button>
                  <button type="button" className="secondary-btn" disabled={busy} onClick={() => void deleteReport(id)}>
                    Delete
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div className="toolbar">
        <button type="button" className="secondary-btn" onClick={() => void createDraft()} disabled={busy}>
          Regenerate draft
        </button>
        <button type="button" className="secondary-btn" onClick={() => void renderPreview()} disabled={busy || !report?.report_id}>
          Preview PDF
        </button>
        <button type="button" className="primary-btn" onClick={() => void downloadPdf()} disabled={busy || !report?.report_id}>
          Download PDF
        </button>
      </div>

      <div className="report-builder-grid">
        <section className="report-canvas">
          <h2>Suggested sections</h2>
          <p className="hint">Auto-selected from model coverage, rules, faults, and historian. Hide or reorder as needed.</p>
          {sections.map((sec, idx) => (
            <ReportSectionCard
              key={sec.id}
              section={sec}
              onMoveUp={() => moveSection(idx, -1)}
              onMoveDown={() => moveSection(idx, 1)}
              onToggle={() => updateSection(idx, { visible: sec.visible === false })}
              onTitle={(title) => updateSection(idx, { title })}
            />
          ))}
        </section>

        <section className="report-preview-frame">
          <h2>Preview</h2>
          {previewUrl ? (
            <iframe title="Report preview" src={previewUrl} className="report-preview-iframe" />
          ) : (
            <p className="hint">Click Preview PDF to render the report bundle.</p>
          )}
        </section>
      </div>

      {report?.report_id ? (
        <p className="hint">
          Report ID: <code>{report.report_id}</code> · {sections.filter((s) => s.visible !== false).length} visible sections
        </p>
      ) : null}
    </div>
  );
}
