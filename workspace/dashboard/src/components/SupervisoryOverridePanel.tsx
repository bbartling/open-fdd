import ActionButton from "./ActionButton";

export type OverrideStatus = {
  device_count?: number;
  scan_interval_s?: number;
  full_rotation_hours?: number;
  operator_priority?: number;
  operator_override_points?: number;
  total_override_points?: number;
  last_scan_at?: string;
  last_scan_device?: number;
  next_device_instance?: number;
  export_row_count?: number;
};

type Props = {
  status: OverrideStatus | null;
  pending?: boolean;
  disabled?: boolean;
  onScanOnce: () => void;
  onExportCsv: () => void;
};

export default function SupervisoryOverridePanel({ status, pending, disabled, onScanOnce, onExportCsv }: Props) {
  const operator = status?.operator_override_points ?? 0;
  const other = Math.max(0, (status?.total_override_points ?? 0) - operator);

  return (
    <section className="panel supervisory-override-panel" aria-label="Supervisory override scan">
      <h3 className="panel-title">Supervisory Override Scan</h3>
      <p className="muted panel-help">
        Hourly ReadProperty(priority-array) scan on commandable BACnet points. Priority 8 operator overrides appear on
        the dashboard; all active override levels are shown in the driver tree.
      </p>
      <div className="override-metrics">
        <div className="override-metric">
          <span className="override-metric-label">Operator overrides (P8)</span>
          <strong className="override-metric-value">{operator}</strong>
        </div>
        <div className="override-metric">
          <span className="override-metric-label">Other priority overrides</span>
          <strong className="override-metric-value">{other}</strong>
        </div>
        <div className="override-metric">
          <span className="override-metric-label">Last scan</span>
          <strong className="override-metric-value">
            {status?.last_scan_at
              ? `Device ${status.last_scan_device ?? "—"} · ${status.last_scan_at}`
              : "Never"}
          </strong>
        </div>
        <div className="override-metric">
          <span className="override-metric-label">Next scan target</span>
          <strong className="override-metric-value">
            {status?.next_device_instance ? `Device ${status.next_device_instance}` : "Scheduled rotation"}
          </strong>
        </div>
      </div>
      <div className="panel-actions">
        <ActionButton
          label={pending ? "Scanning…" : "Scan next device now"}
          disabled={disabled || pending}
          onClick={onScanOnce}
        />
        <ActionButton
          label={`Export override report CSV (${status?.export_row_count ?? 0} rows)`}
          title="Download supervisory override report from the priority-array scan (CSV)."
          disabled={disabled}
          onClick={onExportCsv}
        />
      </div>
    </section>
  );
}
