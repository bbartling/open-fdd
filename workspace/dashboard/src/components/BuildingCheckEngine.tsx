import { Link } from "react-router-dom";
import TrafficLight from "./TrafficLight";
import { useDashboardStream } from "../lib/dashboardStream";

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
                  <li key={f.id || f.title} className={`alert-${f.severity}`}>
                    {f.code ? <span className="badge code-badge">{f.code}</span> : null}
                    <strong>{f.title}</strong>
                    {f.detail ? <span className="muted"> — {f.detail}</span> : null}
                    {f.source ? <span className="badge">{f.source}</span> : null}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      ) : null}
    </div>
  );
}
