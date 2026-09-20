import { useCallback, useEffect, useState } from "react";
import {
  postMvChangePoint,
  type AnalyticsEnvelope,
} from "../api/analyticsApi";
import { Button, DataTable, InlineAlert, Metric } from "./widgets";
import { PlotlyHost } from "./widgets/PlotlyHost";

/** Deterministic demo seed — mirrors scripts/qualification/fixtures/mv_change_point_seed.json */
export const MV_DEMO_SEED = {
  baseline_end: "2023-12",
  dd_kind: "hdd",
  rows: [
    { period: "2023-01", energy: 2100.0, degree_days: 800.0 },
    { period: "2023-02", energy: 1900.0, degree_days: 700.0 },
    { period: "2023-03", energy: 1500.0, degree_days: 500.0 },
    { period: "2023-04", energy: 1100.0, degree_days: 300.0 },
    { period: "2023-05", energy: 700.0, degree_days: 100.0 },
    { period: "2023-06", energy: 600.0, degree_days: 50.0 },
    { period: "2023-07", energy: 540.0, degree_days: 20.0 },
    { period: "2023-08", energy: 560.0, degree_days: 30.0 },
    { period: "2023-09", energy: 660.0, degree_days: 80.0 },
    { period: "2023-10", energy: 1000.0, degree_days: 250.0 },
    { period: "2023-11", energy: 1400.0, degree_days: 450.0 },
    { period: "2023-12", energy: 2000.0, degree_days: 750.0 },
    { period: "2024-01", energy: 1960.0, degree_days: 780.0 },
    { period: "2024-02", energy: 1780.0, degree_days: 690.0 },
    { period: "2024-03", energy: 1360.0, degree_days: 480.0 },
  ],
} as const;

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function scatterFigure(env: AnalyticsEnvelope | null) {
  if (!env?.points?.length) return null;
  const base = env.points.filter((p) => p.period_kind === "baseline");
  const rep = env.points.filter((p) => p.period_kind === "reporting");
  const traces: Record<string, unknown>[] = [
    {
      type: "scatter",
      mode: "markers",
      name: "Baseline",
      x: base.map((p) => Number(p.x)),
      y: base.map((p) => Number(p.y)),
      text: base.map((p) => String(p.period ?? "")),
    },
    {
      type: "scatter",
      mode: "markers",
      name: "Reporting",
      x: rep.map((p) => Number(p.x)),
      y: rep.map((p) => Number(p.y)),
      text: rep.map((p) => String(p.period ?? "")),
    },
  ];
  const withPred = env.points.filter((p) => p.y_predicted != null);
  if (withPred.length) {
    traces.push({
      type: "scatter",
      mode: "markers",
      name: "Predicted",
      x: withPred.map((p) => Number(p.x)),
      y: withPred.map((p) => Number(p.y_predicted)),
      marker: { symbol: "x" },
      text: withPred.map((p) => String(p.period ?? "")),
    });
  }
  return {
    data: traces,
    layout: {
      title: "M&V — energy vs degree-days (2P OLS twin)",
      xaxis: { title: String(env.coverage?.dd_kind ?? "degree-days") },
      yaxis: { title: "energy" },
      margin: { t: 48, r: 24, b: 48, l: 56 },
    },
  };
}

/**
 * Minimal Metering M&V panel — POST /api/analytics/mv on the shared demo seed.
 * Live campus bill wiring can reuse the same body shape later.
 */
export function MvChangePointPanel() {
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await postMvChangePoint({
        query_version: "mv-change-point-v1",
        series: { ...MV_DEMO_SEED },
      });
      setEnv(next);
    } catch (err) {
      setEnv(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  const cov = env?.coverage ?? null;
  const fit = (cov?.fit as Record<string, unknown> | null) ?? null;
  const figure = scatterFigure(env);
  const tableRows = (env?.rows ?? []).map((r) => ({
    period: String(r.period ?? ""),
    kind: String(r.period_kind ?? ""),
    energy: r.energy,
    dd: r.degree_days,
    predicted: r.predicted ?? "—",
    savings: r.savings ?? "—",
  }));

  return (
    <div className="page-stack" data-testid="mv-change-point-panel">
      <InlineAlert id="mv-scope" variant="info" testId="mv-scope">
        Thin IPMVP Option C monthly twin (2P OLS). Demo seed only — not
        investment-grade Camber. Live utilities stay on the Utilities radio.
      </InlineAlert>

      <div className="oracle-sidebar__btn-row">
        <Button
          id="mv-rerun"
          label={loading ? "Running…" : "Re-run demo seed"}
          onClick={() => void run()}
          disabled={loading}
          testId="mv-rerun"
        />
        <Metric
          id="mv-savings"
          label="Reporting savings"
          value={
            cov?.savings_reporting_total != null
              ? String(cov.savings_reporting_total)
              : "—"
          }
          description="predicted − actual"
          loading={loading}
          testId="mv-savings"
        />
        <Metric
          id="mv-slope"
          label="Slope"
          value={fit?.slope != null ? String(fit.slope) : "—"}
          loading={loading}
          testId="mv-slope"
        />
        <Metric
          id="mv-r2"
          label="R²"
          value={fit?.r2 != null ? String(fit.r2) : "—"}
          loading={loading}
          testId="mv-r2"
        />
      </div>

      {error ? (
        <InlineAlert id="mv-error" variant="error" testId="mv-error">
          {error}
        </InlineAlert>
      ) : null}

      {env?.warnings?.length ? (
        <InlineAlert id="mv-warnings" variant="warning" testId="mv-warnings">
          {env.warnings.slice(0, 4).join(" · ")}
        </InlineAlert>
      ) : null}

      <PlotlyHost
        id="mv-scatter"
        label="Baseline vs reporting"
        figure={figure}
        loading={loading}
        height={360}
        testId="mv-chart-scatter"
      />

      <DataTable
        id="mv-monthly"
        label="Monthly M&V rows"
        columns={[
          { key: "period", header: "Period" },
          { key: "kind", header: "Kind" },
          { key: "energy", header: "Energy" },
          { key: "dd", header: "DD" },
          { key: "predicted", header: "Predicted" },
          { key: "savings", header: "Savings" },
        ]}
        rows={tableRows}
        loading={loading}
        testId="mv-table"
      />
    </div>
  );
}
