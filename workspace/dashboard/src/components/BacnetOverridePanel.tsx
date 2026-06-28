import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type OverrideMeta = {
  ok?: boolean;
  retention_years?: number;
  scan_interval_s?: number;
  export_row_count?: number;
  last_scan?: string | null;
};

export default function BacnetOverridePanel() {
  const [meta, setMeta] = useState<OverrideMeta | null>(null);
  const [error, setError] = useState("");

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
        <a className="secondary-btn" href="/api/bacnet/overrides/export">
          All overrides CSV
        </a>
        <a className="secondary-btn" href="/api/bacnet/overrides/export/p8">
          P8 overrides CSV
        </a>
        <a className="secondary-btn" href="/api/bacnet/overrides/export/non-p8">
          Non-P8 CSV
        </a>
        <button type="button" className="linkish-btn" onClick={() => void load()}>
          Refresh status
        </button>
      </div>
    </section>
  );
}
