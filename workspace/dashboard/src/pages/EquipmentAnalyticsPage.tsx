import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { fetchFaultAnalytics } from "../lib/analytics-api";

export default function EquipmentAnalyticsPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    fetchFaultAnalytics(168).then(setData);
  }, []);

  const faults = ((data?.faults as Record<string, unknown>[]) ?? []).filter((r) => {
    const t = String(r.equipment_type ?? "").toUpperCase();
    return t.includes("AHU") || t.includes("VAV") || t.includes("RTU");
  });

  const ahu = faults.filter((r) => String(r.equipment_type ?? "").toUpperCase().includes("AHU"));
  const vav = faults.filter((r) => String(r.equipment_type ?? "").toUpperCase().includes("VAV"));

  return (
    <div className="analytics-page">
      <PageHeader
        title="Equipment analytics"
        subtitle="AHU and VAV fault hours — open Trend plot for time-series when historian data exists"
      />
      <section className="panel">
        <h2>AHU summary</h2>
        {!ahu.length ? (
          <p className="muted">No AHU faults in lookback. Use Trend plot for SAT / static / fan charts.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Equipment</th>
                <th>Fault</th>
                <th>Hours</th>
              </tr>
            </thead>
            <tbody>
              {ahu.map((r, i) => (
                <tr key={i}>
                  <td>{String(r.equipment)}</td>
                  <td>{String(r.fault_name ?? r.fault_code)}</td>
                  <td>{String(r.elapsed_hours)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="panel">
        <h2>VAV zones — worst by comfort fault hours</h2>
        {!vav.length ? (
          <p className="muted">No VAV fault rows. Zone comfort metrics appear when rules flag zones.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Zone</th>
                <th>Fault</th>
                <th>Hours</th>
              </tr>
            </thead>
            <tbody>
              {vav
                .sort((a, b) => Number(b.elapsed_hours ?? 0) - Number(a.elapsed_hours ?? 0))
                .slice(0, 15)
                .map((r, i) => (
                  <tr key={i}>
                    <td>{String(r.equipment)}</td>
                    <td>{String(r.fault_name ?? r.fault_code)}</td>
                    <td>{String(r.elapsed_hours)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
