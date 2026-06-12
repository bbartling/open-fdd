import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { KpiCard, AnalyticsDonutChart, AnalyticsBarChart, SeverityBadge } from "../components/analytics/AnalyticsCharts";
import { fetchAnalyticsOverview, type OverviewResponse } from "../lib/analytics-api";
import { useTheme } from "../contexts/theme-context";

export default function AnalyticsOverviewPage() {
  const { theme } = useTheme();
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAnalyticsOverview()
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const kpis = data?.kpis;

  return (
    <div className="analytics-page">
      <PageHeader title="Overview" subtitle="Engineering analytics — faults, health, and KPIs" />
      {error ? <div className="panel error-panel">{error}</div> : null}
      <div className="kpi-grid">
        <KpiCard label="Active faults" value={loading ? "…" : (kpis?.active_faults ?? "—")} />
        <KpiCard label="Critical / high" value={kpis?.critical_high_faults ?? "—"} />
        <KpiCard label="Total fault hours" value={kpis?.total_fault_hours ?? "—"} />
        <KpiCard label="Equipment w/ faults" value={kpis?.equipment_with_faults ?? "—"} />
        <KpiCard label="Model warnings" value={kpis?.model_warnings ?? "—"} />
        <KpiCard label="Validation" value={kpis?.validation_status ?? "—"} />
      </div>
      <div className="analytics-grid">
        <AnalyticsDonutChart
          title="Fault hours by severity"
          labels={(data?.faults_by_severity ?? []).map((r) => r.group)}
          values={(data?.faults_by_severity ?? []).map((r) => r.elapsed_hours)}
          theme={theme}
          loading={loading}
        />
        <AnalyticsBarChart
          title="Fault hours by equipment"
          labels={(data?.fault_hours_by_equipment ?? []).slice(0, 10).map((r) => r.group)}
          values={(data?.fault_hours_by_equipment ?? []).slice(0, 10).map((r) => r.elapsed_hours)}
          theme={theme}
          loading={loading}
        />
        <AnalyticsBarChart
          title="Fault hours by rule / code"
          labels={(data?.fault_hours_by_code ?? []).slice(0, 10).map((r) => r.group)}
          values={(data?.fault_hours_by_code ?? []).slice(0, 10).map((r) => r.elapsed_hours)}
          theme={theme}
          loading={loading}
        />
      </div>
      <section className="panel">
        <h2>Top active faults</h2>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : !(data?.top_faults ?? []).length ? (
          <p className="muted">No active faults in current snapshot.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Equipment</th>
                <th>Type</th>
                <th>Fault</th>
                <th>Severity</th>
                <th>Hours</th>
                <th>Samples</th>
                <th>Next step</th>
              </tr>
            </thead>
            <tbody>
              {(data?.top_faults ?? []).map((row, i) => (
                <tr key={`${row.equipment}-${row.fault_name}-${i}`}>
                  <td>{row.equipment}</td>
                  <td>{row.equipment_type || "—"}</td>
                  <td>{row.fault_name}</td>
                  <td>
                    <SeverityBadge severity={row.severity} />
                  </td>
                  <td>{row.elapsed_fault_hours}</td>
                  <td>
                    {row.samples_flagged}/{row.samples_evaluated}
                  </td>
                  <td className="muted">{row.recommended_next_step}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
