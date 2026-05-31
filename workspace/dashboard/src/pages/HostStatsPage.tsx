import { useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { apiFetch } from "../lib/api";
import { appendHostHistory } from "../lib/hostHistory";
import PageHeader from "../components/PageHeader";

type MemBlock = {
  available?: boolean;
  total_bytes?: number;
  used_bytes?: number;
  available_bytes?: number;
  free_bytes?: number;
  percent_used?: number;
};

type StorageBlock = {
  available?: boolean;
  label?: string;
  path?: string;
  note?: string;
  total_bytes?: number;
  used_bytes?: number;
  free_bytes?: number;
  percent_used?: number;
};

type HostStats = {
  ok: boolean;
  collected_at: string;
  host: {
    hostname: string;
    platform: string;
    platform_release: string;
    machine: string;
    python_version: string;
    uptime_seconds: number | null;
  };
  cpu: {
    logical_cores: number;
    usage_percent: number | null;
    load_1?: number;
    load_5?: number;
    load_15?: number;
  };
  memory: MemBlock;
  storage: StorageBlock;
  network: { available?: boolean; rx_bytes?: number; tx_bytes?: number };
  ollama: { pid?: number; command?: string; rss_bytes?: number } | null;
};

type HistoryPoint = {
  at: string;
  cpu: number | null;
  mem: number | null;
};

const POLL_MS = 5000;

function fmtBytes(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function fmtUptime(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function meterClass(pct: number | undefined | null): string {
  if (pct == null) return "metric-fill-ok";
  if (pct >= 90) return "metric-fill-critical";
  if (pct >= 75) return "metric-fill-warn";
  return "metric-fill-ok";
}

function appendHistory(prev: HistoryPoint[], sample: HistoryPoint): HistoryPoint[] {
  return appendHostHistory(prev, sample);
}

function MetricMeter({
  label,
  pct,
  detail,
  warn,
}: {
  label: string;
  pct: number | null | undefined;
  detail: string;
  warn?: string;
}) {
  const width = pct == null ? 0 : Math.min(100, Math.max(0, pct));
  return (
    <div className="metric-card">
      <div className="metric-head">
        <span>{label}</span>
        <strong>{pct == null ? "—" : `${pct.toFixed(1)}%`}</strong>
      </div>
      <div className="metric-meter" aria-hidden>
        <div className={`metric-meter-fill ${meterClass(pct)}`} style={{ width: `${width}%` }} />
      </div>
      <p className="muted metric-detail">{detail}</p>
      {warn ? <p className="error metric-detail">{warn}</p> : null}
    </div>
  );
}

export default function HostStatsPage() {
  const [stats, setStats] = useState<HostStats | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlightRef = useRef(false);
  const pollRef = useRef<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  async function load() {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setBusy(true);
    try {
      const data = await apiFetch<HostStats>("/api/host/stats");
      setStats(data);
      setHistory((prev) =>
        appendHistory(prev, {
          at: data.collected_at,
          cpu: data.cpu.usage_percent,
          mem: data.memory?.percent_used ?? null,
        }),
      );
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      inFlightRef.current = false;
      setBusy(false);
      pollRef.current = window.setTimeout(load, POLL_MS);
    }
  }

  useEffect(() => {
    load();
    return () => {
      if (pollRef.current != null) window.clearTimeout(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current || history.length < 2) return;
    const times = history.map((p) => p.at);
    void Plotly.react(
      chartRef.current,
      [
        {
          x: times,
          y: history.map((p) => p.cpu),
          type: "scatter",
          mode: "lines",
          name: "CPU %",
          connectgaps: true,
          line: { color: "#4f78e8", width: 2 },
        },
        {
          x: times,
          y: history.map((p) => p.mem),
          type: "scatter",
          mode: "lines",
          name: "RAM %",
          connectgaps: true,
          line: { color: "#7fd992", width: 2 },
          yaxis: "y2",
        },
      ],
      {
        title: "Last hour (oldest → newest)",
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { color: "#97a3b8", size: 11 },
        margin: { t: 36, r: 48, b: 40, l: 44 },
        xaxis: { title: "Time", type: "date" },
        yaxis: { title: "CPU %", range: [0, 100], ticksuffix: "%" },
        yaxis2: {
          title: "RAM %",
          overlaying: "y",
          side: "right",
          range: [0, 100],
          ticksuffix: "%",
        },
        legend: { orientation: "h", y: 1.15 },
        showlegend: true,
      },
      { responsive: true, displayModeBar: false },
    );
  }, [history]);

  useEffect(
    () => () => {
      if (chartRef.current) Plotly.purge(chartRef.current);
    },
    [],
  );

  const mem = stats?.memory;
  const storage = stats?.storage;
  const diskWarn =
    storage?.available && (storage.percent_used ?? 0) >= 85
      ? "Disk is getting full — feather store may fail soon."
      : undefined;

  return (
    <div className="page page-wide">
      <PageHeader
        title="Host stats"
        subtitle="CPU, RAM, and data-disk space for this edge box. Samples every 5s; charts show the last hour."
      />

      <div className="toolbar">
        <button type="button" onClick={load} disabled={busy}>
          {busy ? "Refreshing…" : "Refresh now"}
        </button>
        {stats?.collected_at ? (
          <span className="muted">Last sample: {new Date(stats.collected_at).toLocaleString()}</span>
        ) : null}
      </div>

      {error ? <p className="error">{error}</p> : null}

      {stats ? (
        <>
          <div className="panel host-chart-panel">
            <h3 className="panel-title">CPU &amp; RAM — last hour</h3>
            {history.length < 2 ? (
              <p className="muted">Collecting samples… chart appears after a few polls.</p>
            ) : null}
            <div ref={chartRef} className="host-stats-chart" />
            <div className="host-now-row">
              <span className="muted">
                Now: CPU {stats.cpu.usage_percent ?? "—"}% · RAM {mem?.percent_used ?? "—"}%
              </span>
            </div>
          </div>

          {storage?.available ? (
            <div className="panel">
              <h3 className="panel-title">Data disk (feather store)</h3>
              <p className="muted host-storage-note">
                One number that matters for trends and rules: free space on{" "}
                <code>{storage.path}</code>
              </p>
              <MetricMeter
                label="Used"
                pct={storage.percent_used}
                detail={`${fmtBytes(storage.free_bytes)} free of ${fmtBytes(storage.total_bytes)} total`}
                warn={diskWarn}
              />
            </div>
          ) : (
            <div className="panel muted">Data disk metrics unavailable on this host.</div>
          )}

          <div className="panel">
            <h3 className="panel-title">System</h3>
            <div className="host-info-grid">
              <div>
                <span className="status-kv-label">Hostname</span>
                <div>{stats.host.hostname}</div>
              </div>
              <div>
                <span className="status-kv-label">Uptime</span>
                <div>{fmtUptime(stats.host.uptime_seconds)}</div>
              </div>
              <div>
                <span className="status-kv-label">CPU cores</span>
                <div>{stats.cpu.logical_cores}</div>
              </div>
              <div>
                <span className="status-kv-label">Ollama</span>
                <div>
                  {stats.ollama ? `running · ${fmtBytes(stats.ollama.rss_bytes)} RAM` : "not detected"}
                </div>
              </div>
            </div>
          </div>
        </>
      ) : (
        !error && <p className="muted">Loading host metrics…</p>
      )}
    </div>
  );
}
