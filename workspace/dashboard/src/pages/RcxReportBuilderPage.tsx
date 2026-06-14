import { useState, type Dispatch, type SetStateAction } from "react";
import PageHeader from "../components/PageHeader";
import {
  downloadRcxReport,
  fetchRcxPreview,
  type RcxBundle,
  type RcxPreviewResponse,
} from "../lib/analytics-api";

const WINDOW_OPTS = [
  { label: "2 hours", hours: 2 },
  { label: "24 hours", hours: 24 },
  { label: "7 days", hours: 168 },
];

export default function RcxReportBuilderPage() {
  const [hours, setHours] = useState(168);
  const [preview, setPreview] = useState<RcxPreviewResponse | null>(null);
  const [selectedBundle, setSelectedBundle] = useState("");
  const [selectedCharts, setSelectedCharts] = useState<Set<string>>(new Set());
  const [selectedSections, setSelectedSections] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const bundles: RcxBundle[] = preview?.report_bundles?.bundles ?? [];

  async function collectPreview(bundleId?: string) {
    setLoading(true);
    setError("");
    setStatus("");
    const bid = bundleId ?? selectedBundle;
    try {
      const p = await fetchRcxPreview({
        hours,
        scope: "building",
        bundle_ids: bid ? [bid] : undefined,
        catalog_only: true,
        include_previews: false,
      });
      setPreview(p);
      const chartIds = p.available_charts.map((c) => c.chart_id).filter(Boolean);
      setSelectedCharts(new Set(chartIds));
      setSelectedSections(new Set(p.sections.map((s) => s.id).filter(Boolean)));
      if (!bid && p.report_bundles?.default_bundle_ids?.[0]) {
        setSelectedBundle(p.report_bundles.default_bundle_ids[0]);
      }
      setStatus("Preview ready — review chart readiness below. DOCX uses screenshot placeholders.");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function onBundleChange(bundleId: string) {
    setSelectedBundle(bundleId);
    void collectPreview(bundleId);
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
      const charts = [...selectedCharts].filter((c) => c && c.trim());
      const blob = await downloadRcxReport({
        hours,
        scope: "building",
        bundle_ids: selectedBundle ? [selectedBundle] : undefined,
        charts,
        sections: [...selectedSections].filter(Boolean),
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "openfdd-rcx-report.docx";
      a.click();
      URL.revokeObjectURL(url);
      setStatus("Report downloaded — paste Plotly screenshots into marked placeholders.");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="analytics-page">
      <PageHeader
        title="RCx Report Builder"
        subtitle="BRICK-driven equipment reports — zone/box, AHU, VAV, boiler/HWS, chiller, OAT vs weather. Charts from SPARQL model; paste Plotly snips into INSERT HERE placeholders."
      />
      <section className="panel">
        <h2>Equipment report package</h2>
        <p className="muted">
          Select a building overview or per-equipment report from the BRICK model. Bench BACnet device 5007 maps to a
          zone-level template. Use Trend plot to snip charts into DOCX placeholders.
        </p>
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
        {bundles.length ? (
          <div className="field" style={{ marginTop: 12 }}>
            <label className="field-label" htmlFor="rcx-bundle">
              Report package
            </label>
            <select
              id="rcx-bundle"
              value={selectedBundle}
              onChange={(e) => onBundleChange(e.target.value)}
            >
              <option value="">All default bundles</option>
              {bundles.map((b) => (
                <option key={b.bundle_id} value={b.bundle_id}>
                  {b.label} ({b.chart_count} chart{b.chart_count === 1 ? "" : "s"})
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="toolbar-row">
          <button type="button" className="btn primary" onClick={() => void collectPreview()} disabled={loading}>
            Collect Data / Preview
          </button>
          <button type="button" className="btn" onClick={() => void generateDocx()} disabled={loading || !preview}>
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
            {(preview.diagnostics?.hints ?? []).map((h) => (
              <p key={h} className="muted">
                {h}
              </p>
            ))}
            {(preview.warnings ?? []).map((w) => (
              <p key={w} className="warning-text">
                {w}
              </p>
            ))}
            {preview.diagnostics?.roles_resolved ? (
              <details>
                <summary>SPARQL role → column mapping</summary>
                <ul>
                  {Object.entries(preview.diagnostics.roles_resolved).map(([k, v]) => (
                    <li key={k}>
                      <code>{k}</code>: {v}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </section>
          <div className="analytics-two-col">
            <section className="panel">
              <h2>Charts</h2>
              {preview.available_charts.map((c) => (
                <label key={c.chart_id} className="check-row">
                  <input
                    type="checkbox"
                    checked={selectedCharts.has(c.chart_id)}
                    onChange={() => toggle(setSelectedCharts, c.chart_id)}
                  />
                  {c.title}
                  {c.partial_note ? <span className="muted"> — {c.partial_note}</span> : null}
                </label>
              ))}
              {preview.disabled_charts.map((c) => (
                <label key={c.chart_id} className="check-row disabled">
                  <input type="checkbox" disabled />
                  {c.title}
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
              <p className="muted" style={{ marginTop: 12 }}>
                DOCX includes <strong>[ INSERT SCREENSHOT HERE ]</strong> boxes for each chart and assigned FDD rule
                sensor — paste Plotly snips after download.
              </p>
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
