import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, hasToken } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";
import type { DisplayFault } from "../../lib/displayFaults";

type Props = {
  fault: DisplayFault | null;
  onClose: () => void;
  onCleared?: () => void;
};

export default function FaultDetailModal({ fault, onClose, onCleared }: Props) {
  const [clearBusy, setClearBusy] = useState(false);
  const [clearError, setClearError] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

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
          {fault.technical ? (
            <section className="bis-modal-section">
              <h4>Technical</h4>
              <pre className="bis-technical">{fault.technical}</pre>
            </section>
          ) : null}
          {fault.meta.length ? (
            <section className="bis-modal-section">
              <h4>At a glance</h4>
              <dl className="bis-meta-grid">
                {fault.meta.map((m) => (
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
