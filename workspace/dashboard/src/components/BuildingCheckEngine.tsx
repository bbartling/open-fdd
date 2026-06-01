import { Link } from "react-router-dom";
import TrafficLight from "./TrafficLight";
import { useDashboardStream, type FaultAlert, type FaultAnalytics } from "../lib/dashboardStream";

function FaultAnalyticsBlock({ a }: { a: FaultAnalytics }) {
  const rows: { label: string; value: string }[] = [];
  if (a.fault_samples != null && a.total_samples != null) {
    rows.push({ label: "Samples", value: `${a.fault_samples} / ${a.total_samples} flagged` });
  }
  if (a.avg_value_fault != null) {
    const unit = a.value_unit || "";
    const band =
      a.bounds_low != null && a.bounds_high != null
        ? ` (band ${a.bounds_low}–${a.bounds_high}${unit})`
        : "";
    rows.push({ label: "Avg while fault", value: `${a.avg_value_fault}${unit}${band}` });
  }
  if (a.min_value_fault != null && a.max_value_fault != null) {
    rows.push({
      label: "Range while fault",
      value: `${a.min_value_fault}–${a.max_value_fault}${a.value_unit || ""}`,
    });
  }
  const dur = a.estimated_fault_duration_label || a.fault_span_label;
  if (dur) {
    rows.push({ label: "Duration in lookback", value: dur });
  }
  if (a.sample_period_sec != null) {
    rows.push({ label: "Sample period", value: `~${a.sample_period_sec} s` });
  }
  if (a.value_columns?.length) {
    rows.push({ label: "Sensor columns", value: a.value_columns.join(", ") });
  }
  if (!rows.length) return null;
  return (
    <dl className="fault-analytics">
      {rows.map((r) => (
        <div key={r.label} className="fault-analytics-row">
          <dt>{r.label}</dt>
          <dd>{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function FaultRow({ f }: { f: FaultAlert }) {
  return (
    <li className={`alert-${f.severity}`}>
      {f.code ? <span className="badge code-badge">{f.code}</span> : null}
      <strong>{f.title}</strong>
      {f.analytics ? <FaultAnalyticsBlock a={f.analytics} /> : null}
      {f.detail ? <p className="fault-detail muted">{f.detail}</p> : null}
      {f.source ? <span className="badge">{f.source}</span> : null}
    </li>
  );
}

export default function BuildingCheckEngine() {
  const { snapshot, error, live } = useDashboardStream();

  if (error && !snapshot) {
    return (
      <div className="panel check-engine check-engine-gray">
        <div className="check-engine-header">
          <TrafficLight traffic="green" />
          <div>
            <h3>Building check-engine</h3>
            <p className="muted">Could not load status: {error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="panel check-engine check-engine-gray">
        <p className="muted">Loading check-engine status…</p>
      </div>
    );
  }

  const faults = snapshot.faults;
  const traffic = faults.traffic;
  const statusClass =
    traffic === "red" ? "check-engine-critical" : traffic === "yellow" ? "check-engine-warning" : "check-engine-ok";

  if (!faults.model_configured && faults.alert_count === 0) {
    return (
      <div className={`panel check-engine ${statusClass}`}>
        <div className="check-engine-header">
          <TrafficLight traffic="green" />
          <div>
            <h3>Building check-engine</h3>
            <p className="muted">No building model configured yet.</p>
            <p className="muted">
              Import a BRICK model under <Link to="/data-model">Data Model</Link> to enable fault detection.
            </p>
          </div>
        </div>
        {live ? <p className="live-badge">Live</p> : null}
      </div>
    );
  }

  const headline =
    faults.status === "ok"
      ? "All clear — no open faults"
      : `${faults.alert_count} issue${faults.alert_count === 1 ? "" : "s"} need attention`;

  return (
    <div className={`panel check-engine ${statusClass}`}>
      <div className="check-engine-header">
        <TrafficLight traffic={traffic} />
        <div>
          <h3>{headline}</h3>
        </div>
      </div>
      {live ? <p className="live-badge">Live</p> : null}

      {faults.families.length ? (
        <div className="fault-tree">
          {faults.families.map((fam) => (
            <details key={fam.family} className="fault-family" open={fam.worst === "critical"}>
              <summary>
                <span className={`fault-tree-dot dot-${fam.traffic}`} />
                <strong>{fam.label}</strong>
                <span className="badge">{fam.count}</span>
              </summary>
              <ul className="check-engine-list">
                {fam.faults.map((f) => (
                  <FaultRow key={f.id || f.title} f={f} />
                ))}
              </ul>
            </details>
          ))}
        </div>
      ) : null}
    </div>
  );
}
