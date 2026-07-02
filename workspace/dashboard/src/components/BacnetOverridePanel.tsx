import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiDownloadBlob } from "../lib/api";

type OverrideMeta = {
  ok?: boolean;
  retention_years?: number;
  scan_interval_s?: number;
  export_row_count?: number;
  last_scan?: string | null;
};

async function downloadExport(path: string, fallbackName: string) {
  const { blob, filename } = await apiDownloadBlob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || fallbackName;
  a.click();
  URL.revokeObjectURL(url);
}

export default function BacnetOverridePanel() {
  const [meta, setMeta] = useState<OverrideMeta | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ bacnet_override_log?: OverrideMeta }>("/api/data-management/summary");
      setMeta(data.bacnet_override_log ?? null);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load override log status");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onExport(path: string, name: string) {
    setBusy(name);
    setError("");
    try {
      await downloadExport(path, name);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel bacnet-override-panel">
      <h3 className="panel-title">Supervisory override log</h3>
      <p className="muted">
        Priority-array scans append to CSV exports under workspace storage. Rows older than{" "}
        <strong>{meta?.retention_years ?? 1} year</strong> are pruned on each hourly scan.
      </p>
      {error ? <p className="error">{error}</p> : null}
      {meta ? (
        <dl className="meta-dl">
          <div>
            <dt>Export rows</dt>
            <dd>{meta.export_row_count ?? 0}</dd>
          </div>
          <div>
            <dt>Scan cadence</dt>
            <dd>{meta.scan_interval_s ?? 3600}s</dd>
          </div>
          <div>
            <dt>Last scan</dt>
            <dd>{meta.last_scan ?? "—"}</dd>
          </div>
        </dl>
      ) : (
        <p className="muted">Loading…</p>
      )}
      <div className="action-bar action-bar-spaced">
        <button
          type="button"
          className="secondary-btn"
          disabled={!!busy}
          onClick={() => void onExport("/api/bacnet/overrides/export", "bacnet_overrides_export.csv")}
        >
          {busy === "bacnet_overrides_export.csv" ? "Exporting…" : "All overrides CSV"}
        </button>
        <button
          type="button"
          className="secondary-btn"
          disabled={!!busy}
          onClick={() => void onExport("/api/bacnet/overrides/export/p8", "bacnet_overrides_p8.csv")}
        >
          {busy === "bacnet_overrides_p8.csv" ? "Exporting…" : "P8 overrides CSV"}
        </button>
        <button
          type="button"
          className="secondary-btn"
          disabled={!!busy}
          onClick={() => void onExport("/api/bacnet/overrides/export/non-p8", "bacnet_overrides_non_p8.csv")}
        >
          {busy === "bacnet_overrides_non_p8.csv" ? "Exporting…" : "Non-P8 CSV"}
        </button>
        <button type="button" className="linkish-btn" onClick={() => void load()}>
          Refresh status
        </button>
      </div>
    </section>
  );
}
