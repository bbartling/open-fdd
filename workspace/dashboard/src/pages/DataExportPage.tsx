import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import ActionButton from "../components/ActionButton";
import { apiDownloadBlob, apiFetch, fetchAuthMe } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  appendExportQuery,
  DATA_EXPORT_PANEL_TITLE,
  exportButtonLabel,
  type ExportFilters,
  type ExportMeta,
  visibleExports,
} from "../lib/dataExport";

type LastExport = {
  label: string;
  ok: boolean;
  detail: string;
  at: string;
};

const HOUR_OPTIONS = [
  { value: 0, label: "All available data" },
  { value: 6, label: "Last 6 hours" },
  { value: 24, label: "Last 24 hours" },
  { value: 168, label: "Last 7 days" },
];

export default function DataExportPage() {
  const [meta, setMeta] = useState<ExportMeta | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [lastExport, setLastExport] = useState<LastExport | null>(null);
  const [filters, setFilters] = useState<ExportFilters>({
    hours: 24,
    site_id: "site:demo",
    building_id: "building:main",
  });

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [m, me] = await Promise.all([
        apiFetch<ExportMeta>("/api/export/meta"),
        fetchAuthMe().catch(() => null),
      ]);
      setMeta(m);
      setRole(me?.role ?? null);
      setFilters((prev) => ({
        ...prev,
        site_id: prev.site_id || m.filters.sites[0] || "site:demo",
        building_id: prev.building_id || m.filters.buildings[0] || "building:main",
      }));
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const exports = useMemo(
    () => (meta ? visibleExports(meta, role) : []),
    [meta, role],
  );

  async function downloadExport(exportId: string, path: string, label: string) {
    setDownloadingId(exportId);
    setError("");
    try {
      const url = appendExportQuery(path, filters);
      const { blob, filename } = await apiDownloadBlob(url);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
      setLastExport({
        label,
        ok: true,
        detail: `Saved ${filename}`,
        at: new Date().toLocaleString(),
      });
    } catch (err) {
      const detail = formatApiError(err);
      setLastExport({
        label,
        ok: false,
        detail,
        at: new Date().toLocaleString(),
      });
      setError(detail);
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className="page data-export-page">
      <PageHeader
        title={DATA_EXPORT_PANEL_TITLE}
        subtitle="Download spreadsheet-ready CSV files for historian trends, faults, BACnet overrides, and model metadata."
      />

      {error ? <p className="error-banner">{error}</p> : null}

      <section className="panel" aria-label={DATA_EXPORT_PANEL_TITLE}>
        <h3 className="panel-title">{DATA_EXPORT_PANEL_TITLE}</h3>
        <p className="muted panel-help">
          Exports use ISO 8601 UTC timestamps plus Excel-friendly local time columns, stable headers, units, and
          point metadata. CSV is the default format for operators and energy engineers.
        </p>

        {meta && !meta.xlsx_supported ? (
          <p className="muted panel-help">{meta.xlsx_note}</p>
        ) : null}

        <div className="export-filters">
          <label className="field">
            <span>Time range</span>
            <select
              value={filters.hours ?? 0}
              onChange={(e) =>
                setFilters((f) => ({ ...f, hours: Number(e.target.value) || undefined }))
              }
            >
              {HOUR_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Site</span>
            <select
              value={filters.site_id || ""}
              onChange={(e) => setFilters((f) => ({ ...f, site_id: e.target.value }))}
            >
              {(meta?.filters.sites ?? ["site:demo"]).map((site) => (
                <option key={site} value={site}>
                  {site}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Building</span>
            <select
              value={filters.building_id || ""}
              onChange={(e) => setFilters((f) => ({ ...f, building_id: e.target.value }))}
            >
              {(meta?.filters.buildings ?? ["building:main"]).map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Protocol / source</span>
            <select
              value={filters.source_protocol || ""}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  source_protocol: e.target.value || undefined,
                }))
              }
            >
              <option value="">All protocols</option>
              {(meta?.filters.protocols ?? []).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Equipment</span>
            <select
              value={filters.equipment_id || ""}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  equipment_id: e.target.value || undefined,
                }))
              }
            >
              <option value="">All equipment</option>
              {(meta?.filters.equipment ?? []).map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </label>
        </div>

        {loading ? <p className="muted">Loading export catalog…</p> : null}

        <div className="export-download-list">
          {exports.map((item) => (
            <div key={item.id} className="export-download-row">
              <div className="export-download-meta">
                <strong>{item.label}</strong>
                {item.data_source_label ? (
                  <span className="muted">Source: {item.data_source_label}</span>
                ) : null}
                {item.row_count != null ? (
                  <span className="muted">Estimated rows: {item.row_count.toLocaleString()}</span>
                ) : null}
              </div>
              <ActionButton
                label={
                  downloadingId === item.id
                    ? "Downloading…"
                    : exportButtonLabel(item)
                }
                disabled={loading || downloadingId != null || item.available === false}
                onClick={() => void downloadExport(item.id, item.path, item.label)}
              />
            </div>
          ))}
        </div>

        {lastExport ? (
          <p className={`export-last-status ${lastExport.ok ? "ok" : "error"}`}>
            Last export ({lastExport.at}): {lastExport.label} — {lastExport.detail}
          </p>
        ) : null}
      </section>
    </div>
  );
}
