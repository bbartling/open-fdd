import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/api";

type MemBlock = {
  available?: boolean;
  total_bytes?: number;
  used_bytes?: number;
  available_bytes?: number;
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
  swap: MemBlock;
  disks: Array<{
    label: string;
    path: string;
    total_bytes: number;
    used_bytes: number;
    free_bytes: number;
    percent_used: number;
  }>;
  network: { available?: boolean; rx_bytes?: number; tx_bytes?: number };
  processes: { count: number | null };
  ollama: { pid?: number; command?: string; rss_bytes?: number } | null;
};

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
  if (pct >= 70) return "metric-fill-warn";
  return "metric-fill-ok";
}

function MetricMeter({ label, pct, detail }: { label: string; pct: number | null | undefined; detail: string }) {
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
    </div>
  );
}

export default function HostStatsPage() {
  const [stats, setStats] = useState<HostStats | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlightRef = useRef(false);
  const pollRef = useRef<number | null>(null);

  async function load() {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setBusy(true);
    try {
      const data = await apiFetch<HostStats>("/api/host/stats");
      setStats(data);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      inFlightRef.current = false;
      setBusy(false);
      pollRef.current = window.setTimeout(load, 5000);
    }
  }

  useEffect(() => {
    load();
    return () => {
      if (pollRef.current != null) {
        window.clearTimeout(pollRef.current);
      }
    };
  }, []);

  const mem = stats?.memory;
  const swap = stats?.swap;

  return (
    <div>
      <h2 className="title">Host stats</h2>
      <p className="muted">
        Edge host OS metrics — CPU, RAM, swap, disk, and network. Refreshes every 5s.
      </p>

      <div className="row">
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
          <div className="panel">
            <h3>System</h3>
            <div className="host-info-grid">
              <div>
                <span className="muted">Hostname</span>
                <div>{stats.host.hostname}</div>
              </div>
              <div>
                <span className="muted">OS</span>
                <div>
                  {stats.host.platform} {stats.host.platform_release} ({stats.host.machine})
                </div>
              </div>
              <div>
                <span className="muted">Uptime</span>
                <div>{fmtUptime(stats.host.uptime_seconds)}</div>
              </div>
              <div>
                <span className="muted">Python</span>
                <div>{stats.host.python_version}</div>
              </div>
              <div>
                <span className="muted">Processes</span>
                <div>{stats.processes.count ?? "—"}</div>
              </div>
            </div>
          </div>

          <div className="metric-grid">
            <MetricMeter
              label="CPU"
              pct={stats.cpu.usage_percent}
              detail={`${stats.cpu.logical_cores} cores${
                stats.cpu.load_1 != null
                  ? ` · load ${stats.cpu.load_1} / ${stats.cpu.load_5} / ${stats.cpu.load_15}`
                  : ""
              }`}
            />
            {mem?.available ? (
              <MetricMeter
                label="RAM"
                pct={mem.percent_used}
                detail={`${fmtBytes(mem.used_bytes)} used · ${fmtBytes(mem.available_bytes)} available · ${fmtBytes(mem.total_bytes)} total`}
              />
            ) : (
              <div className="metric-card muted">RAM metrics unavailable on this host.</div>
            )}
            {swap?.available ? (
              <MetricMeter
                label="Swap"
                pct={swap.percent_used}
                detail={`${fmtBytes(swap.used_bytes)} used · ${fmtBytes(swap.free_bytes)} free · ${fmtBytes(swap.total_bytes)} total`}
              />
            ) : (
              <div className="metric-card muted">Swap metrics unavailable.</div>
            )}
          </div>

          {stats.disks.length ? (
            <div className="panel">
              <h3>Disk</h3>
              <div className="metric-grid">
                {stats.disks.map((disk) => (
                  <MetricMeter
                    key={disk.path}
                    label={disk.label}
                    pct={disk.percent_used}
                    detail={`${fmtBytes(disk.used_bytes)} used · ${fmtBytes(disk.free_bytes)} free · ${fmtBytes(disk.total_bytes)} total`}
                  />
                ))}
              </div>
            </div>
          ) : null}

          <div className="panel">
            <h3>Network &amp; local AI</h3>
            <div className="host-info-grid">
              <div>
                <span className="muted">Network (non-loopback)</span>
                <div>
                  {stats.network.available
                    ? `↓ ${fmtBytes(stats.network.rx_bytes)} · ↑ ${fmtBytes(stats.network.tx_bytes)}`
                    : "—"}
                </div>
              </div>
              <div>
                <span className="muted">Ollama process</span>
                <div>
                  {stats.ollama
                    ? `PID ${stats.ollama.pid} · RSS ${fmtBytes(stats.ollama.rss_bytes)}`
                    : "Not detected"}
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
