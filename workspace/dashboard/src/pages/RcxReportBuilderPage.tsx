import { useState, type Dispatch, type SetStateAction } from "react";
import PageHeader from "../components/PageHeader";
import {
  downloadRcxReport,
  fetchRcxPreview,
  type RcxPreviewResponse,
} from "../lib/analytics-api";

const WINDOW_OPTS = [
  { label: "2 hours", hours: 2 },
  { label: "24 hours", hours: 24 },
  { label: "7 days", hours: 168 },
];

export default function RcxReportBuilderPage() {
  const [hours, setHours] = useState(24);
  const [preview, setPreview] = useState<RcxPreviewResponse | null>(null);
  const [selectedCharts, setSelectedCharts] = useState<Set<string>>(new Set());
  const [selectedSections, setSelectedSections] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  async function collectPreview() {
    setLoading(true);
    setError("");
    setStatus("");
    try {
      const p = await fetchRcxPreview({ hours, scope: "building" });
      setPreview(p);
      setSelectedCharts(new Set(p.available_charts.map((c) => c.id)));
      setSelectedSections(new Set(p.sections.map((s) => s.id)));
      setStatus("Preview ready — review chart readiness below.");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function toggle(setter: Dispatch<SetStateAction<Set<string>>>, id: string) {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function generateDocx() {
    setLoading(true);
    setError("");
    try {
      const blob = await downloadRcxReport({
        hours,
        scope: "building",
        charts: [...selectedCharts],
        sections: [...selectedSections],
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "openfdd-rcx-report.docx";
      a.click();
      URL.revokeObjectURL(url);
      setStatus("Report downloaded.");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="analytics-page">
      <PageHeader title="RCx Report Builder" subtitle="Collect data, preview readiness, generate DOCX (read-only)" />
      <section className="panel">
        <h2>Report window</h2>
        <div className="toolbar-row">
          {WINDOW_OPTS.map((w) => (
            <button
              key={w.hours}
              type="button"
              className={`btn-chip${hours === w.hours ? " active" : ""}`}
              onClick={() => setHours(w.hours)}
            >
              {w.label}
            </button>
          ))}
        </div>
        <div className="toolbar-row">
          <button type="button" className="btn primary" onClick={collectPreview} disabled={loading}>
            Collect Data / Preview
          </button>
          <button
            type="button"
            className="btn"
            onClick={generateDocx}
            disabled={loading || !preview}
          >
            Generate DOCX
          </button>
        </div>
        {status ? <p className="ok-text">{status}</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
      </section>
      {preview ? (
        <>
          <section className="panel">
            <h2>Data readiness</h2>
            <p>
              Active faults: <strong>{preview.fault_summary.active_faults}</strong> · Total fault hours:{" "}
              <strong>{preview.fault_summary.total_fault_hours}</strong>
            </p>
            {(preview.warnings ?? []).map((w) => (
              <p key={w} className="warning-text">
                {w}
              </p>
            ))}
          </section>
          <div className="analytics-two-col">
            <section className="panel">
              <h2>Charts</h2>
              {preview.available_charts.map((c) => (
                <label key={c.id} className="check-row">
                  <input
                    type="checkbox"
                    checked={selectedCharts.has(c.id)}
                    onChange={() => toggle(setSelectedCharts, c.id)}
                  />
                  {c.label}
                </label>
              ))}
              {preview.disabled_charts.map((c) => (
                <label key={c.id} className="check-row disabled">
                  <input type="checkbox" disabled />
                  {c.label}
                  <span className="muted"> — {c.reason}</span>
                </label>
              ))}
            </section>
            <section className="panel">
              <h2>Sections</h2>
              {preview.sections.map((s) => (
                <label key={s.id} className="check-row">
                  <input
                    type="checkbox"
                    checked={selectedSections.has(s.id)}
                    onChange={() => toggle(setSelectedSections, s.id)}
                  />
                  {s.label}
                </label>
              ))}
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
