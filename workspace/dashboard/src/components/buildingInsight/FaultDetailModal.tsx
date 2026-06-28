import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, hasToken } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";
import type { DisplayFault } from "../../lib/displayFaults";
import type { FaultAnalytics } from "../../lib/dashboardStream";

type FaultRecord = {
  fault_id?: string;
  equipment_id?: string;
  rule_id?: string;
  rule_name?: string;
  input_points?: string[];
  analytics?: FaultAnalytics;
};

type Props = {
  fault: DisplayFault | null;
  onClose: () => void;
  onCleared?: () => void;
};

function analyticsFromFault(fault: DisplayFault): FaultAnalytics | undefined {
  const fromUnderlying = fault.underlying[0]?.analytics;
  if (fromUnderlying) return fromUnderlying;
  const hours = fault.meta.find((m) => m.label === "Time in fault");
  if (!hours) return undefined;
  return { estimated_fault_duration_label: hours.value };
}


export default function FaultDetailModal({ fault, onClose, onCleared }: Props) {
  const [clearBusy, setClearBusy] = useState(false);
  const [clearError, setClearError] = useState("");
  const [detailBusy, setDetailBusy] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [record, setRecord] = useState<FaultRecord | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (!fault || fault.id.startsWith("group-")) {
      setRecord(null);
      setDetailError("");
      return;
    }
    let cancelled = false;
    setDetailBusy(true);
    setDetailError("");
    apiFetch<{ ok?: boolean; fault?: FaultRecord }>(`/api/faults/${encodeURIComponent(fault.id)}`)
      .then((res) => {
        if (cancelled) return;
        setRecord(res.fault ?? null);
      })
      .catch((e) => {
        if (cancelled) return;
        setRecord(null);
        setDetailError(formatApiError(e));
      })
      .finally(() => {
        if (!cancelled) setDetailBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fault]);

  const analytics = useMemo(() => {
    if (!fault) return undefined;
    return record?.analytics ?? analyticsFromFault(fault);
  }, [fault, record]);

  const deviceId = useMemo(() => {
    if (!fault) return "";
    return (
      record?.equipment_id ||
      fault.underlying[0]?.equipment_id ||
      fault.underlying[0]?.equipment_name ||
      fault.equipmentLabel
    );
  }, [fault, record]);

  const sensorColumns = analytics?.value_columns?.length
    ? analytics.value_columns
    : record?.input_points?.length
      ? record.input_points
      : [];

  if (!fault) return null;

  async function clearFault() {
    if (!hasToken()) {
      setClearError("Operator login required to clear faults.");
      return;
    }
    setClearBusy(true);
    setClearError("");
    try {
      await apiFetch(`/api/faults/${encodeURIComponent(fault!.id)}/clear`, { method: "POST" });
      onCleared?.();
      onClose();
    } catch (e) {
      setClearError(formatApiError(e));
    } finally {
      setClearBusy(false);
    }
  }

  const canClear =
    fault.source !== "poll_health" &&
    fault.source !== "model_health" &&
    fault.source !== "bacnet_override" &&
    !fault.id.startsWith("group-");

  const metaWithoutAnalytics = fault.meta.filter(
    (m) =>
      ![
        "First seen",
        "Last seen",
        "Fault window",
        "Time in fault",
        "Avg in fault",
        "Avg normal",
        "In-fault range",
        "Samples",
      ].includes(m.label),
  );

  return (
    <div
      className="bis-modal-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bis-modal" role="dialog" aria-labelledby="bis-modal-title">
        <div className="bis-modal-head">
          <span className={`bis-severity-pill bis-sev-${fault.severity}`}>{fault.severityLabel}</span>
          <div className="bis-modal-head-text">
            <h2 id="bis-modal-title">{fault.title}</h2>
            <div className="bis-modal-eq">{fault.equipmentLabel}</div>
          </div>
          <button type="button" className="bis-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bis-modal-body">
          <section className="bis-modal-section">
            <h4>What this means</h4>
            <p>{fault.plainEnglish}</p>
          </section>

          {deviceId ? (
            <section className="bis-modal-section">
              <h4>Device in alarm</h4>
              <p className="bis-device-id">{deviceId}</p>
              {record?.rule_name || record?.rule_id ? (
                <p className="muted">
                  Rule: {record.rule_name || record.rule_id}
                  {sensorColumns.length ? ` · sensor ${sensorColumns.join(", ")}` : ""}
                </p>
              ) : null}
            </section>
          ) : null}

          {detailBusy ? <p className="muted">Loading Rust fault analytics…</p> : null}
          {detailError ? <p className="error">{detailError}</p> : null}

          {analytics ? (
            <section className="bis-modal-section">
              <h4>Sensor statistics (historian)</h4>
              <p className="muted bis-analytics-note">
                Computed in Rust from historian samples — in-alarm vs normal operating periods.
              </p>
              <dl className="bis-meta-grid bis-analytics-grid">
                {analytics.estimated_fault_duration_label || analytics.hours_in_fault != null ? (
                  <div>
                    <dt>Elapsed in alarm</dt>
                    <dd>
                      {analytics.estimated_fault_duration_label ??
                        `${Number(analytics.hours_in_fault).toFixed(1)} h`}
                    </dd>
                  </div>
                ) : null}
                {analytics.fault_span_label ? (
                  <div>
                    <dt>Alarm window</dt>
                    <dd>{analytics.fault_span_label}</dd>
                  </div>
                ) : null}
                {analytics.avg_value_fault != null ? (
                  <div>
                    <dt>Avg while in alarm</dt>
                    <dd>
                      {analytics.avg_value_fault}
                      {analytics.value_unit ? ` ${analytics.value_unit}` : ""}
                    </dd>
                  </div>
                ) : null}
                {analytics.avg_value_normal != null ? (
                  <div>
                    <dt>Avg while normal</dt>
                    <dd>
                      {analytics.avg_value_normal}
                      {analytics.value_unit ? ` ${analytics.value_unit}` : ""}
                    </dd>
                  </div>
                ) : null}
                {analytics.min_value_fault != null && analytics.max_value_fault != null ? (
                  <div>
                    <dt>In-alarm range</dt>
                    <dd>
                      {analytics.min_value_fault} – {analytics.max_value_fault}
                      {analytics.value_unit ? ` ${analytics.value_unit}` : ""}
                    </dd>
                  </div>
                ) : null}
                {analytics.fault_samples != null && analytics.total_samples != null ? (
                  <div>
                    <dt>Samples in alarm</dt>
                    <dd>
                      {analytics.fault_samples} / {analytics.total_samples}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </section>
          ) : null}

          {fault.detail && fault.detail !== fault.plainEnglish ? (
            <section className="bis-modal-section">
              <h4>Detail</h4>
              <p>{fault.detail}</p>
            </section>
          ) : null}
          {fault.underlying.length > 1 ? (
            <section className="bis-modal-section">
              <h4>Affected ({fault.underlying.length})</h4>
              <ul className="bis-modal-list">
                {fault.underlying.map((u) => (
                  <li key={String(u.id || u.title)}>
                    <strong>{u.equipment_name || u.title}</strong>
                    {u.detail ? <span className="muted"> — {u.detail}</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {metaWithoutAnalytics.length ? (
            <section className="bis-modal-section">
              <h4>At a glance</h4>
              <dl className="bis-meta-grid">
                {metaWithoutAnalytics.map((m) => (
                  <div key={m.label}>
                    <dt>{m.label}</dt>
                    <dd>{m.value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
          {clearError ? <p className="error">{clearError}</p> : null}
          <div className="bis-modal-actions">
            {canClear ? (
              <button
                type="button"
                className="bis-btn bis-btn-secondary"
                disabled={clearBusy}
                onClick={() => void clearFault()}
              >
                {clearBusy ? "Clearing…" : hasToken() ? "Clear fault" : "Clear (login required)"}
              </button>
            ) : null}
            {fault.source === "model_health" ? (
              <Link to="/model" className="bis-btn bis-btn-primary" onClick={onClose}>
                Open data model
              </Link>
            ) : fault.source === "poll_health" ? (
              <Link to="/bacnet" className="bis-btn bis-btn-primary" onClick={onClose}>
                BACnet &amp; poll
              </Link>
            ) : (
              <Link to="/model" className="bis-btn bis-btn-primary" onClick={onClose}>
                Model &amp; assignments
              </Link>
            )}
            <button type="button" className="bis-btn bis-btn-secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
