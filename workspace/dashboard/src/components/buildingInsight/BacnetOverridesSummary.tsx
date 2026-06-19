import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";

type OverrideRow = {
  device_instance: number;
  device_address?: string;
  device_label?: string;
  object_name?: string;
  object_identifier?: string;
  priority_level?: number;
  value_text?: string;
  value?: unknown;
  scanned_at?: string;
};

type DeviceBucket = {
  device_instance: number;
  device_address?: string;
  device_label?: string;
  operator_override_count: number;
  total_override_count: number;
  last_scanned_at?: string;
  points?: OverrideRow[];
};

type ScanHealth = {
  ok?: boolean;
  status?: string;
  detail?: string;
  last_scan_age_s?: number | null;
  device_count?: number;
  full_rotation_hours?: number;
};

type OverrideSummary = {
  ok?: boolean;
  operator_override_points?: number;
  total_override_points?: number;
  preview_limit?: number;
  preview_total?: number;
  preview?: OverrideRow[];
  by_device?: DeviceBucket[];
  scan_health?: ScanHealth;
  scan?: {
    scan_interval_s?: number;
    device_count?: number;
    full_rotation_hours?: number;
    last_scan_at?: string;
    last_scan_device?: number | null;
    operator_priority?: number;
  };
};

function formatScanAge(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 7200) return `${Math.round(seconds / 60)}m ago`;
  return `${(seconds / 3600).toFixed(1)}h ago`;
}

function formatUtcShort(value?: string): string {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  return raw.replace("T", " ").slice(0, 19);
}

function healthPillClass(status?: string, ok?: boolean): string {
  if (ok) return "bis-override-health bis-override-health--ok";
  if (status === "stale") return "bis-override-health bis-override-health--warn";
  if (status === "error") return "bis-override-health bis-override-health--err";
  return "bis-override-health bis-override-health--muted";
}

function healthLabel(status?: string, ok?: boolean): string {
  if (ok) return "Scan healthy";
  if (status === "stale") return "Scan stale";
  if (status === "error") return "Scan error";
  if (status === "no_devices") return "No devices";
  return "Scan status";
}

type Props = {
  fallbackCount?: number;
};

export default function BacnetOverridesSummary({ fallbackCount = 0 }: Props) {
  const [summary, setSummary] = useState<OverrideSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAllDevices, setShowAllDevices] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await apiFetch<OverrideSummary>("/api/bacnet/overrides/summary?preview_limit=8");
      setSummary(res);
    } catch (e) {
      setSummary(null);
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 5 * 60 * 1000);
    return () => window.clearInterval(t);
  }, [load]);

  const preview = summary?.preview ?? [];
  const byDevice = summary?.by_device ?? [];
  const p8Count = summary?.operator_override_points ?? fallbackCount;
  const scanHealth = summary?.scan_health;
  const scan = summary?.scan;
  const previewLimit = summary?.preview_limit ?? 8;
  const previewTotal = summary?.preview_total ?? p8Count;

  const deviceRows = useMemo(
    () => (showAllDevices ? byDevice : byDevice.filter((d) => d.operator_override_count > 0 || d.total_override_count > 0)),
    [byDevice, showAllDevices],
  );

  return (
    <div className="bis-card bis-override-card">
      <div className="bis-card-head-row">
        <div>
          <h3>BACnet operator overrides</h3>
          <p className="bis-card-sub bis-card-sub-compact">
            Hourly supervisory scan (one device per cycle) · priority P{scan?.operator_priority ?? 8}
          </p>
        </div>
        <div className="bis-override-head-actions">
          <span className={healthPillClass(scanHealth?.status, scanHealth?.ok)} title={scanHealth?.detail || ""}>
            {healthLabel(scanHealth?.status, scanHealth?.ok)}
          </span>
          <button type="button" className="bis-btn bis-btn-secondary" disabled={loading} onClick={() => void load()}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="bis-override-meta-row">
        <div className="bis-override-stat">
          <span className="label">P8 overrides</span>
          <strong className={p8Count > 0 ? "bis-warn-value" : ""}>{p8Count}</strong>
        </div>
        <div className="bis-override-stat">
          <span className="label">Devices in rotation</span>
          <strong>{scan?.device_count ?? scanHealth?.device_count ?? "—"}</strong>
        </div>
        <div className="bis-override-stat">
          <span className="label">Full plant pass</span>
          <strong>{scan?.full_rotation_hours != null ? `${scan.full_rotation_hours}h` : "—"}</strong>
        </div>
        <div className="bis-override-stat">
          <span className="label">Last scan</span>
          <strong>{formatScanAge(scanHealth?.last_scan_age_s)}</strong>
        </div>
      </div>

      {scanHealth?.detail ? <p className="bis-override-scan-detail muted">{scanHealth.detail}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {preview.length ? (
        <>
          <div className="bis-override-section-head">
            <h4>
              Current P8 overrides
              {previewTotal > previewLimit ? ` (showing ${preview.length} of ${previewTotal})` : ""}
            </h4>
            <Link to="/bacnet" className="bis-inline-link">
              BACnet tab →
            </Link>
          </div>
          <div className="bis-override-table-wrap">
            <table className="bis-override-table">
              <thead>
                <tr>
                  <th>Device</th>
                  <th>Address</th>
                  <th>Point</th>
                  <th>Value</th>
                  <th>Last scan (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {preview.map((row) => (
                  <tr key={`${row.device_instance}-${row.object_identifier}-${row.priority_level}`}>
                    <td>
                      <strong>{row.device_instance}</strong>
                      <div className="muted bis-override-sub">{row.device_label || `Device ${row.device_instance}`}</div>
                    </td>
                    <td className="mono">{row.device_address || "—"}</td>
                    <td>
                      <strong>{row.object_name || row.object_identifier}</strong>
                      {row.object_identifier && row.object_name ? (
                        <div className="muted bis-override-sub mono">{row.object_identifier}</div>
                      ) : null}
                    </td>
                    <td className="mono">{row.value_text ?? String(row.value ?? "—")}</td>
                    <td className="mono">{formatUtcShort(row.scanned_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : !loading ? (
        <p className="bis-lead bis-ok-text">No active P8 operator overrides in the registry.</p>
      ) : null}

      {byDevice.length ? (
        <>
          <div className="bis-override-section-head bis-override-section-head--spaced">
            <h4>By BACnet device</h4>
            <button
              type="button"
              className="bis-btn bis-btn-ghost"
              onClick={() => setShowAllDevices((v) => !v)}
            >
              {showAllDevices ? "P8 / overrides only" : `Show all ${byDevice.length} devices`}
            </button>
          </div>
          <div className="bis-override-table-wrap">
            <table className="bis-override-table bis-override-table--devices">
              <thead>
                <tr>
                  <th>Device</th>
                  <th>Address</th>
                  <th>P8 points</th>
                  <th>All priorities</th>
                  <th>Last scanned (UTC)</th>
                </tr>
              </thead>
              <tbody>
                {deviceRows.map((dev) => (
                  <tr
                    key={dev.device_instance}
                    className={dev.operator_override_count > 0 ? "bis-override-row-alert" : ""}
                  >
                    <td>
                      <strong>{dev.device_instance}</strong>
                    </td>
                    <td className="mono">{dev.device_address || "—"}</td>
                    <td className={dev.operator_override_count > 0 ? "bis-warn-value" : ""}>{dev.operator_override_count}</td>
                    <td>{dev.total_override_count}</td>
                    <td className="mono">{formatUtcShort(dev.last_scanned_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
