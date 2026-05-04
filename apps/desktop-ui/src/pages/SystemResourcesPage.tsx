import { useCallback, useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";

type TimeseriesStats = {
  file_count: number;
  source_count: number;
  site_count: number;
  bytes_total: number;
};

type TtlStatus = {
  ttl_path: string;
  sync_interval_seconds: number;
  last_sync_path: string;
  last_sync_error: string;
};

type CpuInfo = {
  logical_cores: number;
  cpu_percent: number | null;
  load_average_1m?: number;
};

type SystemResources = {
  memory: {
    total_bytes: number;
    available_bytes: number;
    used_bytes: number;
    used_percent: number;
  };
  disk: {
    path: string;
    total_bytes: number;
    free_bytes: number;
    used_bytes: number;
    used_percent: number;
  };
  cpu?: CpuInfo;
};

function fmtBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = value;
  let idx = 0;
  while (n >= 1024 && idx < units.length - 1) {
    n /= 1024;
    idx += 1;
  }
  return `${n.toFixed(1)} ${units[idx]}`;
}

function StatTile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="system-resources-stat">
      <div className="system-resources-stat-label">{label}</div>
      <div className="system-resources-stat-value">{value}</div>
      {detail ? <div className="system-resources-stat-detail">{detail}</div> : null}
    </div>
  );
}

