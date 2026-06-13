import { useCallback, useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { apiFetch } from "../lib/api";
import { appendHostHistory } from "../lib/hostHistory";
import { formatDurationMs } from "../lib/formatDuration";
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
  feather_bytes?: number;
  feather_max_gib?: number;
  breakdown?: { role: string; label: string; path: string; bytes: number }[];
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
  ollama: {
    optional?: boolean;
    detail?: string;
    api_ok?: boolean;
    base_url?: string;
    active_base_url?: string;
    tried_urls?: string[];
    models_installed?: string[];
    configured_model?: string;
    configured_ram_tier?: string;
    gpu_mode?: string;
    gpu_available?: boolean;
    interactive_chat_enabled?: boolean;
    health_timeout_s?: number;
    chat_timeout_s?: number;
    error?: string;
    pid?: number;
    rss_bytes?: number;
    command?: string;
    process?: { pid?: number; rss_bytes?: number };
  };
  container_revisions?: {
    image_tag?: string;
    git_sha?: string;
    built_at?: string;
    services?: {
      id: string;
      label: string;
      image: string;
      image_tag?: string;
      git_sha?: string;
      built_at?: string;
      api_version?: string;
      note?: string;
    }[];
  };
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

type PoogePreview = {
  ok?: boolean;
  dry_run?: boolean;
  targets?: { action?: string; label?: string; path?: string }[];
  audit?: string[];
  errors?: string[];
};

export default function HostStatsPage() {
  const [stats, setStats] = useState<HostStats | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [poogeDryRun, setPoogeDryRun] = useState(true);
  const [poogeConfirm, setPoogeConfirm] = useState("");
  const [poogeClearHistorian, setPoogeClearHistorian] = useState(true);
  const [poogeClearBacnet, setPoogeClearBacnet] = useState(true);
  const [poogeClearModel, setPoogeClearModel] = useState(false);
  const [poogeClearRules, setPoogeClearRules] = useState(false);
  const [poogeClearExports, setPoogeClearExports] = useState(true);
  const [poogeLinuxUpdate, setPoogeLinuxUpdate] = useState(false);
  const [poogeDockerUpdate, setPoogeDockerUpdate] = useState(false);
  const [poogePreview, setPoogePreview] = useState<PoogePreview | null>(null);
  const [poogeBusy, setPoogeBusy] = useState(false);
  const inFlightRef = useRef(false);
  const pollRef = useRef<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

  const poogeBody = useCallback(
    () => ({
      dry_run: poogeDryRun,
      confirmation: poogeConfirm,
      clear_historian: poogeClearHistorian,
      clear_bacnet: poogeClearBacnet,
      clear_model: poogeClearModel,
      clear_rules: poogeClearRules,
      clear_exports: poogeClearExports,
      preserve_auth: true,
      preserve_network: true,
      preserve_site_identity: true,
      linux_update: poogeLinuxUpdate,
      docker_update: poogeDockerUpdate,
    }),
    [
      poogeDryRun,
      poogeConfirm,
      poogeClearHistorian,
      poogeClearBacnet,
      poogeClearModel,
      poogeClearRules,
      poogeClearExports,
      poogeLinuxUpdate,
      poogeDockerUpdate,
    ],
  );

  async function previewPooge() {
    setPoogeBusy(true);
    try {
      const res = await apiFetch<PoogePreview>("/api/host/pooge/preview", {
        method: "POST",
        body: JSON.stringify(poogeBody()),
      });
      setPoogePreview(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setPoogeBusy(false);
    }
  }

  async function runPooge() {
    setPoogeBusy(true);
    try {
      const res = await apiFetch<PoogePreview>("/api/host/pooge/run", {
        method: "POST",
        body: JSON.stringify(poogeBody()),
      });
      setPoogePreview(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setPoogeBusy(false);
    }
  }

  const load = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (pollRef.current != null) window.clearTimeout(pollRef.current);
    };
  }, [load]);

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
              <h3 className="panel-title">Disk usage</h3>
              <p className="muted host-storage-note">
                Workspace data volume <code>{storage.path}</code>
                {storage.feather_max_gib != null ? ` · feather cap ${storage.feather_max_gib} GiB` : ""}
              </p>
              <MetricMeter
                label="Partition used"
                pct={storage.percent_used}
                detail={`${fmtBytes(storage.free_bytes)} free of ${fmtBytes(storage.total_bytes)} total`}
                warn={diskWarn}
              />
              {storage.breakdown?.length ? (
                <div className="host-storage-breakdown">
                  {storage.breakdown.map((row) => (
                    <div key={row.role} className="host-storage-row">
                      <span>{row.label}</span>
                      <strong>{fmtBytes(row.bytes)}</strong>
                      <span className="muted">
                        <code>{row.path}</code>
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="panel muted">Data disk metrics unavailable on this host.</div>
          )}

          <div className={`panel${stats.ollama.optional ? " host-ollama-optional" : ""}`}>
            <h3 className="panel-title">Ollama</h3>
            {stats.ollama.optional ? (
              <>
                <p className="muted">
                  {stats.ollama.detail || "Optional on CPU-only hosts — building insight uses rule-based summaries."}
                </p>
                {stats.ollama.configured_ram_tier || stats.ollama.configured_model ? (
                  <div className="host-ollama-grid">
                    {stats.ollama.configured_model ? (
                      <div className="status-kv">
                        <span className="status-kv-label">Model</span>
                        <span className="status-kv-value">{stats.ollama.configured_model}</span>
                      </div>
                    ) : null}
                    {stats.ollama.configured_ram_tier ? (
                      <div className="status-kv">
                        <span className="status-kv-label">Runtime</span>
                        <span className="status-kv-value">
                          {stats.ollama.configured_ram_tier}
                          {stats.ollama.gpu_mode ? `, ${stats.ollama.gpu_mode}` : ""}
                        </span>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <div className="host-ollama-grid">
                  <div className="status-kv">
                    <span className="status-kv-label">API</span>
                    <span className={`status-kv-value ${stats.ollama.api_ok ? "ok" : "error"}`}>
                      {stats.ollama.api_ok ? "reachable" : "unreachable"}
                    </span>
                  </div>
                  {stats.ollama.active_base_url || stats.ollama.base_url ? (
                    <div className="status-kv">
                      <span className="status-kv-label">URL</span>
                      <span className="status-kv-value mono">
                        {stats.ollama.active_base_url || stats.ollama.base_url}
                      </span>
                    </div>
                  ) : null}
                  {stats.ollama.configured_model ? (
                    <div className="status-kv">
                      <span className="status-kv-label">Model</span>
                      <span className="status-kv-value">{stats.ollama.configured_model}</span>
                    </div>
                  ) : null}
                  {stats.ollama.configured_ram_tier ? (
                    <div className="status-kv">
                      <span className="status-kv-label">Runtime</span>
                      <span className="status-kv-value">
                        {stats.ollama.configured_ram_tier}
                        {stats.ollama.gpu_mode ? `, ${stats.ollama.gpu_mode}` : ""}
                      </span>
                    </div>
                  ) : null}
                  <div className="status-kv">
                    <span className="status-kv-label">GPU</span>
                    <span className={`status-kv-value ${stats.ollama.gpu_available ? "ok" : ""}`}>
                      {stats.ollama.gpu_available ? "available" : "not detected"}
                    </span>
                  </div>
                  <div className="status-kv">
                    <span className="status-kv-label">Agent chat</span>
                    <span className={`status-kv-value ${stats.ollama.interactive_chat_enabled ? "ok" : ""}`}>
                      {stats.ollama.interactive_chat_enabled ? "enabled" : "disabled"}
                    </span>
                  </div>
                  {stats.ollama.health_timeout_s != null ? (
                    <div className="status-kv">
                      <span className="status-kv-label">Health probe</span>
                      <span className="status-kv-value">{formatDurationMs(stats.ollama.health_timeout_s * 1000)}</span>
                    </div>
                  ) : null}
                  {stats.ollama.chat_timeout_s != null ? (
                    <div className="status-kv">
                      <span className="status-kv-label">Agent chat timeout</span>
                      <span className="status-kv-value">{formatDurationMs(stats.ollama.chat_timeout_s * 1000)}</span>
                    </div>
                  ) : null}
                  {stats.ollama.process?.rss_bytes || stats.ollama.rss_bytes ? (
                    <div className="status-kv">
                      <span className="status-kv-label">Host process RAM</span>
                      <span className="status-kv-value">
                        {fmtBytes(stats.ollama.process?.rss_bytes ?? stats.ollama.rss_bytes)}
                      </span>
                    </div>
                  ) : null}
                </div>
                {stats.ollama.error && !stats.ollama.api_ok ? (
                  <p className="muted host-storage-note">{stats.ollama.error}</p>
                ) : null}
                {!stats.ollama.api_ok && stats.ollama.tried_urls?.length ? (
                  <p className="muted host-storage-note">
                    Probed: {stats.ollama.tried_urls.join(", ")} — use{" "}
                    <code>docker compose --profile ai up -d</code> or set <code>OFDD_OLLAMA_BASE_URL</code> in{" "}
                    <code>workspace/ollama.env.local</code>.
                  </p>
                ) : null}
              </>
            )}
          </div>

          {stats.container_revisions?.services?.length ? (
            <div className="panel">
              <h3 className="panel-title">Container revisions</h3>
              <p className="muted">
                Image tag <code>{stats.container_revisions.image_tag}</code>
                {stats.container_revisions.git_sha ? (
                  <> · git <code>{stats.container_revisions.git_sha}</code></>
                ) : null}
                {stats.container_revisions.built_at ? <> · built {stats.container_revisions.built_at}</> : null}
              </p>
              <table className="data-table compact">
                <thead>
                  <tr>
                    <th>Service</th>
                    <th>Image</th>
                    <th>Rev</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.container_revisions.services.map((svc) => (
                    <tr key={svc.id}>
                      <td>{svc.label}</td>
                      <td className="mono">{svc.image}</td>
                      <td className="mono">
                        {svc.api_version ? `api ${svc.api_version}` : svc.git_sha || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <div className="panel danger-zone">
            <h3 className="panel-title">Danger Zone</h3>
            <p className="muted">
              <strong>Factory reset</strong> — wipe historian, BACnet scratch, and exports for a clean job-site
              redeploy. Integrator only. Type <code>RESET THIS EDGE</code> to run for real. Dry-run is on by default.
            </p>
            <label>
              <input type="checkbox" checked={poogeDryRun} onChange={(e) => setPoogeDryRun(e.target.checked)} />
              Dry-run preview (no deletes)
            </label>
            <div className="host-info-grid">
              <label><input type="checkbox" checked={poogeClearHistorian} onChange={(e) => setPoogeClearHistorian(e.target.checked)} /> Clear historian</label>
              <label><input type="checkbox" checked={poogeClearBacnet} onChange={(e) => setPoogeClearBacnet(e.target.checked)} /> Clear BACnet scratch</label>
              <label><input type="checkbox" checked={poogeClearModel} onChange={(e) => setPoogeClearModel(e.target.checked)} /> Clear BRICK model</label>
              <label><input type="checkbox" checked={poogeClearRules} onChange={(e) => setPoogeClearRules(e.target.checked)} /> Clear rules</label>
              <label><input type="checkbox" checked={poogeClearExports} onChange={(e) => setPoogeClearExports(e.target.checked)} /> Clear exports</label>
              <label><input type="checkbox" checked={poogeLinuxUpdate} onChange={(e) => setPoogeLinuxUpdate(e.target.checked)} /> Linux package update</label>
              <label><input type="checkbox" checked={poogeDockerUpdate} onChange={(e) => setPoogeDockerUpdate(e.target.checked)} /> Pull Docker images</label>
            </div>
            <div className="field">
              <label className="field-label">Confirmation phrase</label>
              <input value={poogeConfirm} onChange={(e) => setPoogeConfirm(e.target.value)} placeholder="RESET THIS EDGE" />
            </div>
            <div className="toolbar">
              <button type="button" className="secondary-btn" disabled={poogeBusy} onClick={() => void previewPooge()}>
                Preview actions
              </button>
              <button type="button" className="danger-btn" disabled={poogeBusy || poogeDryRun} onClick={() => void runPooge()}>
                Run factory reset
              </button>
            </div>
            {poogePreview?.targets?.length ? (
              <ul className="muted">
                {poogePreview.targets.map((t, i) => (
                  <li key={i}>{t.label || t.action}{t.path ? ` — ${t.path}` : ""}</li>
                ))}
              </ul>
            ) : null}
            {poogePreview?.audit?.length ? (
              <pre className="muted">{poogePreview.audit.join("\n")}</pre>
            ) : null}
          </div>

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
            </div>
          </div>
        </>
      ) : (
        !error && <p className="muted">Loading host metrics…</p>
      )}
    </div>
  );
}
