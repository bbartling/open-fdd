import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { getPlotlyThemeLayout, type ChartTheme } from "../../lib/plotly-theme";

type BarChartProps = {
  title: string;
  labels: string[];
  values: number[];
  theme: ChartTheme;
  yLabel?: string;
  loading?: boolean;
  emptyMessage?: string;
};

export function AnalyticsBarChart({
  title,
  labels,
  values,
  theme,
  yLabel = "Hours (est.)",
  loading,
  emptyMessage = "No data for selected window",
}: BarChartProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || loading) return;
    if (!labels.length) {
      Plotly.purge(el);
      return;
    }
    const themed = getPlotlyThemeLayout(theme);
    Plotly.react(
      el,
      [
        {
          type: "bar",
          x: labels,
          y: values,
          marker: { color: themed.colorway[0] },
          hovertemplate: "%{x}<br>%{y:.2f} h<extra></extra>",
        },
      ],
      {
        ...themed,
        title: { text: title, font: { color: themed.font.color, size: 14 } },
        yaxis: { ...themed.yaxis, title: yLabel },
        margin: { ...themed.margin, b: 80 },
      },
      { responsive: true, displayModeBar: false },
    );
    return () => {
      Plotly.purge(el);
    };
  }, [title, labels, values, theme, yLabel, loading]);

  if (loading) return <div className="chart-card chart-empty">Loading…</div>;
  if (!labels.length) return <div className="chart-card chart-empty">{emptyMessage}</div>;
  return <div className="chart-card" ref={ref} />;
}

type DonutProps = {
  title: string;
  labels: string[];
  values: number[];
  theme: ChartTheme;
  loading?: boolean;
};

export function AnalyticsDonutChart({ title, labels, values, theme, loading }: DonutProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || loading) return;
    if (!labels.length) {
      Plotly.purge(el);
      return;
    }
    const themed = getPlotlyThemeLayout(theme);
    Plotly.react(
      el,
      [
        {
          type: "pie",
          labels,
          values,
          hole: 0.45,
          textinfo: "label+percent",
          textfont: { color: themed.font.color, size: 11 },
          hovertemplate: "%{label}<br>%{value:.2f} h<extra></extra>",
        },
      ],
      {
        ...themed,
        title: { text: title, font: { color: themed.font.color, size: 14 } },
        showlegend: true,
        legend: { ...themed.legend, orientation: "v", y: 0.5 },
      },
      { responsive: true, displayModeBar: false },
    );
    return () => Plotly.purge(el);
  }, [title, labels, values, theme, loading]);

  if (loading) return <div className="chart-card chart-empty">Loading…</div>;
  if (!labels.length) return <div className="chart-card chart-empty">No severity data</div>;
  return <div className="chart-card" ref={ref} />;
}

export function KpiCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint ? <div className="kpi-hint">{hint}</div> : null}
    </div>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase();
  const cls = s === "critical" ? "sev-critical" : s === "warning" ? "sev-warning" : "sev-info";
  return <span className={`severity-badge ${cls}`}>{severity}</span>;
}
