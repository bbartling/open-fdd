import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import FddRulePinMenu, { type RulePinTarget } from "../components/FddRulePinMenu";
import Plotly from "plotly.js-dist-min";
import PageHeader from "../components/PageHeader";
import { TabDebugPanel } from "../components/TabDebugPanel";
import TelemetryScopePicker from "../components/TelemetryScopePicker";
import { useTheme } from "../contexts/theme-context";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { buildPlotTraces, type PlotReadingsResponse } from "../lib/plot-chart";
import {
  defaultKeysForEquipment,
  useTelemetryCatalog,
  type SeriesOption,
} from "../lib/telemetryCatalog";

const PLOT_LOG = (...args: unknown[]) => {
  if (import.meta.env.DEV || localStorage.getItem("ofdd_debug_plot") === "1") {
    console.debug("[plot]", ...args);
  }
};

const FETCH_TIMEOUT_MS = 120_000;

export default function PlotPage() {
  const chartRef = useRef<HTMLDivElement>(null);
  const fetchGen = useRef(0);
  const debounceRef = useRef<number | null>(null);
  const { theme } = useTheme();
  const catalog = useTelemetryCatalog();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const site = params.get("site");
    const device = params.get("device");
    if (site) catalog.setSiteId(site);
    if (device) catalog.setEquipmentId(device);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const {
    sites,
    siteId,
    setSiteId,
    equipmentGroups,
    equipmentId,
    setEquipmentId,
    kinds,
    loading: catalogLoading,
    error: catalogError,
    visibleOptions,
    activeGroup,
  } = catalog;

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [enabledFaults, setEnabledFaults] = useState<Set<string>>(new Set());
  const [faultPanels, setFaultPanels] = useState<PlotReadingsResponse["fault_panels"]>([]);
  const [plotData, setPlotData] = useState<PlotReadingsResponse | null>(null);
  const [hours, setHours] = useState(24);
  const [showBounds, setShowBounds] = useState(true);
  const [includeFaults, setIncludeFaults] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [chartLoading, setChartLoading] = useState(false);
  const [pinMenu, setPinMenu] = useState<(RulePinTarget & { x: number; y: number }) | null>(null);
  const [pinStatus, setPinStatus] = useState("");

  const optionByKey = useMemo(() => {
    const m = new Map<string, SeriesOption>();
    for (const o of catalog.seriesOptions) m.set(o.key, o);
    return m;
  }, [catalog.seriesOptions]);

  useEffect(() => {
    if (!equipmentId || catalog.seriesOptions.length === 0) return;
    const keys = defaultKeysForEquipment(catalog.seriesOptions, equipmentId, 6);
    PLOT_LOG("default selection", equipmentId, keys);
    setSelected(new Set(keys));
  }, [equipmentId, catalog.seriesOptions.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const renderChart = useCallback(
    async (data: PlotReadingsResponse) => {
      if (!chartRef.current) {
        PLOT_LOG("renderChart: no chart ref");
        return;
      }
      const t0 = performance.now();
      try {
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
        PLOT_LOG("Plotly.react done", `${Math.round(performance.now() - t0)}ms`, traces.length, "traces");
      } catch (e) {
        PLOT_LOG("Plotly.react error", e);
        throw e;
      }
    },
    [enabledFaults, showBounds, theme, siteId, hours],
  );

  useEffect(() => {
    if (plotData) {
      void renderChart(plotData).catch((e) => {
        setError(formatApiError(e));
        PLOT_LOG("render effect error", e);
      });
    }
  }, [plotData, renderChart]);

  const refreshChart = useCallback(async () => {
    if (!siteId || !selected.size) {
      PLOT_LOG("refresh skipped", { siteId, selected: selected.size });
      return;
    }
    const gen = ++fetchGen.current;
    setChartLoading(true);
    setError("");
    const keys = [...selected];
    const cols = [...new Set(keys.map((k) => optionByKey.get(k)?.column ?? k))];
    PLOT_LOG("fetch readings", { siteId, keys: keys.length, cols, hours, includeFaults });
    const t0 = performance.now();
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const qs = new URLSearchParams({
        site_id: siteId,
        columns: keys.join(","),
        hours: String(hours),
        include_faults: String(includeFaults),
      });
      const res = await apiFetch<PlotReadingsResponse>(`/api/timeseries/readings?${qs}`, {
        signal: controller.signal,
      });
      if (gen !== fetchGen.current) {
        PLOT_LOG("stale response ignored", gen);
        return;
      }
      const seriesCount = Object.keys(res.series ?? {}).length;
      PLOT_LOG("readings ok", `${Math.round(performance.now() - t0)}ms`, seriesCount, "series");
      if (seriesCount === 0) {
        setError("No series returned — check feather data or point selection.");
        setPlotData(null);
        return;
      }
      setFaultPanels(res.fault_panels ?? []);
      setEnabledFaults(new Set((res.fault_panels ?? []).map((p) => p.key)));
      setPlotData(res);
      const faultCount = Object.values(res.fault_totals ?? {}).reduce((a, b) => a + b, 0);
      const trunc = res.chart_truncated ? ` (downsampled ×${res.chart_stride})` : "";
      setStatus(
        `Plotted ${seriesCount} series, ${res.fault_panels?.length ?? 0} fault lanes, ${faultCount} flag samples${trunc}.`,
      );
    } catch (e) {
      if (gen !== fetchGen.current) return;
      const msg =
        e instanceof DOMException && e.name === "AbortError"
          ? `Chart request timed out after ${FETCH_TIMEOUT_MS / 1000}s — try fewer points or disable FDD overlays.`
          : formatApiError(e);
      PLOT_LOG("readings error", msg);
      setError(msg);
    } finally {
      window.clearTimeout(timer);
      if (gen === fetchGen.current) setChartLoading(false);
    }
  }, [siteId, selected, hours, includeFaults, optionByKey]);

  useEffect(() => {
    if (!selected.size || !siteId) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      void refreshChart();
    }, 450);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [siteId, hours, includeFaults, selected, refreshChart]);

  useEffect(() => {
    return () => {
      fetchGen.current += 1;
      if (chartRef.current) Plotly.purge(chartRef.current);
    };
  }, []);

  function onEquipmentChange(nextId: string) {
    setEquipmentId(nextId);
    setSelected(new Set(defaultKeysForEquipment(catalog.seriesOptions, nextId, 6)));
  }

  function selectAllVisible() {
    setSelected(new Set(visibleOptions.map((o) => o.key)));
  }

  function clearVisible() {
    setSelected(new Set());
  }

  function toggleKey(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
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

  function seriesKindLabel(opt: SeriesOption): string {
    const k = kinds[opt.column];
    if (k === "humidity") return " %RH";
    if (k === "temperature") return " °F";
    return "";
  }

  const plotLink =
    siteId && equipmentId
      ? `/plot?site=${encodeURIComponent(siteId)}&device=${encodeURIComponent(equipmentId)}`
      : "/plot";

  return (
    <div className="page page-wide">
      <PageHeader
        title="Trend plot"
        subtitle={
          <>
            Feather telemetry with optional FDD overlays. Pick a device, select points, then refresh. Right-click a
            series chip to pin an FDD rule. Enable debug:{" "}
            <code>localStorage.ofdd_debug_plot=1</code>
          </>
        }
      />
      <TabDebugPanel tab="plot" />

      <div className="panel">
        <div className="form-row">
          <TelemetryScopePicker
            idPrefix="plot"
            sites={sites}
            siteId={siteId}
            onSiteChange={setSiteId}
            equipmentGroups={equipmentGroups}
            equipmentId={equipmentId}
            onEquipmentChange={onEquipmentChange}
            disabled={catalogLoading}
          />
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
          <label className="checkbox-inline" title="Evaluates all saved rules — slow on large sites">
            <input type="checkbox" checked={includeFaults} onChange={(e) => setIncludeFaults(e.target.checked)} />
            FDD overlays (slow)
          </label>
          <label className="checkbox-inline">
            <input type="checkbox" checked={showBounds} onChange={(e) => setShowBounds(e.target.checked)} />
            OOB guide lines
          </label>
          <div className="form-row-actions">
            <button type="button" disabled={chartLoading || !selected.size} onClick={() => void refreshChart()}>
              {chartLoading ? "Loading…" : "Refresh chart"}
            </button>
          </div>
        </div>
      </div>

      <div className="plot-series-picker panel">
        <div className="plot-series-picker-head">
          <h3 className="panel-title">Telemetry</h3>
          {activeGroup ? (
            <span className="muted">
              {activeGroup.name}
              {activeGroup.bacnet_device_instance != null ? ` · device ${activeGroup.bacnet_device_instance}` : ""}
              {" · "}
              {visibleOptions.length} point{visibleOptions.length === 1 ? "" : "s"}
              {catalogLoading ? " · loading catalog…" : ""}
            </span>
          ) : null}
        </div>
        {visibleOptions.length ? (
          <>
            <div className="plot-series-toolbar">
              <button type="button" className="secondary-btn" onClick={selectAllVisible}>
                Select all
              </button>
              <button type="button" className="secondary-btn" onClick={clearVisible}>
                Clear
              </button>
              <a className="secondary-btn" href={plotLink}>
                Link this scope
              </a>
            </div>
            <div className="plot-series-chips">
              {visibleOptions.map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  className={selected.has(opt.key) ? "chip chip-on" : "chip chip-off"}
                  onClick={() => toggleKey(opt.key)}
                  onContextMenu={(e: MouseEvent) => {
                    e.preventDefault();
                    setPinMenu({
                      kind: "point",
                      id: opt.key,
                      label: opt.label,
                      x: e.clientX,
                      y: e.clientY,
                    });
                  }}
                  title={
                    opt.column !== opt.key
                      ? `Feather column: ${opt.column} — right-click to pin FDD rule`
                      : "Right-click to pin FDD rule"
                  }
                >
                  {opt.label}
                  <span className="chip-kind">{seriesKindLabel(opt)}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <p className="muted">
            {catalog.seriesOptions.length
              ? "No points for this device in the feather store — try another device or enable BACnet polling."
              : "No numeric columns in feather store — enable BACnet polling first."}
          </p>
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
        {chartLoading ? <div className="plot-chart-loading">Loading chart…</div> : null}
        <div ref={chartRef} className="plot-chart" />
      </div>
      <FddRulePinMenu menu={pinMenu} onClose={() => setPinMenu(null)} onStatus={setPinStatus} />

      {status ? <p className="ok">{status}</p> : null}
      {pinStatus ? <p className="ok">{pinStatus}</p> : null}
      {(error || catalogError) ? <p className="error">{error || catalogError}</p> : null}
    </div>
  );
}
