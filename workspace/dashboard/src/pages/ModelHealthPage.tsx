import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { fetchModelHealth } from "../lib/analytics-api";

export default function ModelHealthPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchModelHealth()
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  const counts = (data?.counts as Record<string, unknown>) ?? {};
  const issues = (data?.issues as Record<string, unknown>[]) ?? [];

  return (
    <div className="analytics-page">
      <PageHeader title="BACnet / model health" subtitle="Data model integrity and polling health" />
      {loading ? <p className="muted">Loading…</p> : null}
      <div className="kpi-grid">
        {(["device_count", "point_count", "equipment_count", "stale_point_count", "issue_count"] as const).map(
          (key) => (
            <div key={key} className="kpi-card">
              <div className="kpi-label">{key.replace(/_/g, " ")}</div>
              <div className="kpi-value">{String(counts[key] ?? "—")}</div>
            </div>
          ),
        )}
      </div>
      <section className="panel">
        <h2>Model warnings</h2>
        {!issues.length ? (
          <p className="muted">No model health issues.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((row, i) => (
                <tr key={i}>
                  <td>{String(row.title ?? "—")}</td>
                  <td className="muted">{String(row.detail ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
