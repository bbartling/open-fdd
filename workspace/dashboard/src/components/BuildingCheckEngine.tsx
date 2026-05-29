import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";

type Alert = {
  id?: string;
  severity: string;
  title: string;
  detail?: string;
  source?: string;
};

type BuildingStatus = {
  status: "ok" | "warning" | "critical";
  check_engine: boolean;
  model_score?: number;
  model_summary?: string;
  alert_count: number;
  alerts: Alert[];
};

export default function BuildingCheckEngine() {
  const [data, setData] = useState<BuildingStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<BuildingStatus>("/api/building/status")
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="panel check-engine check-engine-gray">
        <div className="check-engine-header">
          <span className="check-engine-icon">⬤</span>
          <div>
            <h3>Building status</h3>
            <p className="muted">Could not load status: {error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="panel check-engine check-engine-gray">
        <p className="muted">Loading building status…</p>
      </div>
    );
  }

  const statusClass =
    data.status === "critical"
      ? "check-engine-critical"
      : data.status === "warning"
        ? "check-engine-warning"
        : "check-engine-ok";

  const icon = data.check_engine ? "⚠" : "✓";
  const headline =
    data.status === "ok"
      ? "All clear — no open building issues"
      : `${data.alert_count} issue${data.alert_count === 1 ? "" : "s"} need attention`;

  return (
    <div className={`panel check-engine ${statusClass}`}>
      <div className="check-engine-header">
        <span className="check-engine-icon">{icon}</span>
        <div>
          <h3>{headline}</h3>
          {data.model_summary ? <p className="muted">{data.model_summary}</p> : null}
          {typeof data.model_score === "number" ? (
            <p className="muted">Data model score: {data.model_score}/100</p>
          ) : null}
        </div>
      </div>
      {data.alerts.length ? (
        <ul className="check-engine-list">
          {data.alerts.map((alert) => (
            <li key={alert.id || alert.title} className={`alert-${alert.severity}`}>
              <strong>{alert.title}</strong>
              {alert.detail ? <span className="muted"> — {alert.detail}</span> : null}
              {alert.source ? <span className="badge">{alert.source}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">
          Import a BRICK model under <Link to="/data-model">Data Model</Link>, then run Python rules in{" "}
          <Link to="/rule-lab">Rule Lab</Link>. The AI agent can update alerts via{" "}
          <code>PUT /api/building/alerts</code>.
        </p>
      )}
    </div>
  );
}
