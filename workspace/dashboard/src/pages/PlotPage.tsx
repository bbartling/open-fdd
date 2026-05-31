import { useCallback, useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import PageHeader from "../components/PageHeader";
import { TabDebugPanel } from "../components/TabDebugPanel";
import { useTheme } from "../contexts/theme-context";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { buildPlotTraces, type PlotReadingsResponse } from "../lib/plot-chart";

type SiteRow = { site_id: string; name: string };

export default function PlotPage() {
  const chartRef = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [siteId, setSiteId] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [kinds, setKinds] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [enabledFaults, setEnabledFaults] = useState<Set<string>>(new Set());
  const [faultPanels, setFaultPanels] = useState<PlotReadingsResponse["fault_panels"]>([]);
  const [plotData, setPlotData] = useState<PlotReadingsResponse | null>(null);
  const [hours, setHours] = useState(24);
  const [showBounds, setShowBounds] = useState(true);
  const [includeFaults, setIncludeFaults] = useState(true);
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

  const renderChart = useCallback(
    async (data: PlotReadingsResponse) => {
      if (!chartRef.current) return;
      const { traces, layout } = buildPlotTraces(data, {
        enabledFaults,
        showBounds,
        theme,
      });
      await Plotly.react(
        chartRef.current,
        traces as Plotly.Data[],
        {
          ...layout,
          title: `Feather · ${data.site_id ?? siteId} · ${data.hours ?? hours}h`,
          height: 460,
        },
        { responsive: true, displayModeBar: true },
      );
    },
    [enabledFaults, showBounds, theme, siteId, hours],
  );

  useEffect(() => {
    if (plotData) void renderChart(plotData);
  }, [plotData, renderChart]);

  async function refreshChart() {
    if (!siteId || !selected.size) return;
    setLoading(true);
    setError("");
    try {
      const cols = [...selected].join(",");
      const res = await apiFetch<PlotReadingsResponse>(
        `/api/timeseries/readings?site_id=${encodeURIComponent(siteId)}&columns=${encodeURIComponent(cols)}&hours=${hours}&include_faults=${includeFaults}`,
      );
      setKinds(res.series_kinds ?? {});
      setFaultPanels(res.fault_panels ?? []);
      setEnabledFaults(new Set((res.fault_panels ?? []).map((p) => p.key)));
      setPlotData(res);
      const faultCount = Object.values(res.fault_totals ?? {}).reduce((a, b) => a + b, 0);
      const trunc = res.chart_truncated ? ` (downsampled ×${res.chart_stride})` : "";
      setStatus(
        `Plotted ${Object.keys(res.series ?? {}).length} series, ${res.fault_panels?.length ?? 0} fault lanes, ${faultCount} flag samples${trunc}.`,
      );
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (selected.size && siteId) void refreshChart();
    return () => {
      if (chartRef.current) Plotly.purge(chartRef.current);
    };
  }, [siteId, hours, includeFaults, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleColumn(col: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(col)) next.delete(col);
      else next.add(col);
      return next;
    });
  }

  function toggleFault(key: string) {
    setEnabledFaults((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function columnKindLabel(col: string): string {
    const k = kinds[col];
    if (k === "humidity") return " %RH";
    if (k === "temperature") return " °F";
    return "";
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="Trend plot"
        subtitle="Feather telemetry with FDD fault overlays — temperature left, humidity right, fault lanes on a boolean axis."
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
              <option value={1}>1 h</option>
              <option value={6}>6 h</option>
              <option value={24}>24 h</option>
              <option value={72}>3 d</option>
              <option value={168}>7 d</option>
            </select>
          </div>
          <label className="checkbox-inline">
            <input type="checkbox" checked={includeFaults} onChange={(e) => setIncludeFaults(e.target.checked)} />
            Evaluate FDD rules
          </label>
          <label className="checkbox-inline">
            <input type="checkbox" checked={showBounds} onChange={(e) => setShowBounds(e.target.checked)} />
            OOB guide lines
          </label>
          <div className="form-row-actions">
            <button type="button" disabled={loading || !selected.size} onClick={() => void refreshChart()}>
              {loading ? "Loading…" : "Refresh chart"}
            </button>
          </div>
        </div>
      </div>

      <div className="plot-series-picker panel">
        <h3 className="panel-title">Telemetry</h3>
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
                <span className="chip-kind">{columnKindLabel(col)}</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="muted">No numeric columns in feather store — enable BACnet polling first.</p>
        )}
      </div>

      {faultPanels?.length ? (
        <div className="plot-series-picker panel">
          <h3 className="panel-title">Fault overlays</h3>
          <div className="plot-series-chips">
            {faultPanels.map((p) => (
              <button
                key={p.key}
                type="button"
                className={enabledFaults.has(p.key) ? "chip chip-on chip-fault" : "chip chip-off chip-fault"}
                style={{ borderColor: p.color }}
                onClick={() => toggleFault(p.key)}
              >
                <span className="fault-swatch" style={{ background: p.color }} />
                {p.title}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="panel plot-chart-panel">
        <div ref={chartRef} className="plot-chart" />
      </div>
      {status ? <p className="ok">{status}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </div>
  );
}
