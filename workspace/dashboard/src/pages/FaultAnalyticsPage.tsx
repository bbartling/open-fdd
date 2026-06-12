import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { AnalyticsBarChart, SeverityBadge } from "../components/analytics/AnalyticsCharts";
import { fetchFaultAnalytics } from "../lib/analytics-api";
import { useTheme } from "../contexts/theme-context";

const RANGES = [
  { label: "Last 2 hours", hours: 2 },
  { label: "Last 24 hours", hours: 24 },
  { label: "Last 7 days", hours: 168 },
];

export default function FaultAnalyticsPage() {
  const { theme } = useTheme();
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchFaultAnalytics(hours)
      .then(setData)
      .finally(() => setLoading(false));
  }, [hours]);

  const byEq = (data?.fault_hours_by_equipment as { group: string; elapsed_hours: number }[]) ?? [];
  const byCode = (data?.fault_hours_by_code as { group: string; elapsed_hours: number }[]) ?? [];
  const bySev = (data?.fault_hours_by_severity as { group: string; elapsed_hours: number }[]) ?? [];
  const faults = (data?.faults as Record<string, unknown>[]) ?? [];

  return (
    <div className="analytics-page">
      <PageHeader title="Fault analytics" subtitle="Worst equipment and rules by elapsed fault hours" />
      <div className="toolbar-row">
        {RANGES.map((r) => (
          <button
            key={r.hours}
            type="button"
            className={`btn-chip${hours === r.hours ? " active" : ""}`}
            onClick={() => setHours(r.hours)}
          >
            {r.label}
          </button>
        ))}
      </div>
      <div className="analytics-grid">
        <AnalyticsBarChart
          title="Fault hours by severity"
          labels={bySev.map((r) => r.group)}
          values={bySev.map((r) => r.elapsed_hours)}
          theme={theme}
          loading={loading}
        />
        <AnalyticsBarChart
          title="Top equipment by fault hours"
          labels={byEq.slice(0, 10).map((r) => r.group)}
          values={byEq.slice(0, 10).map((r) => r.elapsed_hours)}
          theme={theme}
          loading={loading}
        />
        <AnalyticsBarChart
          title="Fault hours by code"
          labels={byCode.slice(0, 10).map((r) => r.group)}
          values={byCode.slice(0, 10).map((r) => r.elapsed_hours)}
          theme={theme}
          loading={loading}
        />
      </div>
      <section className="panel">
        <h2>Fault detail</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Equipment</th>
              <th>Type</th>
              <th>Fault</th>
              <th>Severity</th>
              <th>Hours</th>
              <th>Samples</th>
            </tr>
          </thead>
          <tbody>
            {faults.map((row, i) => (
              <tr key={i}>
                <td>{String(row.equipment ?? "—")}</td>
                <td>{String(row.equipment_type ?? "—")}</td>
                <td>{String(row.fault_name ?? row.fault_code ?? "—")}</td>
                <td>
                  <SeverityBadge severity={String(row.severity ?? "warning")} />
                </td>
                <td>{String(row.elapsed_hours ?? "—")}</td>
                <td>
                  {String(row.samples_flagged ?? "—")}/{String(row.samples_evaluated ?? "—")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