export function SystemResourcesPage() {
  const [stats, setStats] = useState<TimeseriesStats | null>(null);
  const [ttl, setTtl] = useState<TtlStatus | null>(null);
  const [resources, setResources] = useState<SystemResources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    setRefreshing(true);
    try {
      const [s, t, r] = await Promise.all([
        desktopFetch<TimeseriesStats>("/storage/timeseries/stats"),
        desktopFetch<TtlStatus>("/model/ttl/status"),
        desktopFetch<SystemResources>("/system/resources"),
      ]);
      setStats(s);
      setTtl(t);
      setResources(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const cpu = resources?.cpu;

  return (
    <section className="stack-page system-resources-page" aria-labelledby="system-resources-title">
      <header className="system-resources-hero">
        <h2 id="system-resources-title" className="title system-resources-title">
          System resources
        </h2>
        <p className="muted system-resources-lead">
          Feather footprint and TTL mirror on this machine, plus live RAM, CPU, and disk for the gateway host. Purge and
          deletion controls stay on <strong>Data &amp; model maintenance</strong>.
        </p>
      </header>

      {error ? (
        <div className="system-resources-banner system-resources-banner--error" role="alert">
          {error}
        </div>
      ) : null}

      <div className="system-resources-stack">
        <article className="system-resources-panel">
          <h3 className="system-resources-panel-title">Timeseries store</h3>
          <p className="muted system-resources-panel-desc">Feather files ingested through the bridge.</p>
          <div className="system-resources-panel-inner">
            {stats ? (
              <div className="system-resources-stat-grid">
                <StatTile label="Feather files" value={String(stats.file_count)} />
                <StatTile label="Sources" value={String(stats.source_count)} />
                <StatTile label="Sites with data" value={String(stats.site_count)} />
                <StatTile label="Total size" value={fmtBytes(stats.bytes_total)} />
              </div>
            ) : (
              <p className="muted system-resources-placeholder">Loading…</p>
            )}
          </div>
        </article>

        <article className="system-resources-panel">
          <h3 className="system-resources-panel-title">Host bridge</h3>
          <p className="muted system-resources-panel-desc">
            Physical memory, processor usage, and free space on the volume that hosts your user profile (same host as the
            gateway).
          </p>
          <div className="system-resources-panel-inner">
            {resources ? (
              <>
                <div className="system-resources-stat-grid">
                  <StatTile
                    label="RAM in use"
                    value={`${resources.memory.used_percent.toFixed(1)}%`}
                    detail={`${fmtBytes(resources.memory.used_bytes)} / ${fmtBytes(resources.memory.total_bytes)}`}
                  />
                  <StatTile
                    label="RAM available"
                    value={fmtBytes(resources.memory.available_bytes)}
                    detail="Ready for new work"
                  />
                  <StatTile
                    label="CPU"
                    value={
                      cpu?.cpu_percent != null
                        ? `${cpu.cpu_percent.toFixed(1)}%`
                        : cpu?.load_average_1m != null
                          ? `Load ${cpu.load_average_1m.toFixed(2)}`
                          : "—"
                    }
                    detail={
                      cpu?.cpu_percent != null
                        ? `~0.12s sample · ${cpu?.logical_cores ?? "—"} logical cores`
                        : cpu?.load_average_1m != null
                          ? `1m load avg (CPU % N/A here) · ${cpu?.logical_cores ?? "—"} cores`
                          : `${cpu?.logical_cores ?? "—"} logical cores`
                    }
                  />
                  <StatTile
                    label="Disk used"
                    value={`${resources.disk.used_percent.toFixed(1)}%`}
                    detail={`${fmtBytes(resources.disk.free_bytes)} free of ${fmtBytes(resources.disk.total_bytes)}`}
                  />
                </div>
                <p className="muted system-resources-disk-path" title={resources.disk.path}>
                  Disk measured at <code className="inline-code">{resources.disk.path}</code>
                </p>
                <div className="system-resources-chart-row">
                  <DonutChart
                    title="Memory"
                    used={resources.memory.used_bytes}
                    free={resources.memory.available_bytes}
                    usedLabel="In use"
                    freeLabel="Available"
                  />
                  <DonutChart
                    title="Disk"
                    used={resources.disk.used_bytes}
                    free={resources.disk.free_bytes}
                    usedLabel="Used"
                    freeLabel="Free"
                  />
                </div>
              </>
            ) : (
              <p className="muted system-resources-placeholder">Loading…</p>
            )}
          </div>
        </article>

        <article className="system-resources-panel">
          <h3 className="system-resources-panel-title">TTL mirror sync</h3>
          <p className="muted system-resources-panel-desc">Background sync of the RDF/TTL graph to the configured mirror.</p>
          <div className="system-resources-panel-inner system-resources-panel-inner--align-start">
            {ttl ? (
              <dl className="system-resources-dl">
                <div>
                  <dt>TTL path</dt>
                  <dd>
                    <code className="inline-code">{ttl.ttl_path}</code>
                  </dd>
                </div>
                <div>
                  <dt>Sync interval</dt>
                  <dd>{ttl.sync_interval_seconds}s</dd>
                </div>
                <div>
                  <dt>Last sync file</dt>
                  <dd>{ttl.last_sync_path || "Not yet synced"}</dd>
                </div>
                <div>
                  <dt>Last error</dt>
                  <dd>
                    {ttl.last_sync_error ? (
                      <span className="system-resources-dl-error">{ttl.last_sync_error}</span>
                    ) : (
                      <span className="muted">None</span>
                    )}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="muted system-resources-placeholder">Loading…</p>
            )}
          </div>
        </article>
      </div>

      <div className="system-resources-actions">
        <button type="button" className="secondary-btn" disabled={refreshing} onClick={() => void refresh()}>
          {refreshing ? "Refreshing…" : "Refresh stats"}
        </button>
      </div>
    </section>
  );
}

function DonutChart({
  title,
  used,
  free,
  usedLabel,
  freeLabel,
}: {
  title: string;
  used: number;
  free: number;
  usedLabel: string;
  freeLabel: string;
}) {
  const [ref, setRef] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    let mounted = true;
    async function draw() {
      if (!ref) return;
      const Plotly = (await import("plotly.js-dist-min")).default as {
        react: (el: HTMLDivElement, data: unknown[], layout: unknown, config: unknown) => void;
      };
      if (!mounted) return;
      const textColor = getComputedStyle(document.body).color || "#111827";
      Plotly.react(
        ref,
        [
          {
            type: "pie",
            labels: [usedLabel, freeLabel],
            values: [Math.max(0, used), Math.max(0, free)],
            hole: 0.58,
            textinfo: "label+percent",
            textposition: "outside",
            marker: { colors: ["#c23b3b", "#2f57c7"] },
          },
        ],
        {
          title: { text: title, font: { size: 14, color: textColor } },
          margin: { t: 44, r: 12, b: 12, l: 12 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { color: textColor },
          showlegend: true,
          legend: { orientation: "h", y: -0.08 },
        },
        { responsive: true, displaylogo: false },
      );
    }
    void draw();
    return () => {
      mounted = false;
    };
  }, [ref, title, used, free, usedLabel, freeLabel]);

  return (
    <div className="system-resources-chart-wrap">
      <div ref={setRef} className="system-resources-chart" />
    </div>
  );
}
