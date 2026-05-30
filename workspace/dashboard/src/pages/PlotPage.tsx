import { useCallback, useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import PageHeader from "../components/PageHeader";
import { TabDebugPanel } from "../components/TabDebugPanel";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type SiteRow = { site_id: string; name: string };

export default function PlotPage() {
  const chartRef = useRef<HTMLDivElement>(null);
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [siteId, setSiteId] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [hours, setHours] = useState(24);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    apiFetch<{ sites: SiteRow[] }>("/api/timeseries/sites")
      .then((res) => {
        setSites(res.sites ?? []);
        if (res.sites?.length) setSiteId(res.sites[0].site_id);
      })
      .catch((e) => setError(formatApiError(e)));
  }, []);

  const loadSeries = useCallback(async (sid: string) => {
    if (!sid) return;
    const res = await apiFetch<{ columns: string[]; labels: Record<string, string> }>(
      `/api/timeseries/series?site_id=${encodeURIComponent(sid)}`,
    );
    setColumns(res.columns ?? []);
    setLabels(res.labels ?? {});
    setSelected(new Set((res.columns ?? []).slice(0, 3)));
  }, []);

  useEffect(() => {
    if (siteId) loadSeries(siteId).catch((e) => setError(formatApiError(e)));
  }, [siteId, loadSeries]);

  async function refreshChart() {
    if (!siteId || !selected.size || !chartRef.current) return;
    setLoading(true);
    setError("");
    try {
      const cols = [...selected].join(",");
      const res = await apiFetch<{
        timestamps: string[];
        series: Record<string, (number | null)[]>;
      }>(`/api/timeseries/plot?site_id=${encodeURIComponent(siteId)}&columns=${encodeURIComponent(cols)}&hours=${hours}`);
      const traces = Object.entries(res.series ?? {}).map(([col, vals]) => ({
        x: res.timestamps,
        y: vals,
        type: "scatter" as const,
        mode: "lines" as const,
        name: labels[col] || col,
        connectgaps: true,
      }));
      await Plotly.react(
        chartRef.current,
        traces,
        {
          title: `Feather store · ${siteId} · ${hours}h`,
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { color: "#c9d1d9" },
          xaxis: { title: "Time" },
          yaxis: { title: "Value" },
          margin: { t: 48, r: 24, b: 48, l: 56 },
          legend: { orientation: "h" as const, y: 1.12 },
        },
        { responsive: true, displayModeBar: true },
      );
      setStatus(`Plotted ${traces.length} series from feather store.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (selected.size && siteId) void refreshChart();
  }, [siteId, hours]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleColumn(col: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(col)) next.delete(col);
      else next.add(col);
      return next;
    });
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Trend plot"
        subtitle="Live BACnet / feather timeseries — same Plotly pattern as the cloud pipeline dashboard."
      />
      <TabDebugPanel tab="plot" />

      <div className="panel">
        <div className="form-row">
          <div className="field">
            <label className="field-label" htmlFor="plot-site">
              Site
            </label>
            <select id="plot-site" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
              {sites.map((s) => (
                <option key={s.site_id} value={s.site_id}>
                  {s.name || s.site_id}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="plot-hours">
              History
            </label>
            <select id="plot-hours" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
              <option value={6}>6 h</option>
              <option value={24}>24 h</option>
              <option value={72}>3 d</option>
              <option value={168}>7 d</option>
            </select>
          </div>
          <div className="form-row-actions">
            <button type="button" disabled={loading || !selected.size} onClick={() => void refreshChart()}>
              {loading ? "Loading…" : "Refresh chart"}
            </button>
          </div>
        </div>
      </div>

      <div className="plot-series-picker panel">
        <h3 className="panel-title">Series</h3>
        {columns.length ? (
          <div className="plot-series-chips">
            {columns.map((col) => (
              <button
                key={col}
                type="button"
                className={selected.has(col) ? "chip chip-on" : "chip chip-off"}
                onClick={() => toggleColumn(col)}
              >
                {labels[col] || col}
              </button>
            ))}
          </div>
        ) : (
          <p className="muted">No numeric columns in feather store for this site — enable BACnet polling first.</p>
        )}
      </div>

      <div className="panel">
        <div ref={chartRef} className="plot-chart" />
      </div>
      {status ? <p className="ok">{status}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </div>
  );
}
