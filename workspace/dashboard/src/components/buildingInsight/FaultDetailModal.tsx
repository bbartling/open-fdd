import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { DisplayFault } from "../../lib/displayFaults";
import type { FaultAnalytics } from "../../lib/dashboardStream";
import { apiFetch } from "../../lib/api";
import {
  describeFaultCause,
  plotLinkForFault,
  ruleConfigLines,
} from "../../lib/faultInsight";

type Props = {
  fault: DisplayFault | null;
  onClose: () => void;
  canClear?: boolean;
  clearing?: boolean;
  onClear?: (fault: DisplayFault) => void;
};

type SavedRuleMeta = {
  id: string;
  name?: string;
  short_description?: string;
  config?: Record<string, unknown>;
};

export default function FaultDetailModal({ fault, onClose, canClear, clearing, onClear }: Props) {
  const [ruleMeta, setRuleMeta] = useState<SavedRuleMeta | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    setRuleMeta(null);
    if (!fault || fault.source !== "fdd") return;
    const rid = fault.modelContext?.rule_id || fault.underlying[0]?.rule_id;
    if (!rid) return;
    let cancelled = false;
    apiFetch<{ rules: SavedRuleMeta[] }>("/api/rules/saved")
      .then((res) => {
        if (cancelled) return;
        const hit = (res.rules || []).find((r) => r.id === rid);
        setRuleMeta(hit || { id: rid });
      })
      .catch(() => {
        if (!cancelled) setRuleMeta({ id: rid });
      });
    return () => {
      cancelled = true;
    };
  }, [fault]);

  if (!fault) return null;

  const ctx = fault.modelContext;
  const primary = fault.underlying[0];
  const analytics = (primary?.analytics || {}) as FaultAnalytics;
  const insight = ctx?.insight;
  const sensors = insight?.sensors?.length ? insight.sensors : [];
  const unit = analytics.value_unit || insight?.value_unit || "°F";
  const ruleName = ctx?.rule_name || primary?.rule_name || ruleMeta?.name || "";
  const ruleId = ctx?.rule_id || primary?.rule_id || ruleMeta?.id || "";
  const configLines = ruleConfigLines(ruleMeta?.config);
  const thresholdLines = (() => {
    const lines: { label: string; value: string }[] = [];
    const lo = insight?.rule_bounds_low ?? insight?.bounds_low ?? analytics.bounds_low;
    const hi = insight?.rule_bounds_high ?? insight?.bounds_high ?? analytics.bounds_high;
    if (lo != null && String(lo).trim() !== "") lines.push({ label: "Low setpoint", value: `${lo}${unit}` });
    if (hi != null && String(hi).trim() !== "") lines.push({ label: "High setpoint", value: `${hi}${unit}` });
    if (insight?.rule_window_samples != null)
      lines.push({ label: "Window (samples)", value: String(insight.rule_window_samples) });
    if (insight?.rule_flatline_tolerance != null)
      lines.push({ label: "Flatline tolerance", value: String(insight.rule_flatline_tolerance) });
    return lines;
  })();
  const causeText = describeFaultCause(analytics, ruleMeta?.config);
  const plotHref = plotLinkForFault(ctx?.equipment?.id, ctx?.site_id);

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
            <div className="bis-modal-eq">{fault.symptom}</div>
            {fault.dataSource ? <span className="bis-source-badge">{fault.dataSource}</span> : null}
          </div>
          <button type="button" className="bis-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="bis-modal-body">
          {fault.source === "fdd" ? (
            <section className="bis-modal-section bis-modal-cause">
              <h4>Why this fired</h4>
              <p>{causeText}</p>
              {thresholdLines.length || configLines.length ? (
                <dl className="bis-meta-grid bis-meta-grid-compact">
                  {[...thresholdLines, ...configLines.filter((c) => !thresholdLines.some((t) => t.label === c.label))].map(
                    (line) => (
                      <div key={line.label}>
                        <dt>{line.label}</dt>
                        <dd>{line.value}</dd>
                      </div>
                    ),
                  )}
                </dl>
              ) : null}
            </section>
          ) : null}

          {fault.source === "fdd" && (insight || analytics.avg_value_fault != null) ? (
            <section className="bis-modal-section">
              <h4>Sensor analytics</h4>
              {sensors.length > 1 ? (
                <div className="bis-sensor-table-wrap">
                  <table className="bis-sensor-table">
                    <thead>
                      <tr>
                        <th>Sensor</th>
                        <th>Avg fault</th>
                        <th>Avg OK</th>
                        <th>Avg overall</th>
                        <th>Avg motor run</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sensors.map((s) => (
                        <tr key={s.column || s.label}>
                          <td>
                            <strong>{s.label || s.column}</strong>
                            {s.brick_type ? <div className="muted">{s.brick_type}</div> : null}
                          </td>
                          <td>{s.avg_while_fault != null ? `${s.avg_while_fault}${unit}` : "—"}</td>
                          <td>{s.avg_while_ok != null ? `${s.avg_while_ok}${unit}` : "—"}</td>
                          <td>
                            {s.avg_overall != null
                              ? `${s.avg_overall}${unit}${s.min_overall != null && s.max_overall != null ? ` (${s.min_overall}–${s.max_overall})` : ""}`
                              : "—"}
                          </td>
                          <td>{s.avg_while_motor_run != null ? `${s.avg_while_motor_run}${unit}` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <dl className="bis-meta-grid">
                  {insight?.avg_while_fault != null || analytics.avg_value_fault != null ? (
                    <div>
                      <dt>Avg while fault</dt>
                      <dd>
                        {insight?.avg_while_fault ?? analytics.avg_value_fault}
                        {unit}
                      </dd>
                    </div>
                  ) : null}
                  {insight?.avg_while_ok != null ? (
                    <div>
                      <dt>Avg while OK</dt>
                      <dd>
                        {insight.avg_while_ok}
                        {unit}
                      </dd>
                    </div>
                  ) : null}
                  {insight?.avg_overall != null ? (
                    <div>
                      <dt>Avg overall (lookback)</dt>
                      <dd>
                        {insight.avg_overall}
                        {unit}
                        {insight.min_overall != null && insight.max_overall != null
                          ? ` (${insight.min_overall}–${insight.max_overall})`
                          : ""}
                      </dd>
                    </div>
                  ) : null}
                  {insight?.avg_while_motor_run != null ? (
                    <div>
                      <dt>Avg while motor run</dt>
                      <dd>
                        {insight.avg_while_motor_run}
                        {unit}
                        {insight.motor_label ? ` · ${insight.motor_label}` : ""}
                      </dd>
                    </div>
                  ) : null}
                  {insight?.avg_while_motor_run_fault != null ? (
                    <div>
                      <dt>Avg motor run + fault</dt>
                      <dd>
                        {insight.avg_while_motor_run_fault}
                        {unit}
                      </dd>
                    </div>
                  ) : null}
                  {insight?.fault_sample_pct != null ? (
                    <div>
                      <dt>Fault sample rate</dt>
                      <dd>{insight.fault_sample_pct}% of lookback</dd>
                    </div>
                  ) : null}
                  {insight?.motor_runtime_hours != null && insight.motor_runtime_hours > 0 ? (
                    <div>
                      <dt>Motor run-hours</dt>
                      <dd>
                        {insight.motor_runtime_hours} h
                        {insight.motor_equipment ? ` (${insight.motor_equipment})` : ""}
                      </dd>
                    </div>
                  ) : null}
                  {insight?.historian_source ? (
                    <div>
                      <dt>Historian source</dt>
                      <dd>{insight.historian_source}</dd>
                    </div>
                  ) : null}
                </dl>
              )}
            </section>
          ) : null}

          {ctx && fault.source === "fdd" ? (
            <section className="bis-modal-section">
              <h4>Equipment &amp; sensor</h4>
              <dl className="bis-meta-grid">
                <div>
                  <dt>Equipment</dt>
                  <dd>
                    {ctx.equipment?.name || "—"}
                    {ctx.equipment?.type && ctx.equipment.type !== "—"
                      ? ` — ${ctx.equipment.type}`
                      : ""}
                  </dd>
                </div>
                <div>
                  <dt>Rule</dt>
                  <dd>{ruleName || ruleId || "—"}</dd>
                </div>
                <div>
                  <dt>Point / sensor</dt>
                  <dd>{ctx.point?.name || "not mapped"}</dd>
                </div>
                <div>
                  <dt>Historian column</dt>
                  <dd>{ctx.historian_column || ctx.point?.external_id || "—"}</dd>
                </div>
                {ctx.point?.brick_type ? (
                  <div>
                    <dt>BRICK class</dt>
                    <dd>{ctx.point.brick_type}</dd>
                  </div>
                ) : null}
                <div>
                  <dt>BACnet</dt>
                  <dd>{ctx.bacnet_summary || "not available"}</dd>
                </div>
                {ctx.site_id ? (
                  <div>
                    <dt>Site</dt>
                    <dd>{ctx.site_id}</dd>
                  </div>
                ) : null}
              </dl>
            </section>
          ) : null}

          <section className="bis-modal-section">
            <h4>What this means</h4>
            <p>{fault.plainEnglish}</p>
          </section>

          {fault.detail && fault.detail !== fault.plainEnglish && fault.detail !== causeText ? (
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

          {fault.technical && !ctx ? (
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

          <div className="bis-modal-actions">
            {fault.source === "fdd" ? (
              <>
                <Link to={plotHref} className="bis-btn bis-btn-primary" onClick={onClose}>
                  View trend
                </Link>
                <Link to="/rule-lab" className="bis-btn bis-btn-secondary" onClick={onClose}>
                  Rule Lab
                </Link>
              </>
            ) : null}
            {fault.source === "model_health" ? (
              <Link to="/model" className="bis-btn bis-btn-primary" onClick={onClose}>
                Open data model
              </Link>
            ) : null}
            {fault.source === "poll_health" ? (
              <Link to="/bacnet" className="bis-btn bis-btn-primary" onClick={onClose}>
                BACnet &amp; poll
              </Link>
            ) : null}
            {canClear && onClear ? (
              <button
                type="button"
                className="bis-btn bis-btn-clear"
                disabled={clearing}
                onClick={() => onClear(fault)}
              >
                {clearing ? "Clearing…" : "Clear alarm"}
              </button>
            ) : null}
            <button type="button" className="bis-btn bis-btn-secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
