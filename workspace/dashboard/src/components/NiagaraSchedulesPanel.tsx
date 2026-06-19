import { useMemo } from "react";
import type { NiagaraSchedule } from "../lib/niagara-api";

type Props = {
  schedules: NiagaraSchedule[];
  loading?: boolean;
  onRefresh: (read: boolean) => void;
  scheduleBase: string;
  onScheduleBaseChange: (value: string) => void;
};

export default function NiagaraSchedulesPanel({
  schedules,
  loading,
  onRefresh,
  scheduleBase,
  onScheduleBaseChange,
}: Props) {
  const sorted = useMemo(
    () => [...schedules].sort((a, b) => (a.ord || a.name).localeCompare(b.ord || b.name)),
    [schedules],
  );

  return (
    <div className="niagara-schedules-panel">
      <p className="muted" style={{ marginTop: 0 }}>
        Discover Niagara schedules (baskStream <code>schedules</code> command). Default root is{" "}
        <code>slot:/Schedules</code> — adjust for your station layout.
      </p>
      <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        <label className="field-inline" style={{ flex: "1 1 18rem" }}>
          Schedules folder ORD
          <input
            value={scheduleBase}
            onChange={(e) => onScheduleBaseChange(e.target.value)}
            placeholder="slot:/Schedules"
          />
        </label>
        <button type="button" className="secondary-btn" disabled={loading} onClick={() => onRefresh(false)}>
          List schedules
        </button>
        <button type="button" className="secondary-btn" disabled={loading} onClick={() => onRefresh(true)}>
          List + read values
        </button>
      </div>
      {sorted.length ? (
        <div className="niagara-override-table-wrap bis-override-table-wrap">
          <table className="data-table niagara-schedules-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>ORD</th>
                <th>Type</th>
                <th>Status</th>
                <th>Schedule</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.ord}>
                  <td>{row.name || "—"}</td>
                  <td>
                    <code className="mono">{row.ord}</code>
                  </td>
                  <td className="muted">{row.type || "—"}</td>
                  <td>{row.status || "—"}</td>
                  <td className="mono">
                    {row.schedule_error ? (
                      <span className="error">{row.schedule_error}</span>
                    ) : row.schedule != null ? (
                      typeof row.schedule === "string" ? row.schedule : JSON.stringify(row.schedule).slice(0, 120)
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No schedules loaded — connect to the station and list schedules.</p>
      )}
    </div>
  );
}
