import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import TrafficLight, { Traffic } from "./TrafficLight";

type Alert = {
  id?: string;
  severity: string;
  title: string;
  detail?: string;
  source?: string;
  code?: string;
};

type FamilyNode = {
  family: string;
  label: string;
  worst: string;
  traffic: Traffic;
  count: number;
  faults: Alert[];
};

type FaultsStatus = {
  status: "ok" | "warning" | "critical";
  traffic: Traffic;
  check_engine: boolean;
  alert_count: number;
  families: FamilyNode[];
};

type BuildingStatus = {
  traffic: Traffic;
  model_score?: number;
  model_summary?: string;
};

export default function BuildingCheckEngine() {
  const [faults, setFaults] = useState<FaultsStatus | null>(null);
  const [building, setBuilding] = useState<BuildingStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<FaultsStatus>("/api/faults/status").then(setFaults).catch((e) => setError(String(e)));
    apiFetch<BuildingStatus>("/api/building/status").then(setBuilding).catch(() => undefined);
  }, []);

  if (error) {
    return (
      <div className="panel check-engine">
        <div className="check-engine-header">
          <TrafficLight traffic="green" />
          <div>
            <h3>Building status</h3>
            <p className="muted">Could not load status: {error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!faults) {
    return (
      <div className="panel check-engine">
        <p className="muted">Loading building check-engine status…</p>
      </div>
    );
  }

  const traffic = faults.traffic;
  const headline =
    faults.status === "ok"
      ? "All clear — no open building faults"
      : `${faults.alert_count} issue${faults.alert_count === 1 ? "" : "s"} need attention`;
  const statusClass =
    traffic === "red" ? "check-engine-critical" : traffic === "yellow" ? "check-engine-warning" : "check-engine-ok";

  return (
    <div className={`panel check-engine ${statusClass}`}>
      <div className="check-engine-header">
        <TrafficLight traffic={traffic} />
        <div>
          <h3>{headline}</h3>
          {building?.model_summary ? <p className="muted">{building.model_summary}</p> : null}
          {typeof building?.model_score === "number" ? (
            <p className="muted">Data model score: {building.model_score}/100</p>
          ) : null}
          <p className="muted">
            Fixed fault codes only — browse the{" "}
            <Link to="/faults">equipment fault catalog</Link>. The AI agent maps faults to these codes
            and cannot invent new ones.
          </p>
        </div>
      </div>

      {faults.families.length ? (
        <div className="fault-tree">
          {faults.families.map((fam) => (
            <details key={fam.family} className="fault-family" open={fam.worst === "critical"}>
              <summary>
                <span className={`status-dot dot-${fam.traffic}`} />
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
      ) : (
        <p className="muted">
          No open faults. Import a BRICK model under <Link to="/data-model">Data Model</Link>, save
          Python rules tagged with a fault code in <Link to="/rule-lab">Rule Lab</Link>, and the
          scheduled FDD run will light this board.
        </p>
      )}
    </div>
  );
}
