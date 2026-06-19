import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import PageHeader from "../components/PageHeader";
import RcxReportsLibrary from "../components/RcxReportsLibrary";
import {
  downloadRcxReport,
  fetchRcxPreview,
  type RcxBundle,
  type RcxPreviewResponse,
} from "../lib/analytics-api";
import {
  HISTORY_PRESETS,
  resolveHistoryPreset,
  type WindowSelection,
} from "../lib/time-window";

const RCX_WINDOW_PRESETS = [
  { id: "2h", label: "2 hours", hours: 2 },
  ...HISTORY_PRESETS.filter((p) => ["24h", "7d", "30d", "mtd", "last-month", "ytd"].includes(p.id)),
];

function resolveRcxPreset(id: string): WindowSelection {
  if (id === "2h") return { presetId: "2h", hours: 2 };
  return resolveHistoryPreset(id);
}

export default function RcxReportBuilderPage() {
  const [windowSel, setWindowSel] = useState<WindowSelection>(() => resolveRcxPreset("7d"));
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [preview, setPreview] = useState<RcxPreviewResponse | null>(null);
  const [selectedBundle, setSelectedBundle] = useState("");
  const [selectedCharts, setSelectedCharts] = useState<Set<string>>(new Set());
  const [selectedSections, setSelectedSections] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [libraryRefresh, setLibraryRefresh] = useState(0);

  const bundles: RcxBundle[] = preview?.report_bundles?.bundles ?? [];

  const reportBody = useMemo(() => {
    if (windowSel.presetId === "custom" && customStart && customEnd) {
      return { hours: 168, start: new Date(customStart).toISOString(), end: new Date(customEnd).toISOString() };
    }
    if (windowSel.start && windowSel.end) {
      return { hours: windowSel.hours, start: windowSel.start, end: windowSel.end };
    }
    return { hours: windowSel.hours };
  }, [windowSel, customStart, customEnd]);

  async function collectPreview(bundleId?: string) {
    setLoading(true);
    setError("");
    setStatus("");
    const bid = bundleId ?? selectedBundle;
    try {
      const p = await fetchRcxPreview({
        ...reportBody,
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

  function onPreset(id: string) {
    if (id === "custom") {
      setWindowSel({ presetId: "custom", hours: 168 });
      return;
    }
    setWindowSel(resolveRcxPreset(id));
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
      const { blob, savedFilename } = await downloadRcxReport({
        ...reportBody,
        scope: "building",
        bundle_ids: selectedBundle ? [selectedBundle] : undefined,
        charts,
        sections: [...selectedSections].filter(Boolean),
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = savedFilename || "openfdd-rcx-report.docx";
      a.click();
      URL.revokeObjectURL(url);
      setLibraryRefresh((n) => n + 1);
      setStatus(
        savedFilename
          ? `Report saved as ${savedFilename} — see library below. Paste Plotly screenshots into placeholders after download.`
          : "Report downloaded — paste Plotly screenshots into marked placeholders.",
      );
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
        subtitle="Equipment reports from the BRICK model — charts, DOCX export, saved library."
      />
      <section className="panel rcx-builder-panel">
        <p className="rcx-intro ui-sr-lead">
          Pick a report package and time range. Use Trend plot to capture charts into DOCX placeholders.
        </p>

        <div className="rcx-toolbar-block">
          <span className="rcx-toolbar-label">Time range</span>
          <div className="toolbar-row rcx-window-chips">
            {RCX_WINDOW_PRESETS.map((w) => (
              <button
                key={w.id}
                type="button"
                className={`btn-chip${windowSel.presetId === w.id ? " active" : ""}`}
                onClick={() => onPreset(w.id)}
              >
                {w.label}
              </button>
            ))}
            <button
              type="button"
              className={`btn-chip${windowSel.presetId === "custom" ? " active" : ""}`}
              onClick={() => onPreset("custom")}
            >
              Custom dates
            </button>
          </div>
          {windowSel.presetId === "custom" ? (
            <div className="rcx-date-row">
              <label className="field">
                <span className="field-label">Start</span>
                <input type="datetime-local" value={customStart} onChange={(e) => setCustomStart(e.target.value)} />
              </label>
              <label className="field">
                <span className="field-label">End</span>
                <input type="datetime-local" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} />
              </label>
            </div>
          ) : null}
        </div>

        {bundles.length ? (
          <div className="field rcx-bundle-field">
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

        <div className="rcx-toolbar-block rcx-actions-block">
          <span className="rcx-toolbar-label">Actions</span>
          <div className="toolbar-row rcx-action-row">
            <button type="button" className="btn primary" onClick={() => void collectPreview()} disabled={loading}>
              Collect Data / Preview
            </button>
            <button type="button" className="btn" onClick={() => void generateDocx()} disabled={loading || !preview}>
              Generate DOCX
            </button>
          </div>
        </div>

        {status ? <p className="ok-text">{status}</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
      </section>

      <RcxReportsLibrary refreshToken={libraryRefresh} />

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
