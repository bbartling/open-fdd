import { useEffect, useState } from "react";
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

export function SystemResourcesPage() {
  const [stats, setStats] = useState<TimeseriesStats | null>(null);
  const [ttl, setTtl] = useState<TtlStatus | null>(null);
  const [resources, setResources] = useState<SystemResources | null>(null);
  const [status, setStatus] = useState("Host resources, Feather stats, and TTL sync health.");

  async function refresh() {
    try {
      const [s, t] = await Promise.all([
        desktopFetch<TimeseriesStats>("/storage/timeseries/stats"),
        desktopFetch<TtlStatus>("/model/ttl/status"),
      ]);
      setStats(s);
      setTtl(t);
      const r = await desktopFetch<SystemResources>("/system/resources");
      setResources(r);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="card">
      <h2 className="title">System resources</h2>
      <p className="muted">Data deletion and model purge controls live on the Data &amp; model maintenance page.</p>
      <div className="grid-two">
        <div>
          <h3>Timeseries store</h3>
          <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
            {stats ? (
              <div style={{ display: "grid", gap: 6 }}>
                <div><strong>Feather files:</strong> {stats.file_count}</div>
                <div><strong>Sources:</strong> {stats.source_count}</div>
                <div><strong>Sites with data:</strong> {stats.site_count}</div>
                <div><strong>Total bytes:</strong> {fmtBytes(stats.bytes_total)}</div>
              </div>
            ) : (
              <div className="muted">Loading...</div>
            )}
          </div>
        </div>
        <div>
          <h3>Host resources</h3>
          {resources ? (
            <div style={{ display: "grid", gap: 10 }}>
              <DonutChart
                title={`Memory used ${resources.memory.used_percent.toFixed(1)}%`}
                used={resources.memory.used_bytes}
                free={resources.memory.available_bytes}
                usedLabel="Used"
                freeLabel="Available"
              />
              <DonutChart
                title={`Disk used ${resources.disk.used_percent.toFixed(1)}%`}
                used={resources.disk.used_bytes}
                free={resources.disk.free_bytes}
                usedLabel="Used"
                freeLabel="Free"
              />
              <div className="muted">Disk path: {resources.disk.path}</div>
            </div>
          ) : (
            <div className="muted">Loading...</div>
          )}
        </div>
        <div>
          <h3>TTL sync status</h3>
          <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 12 }}>
            {ttl ? (
              <div style={{ display: "grid", gap: 6 }}>
                <div><strong>TTL path:</strong> {ttl.ttl_path}</div>
                <div><strong>Sync interval:</strong> {ttl.sync_interval_seconds}s</div>
                <div><strong>Last sync:</strong> {ttl.last_sync_path || "not yet synced"}</div>
                <div>
                  <strong>Last error:</strong>{" "}
                  {ttl.last_sync_error ? <span style={{ color: "var(--danger)" }}>{ttl.last_sync_error}</span> : "none"}
                </div>
              </div>
            ) : (
              <div className="muted">Loading...</div>
            )}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={() => void refresh()}>Refresh stats</button>
      </div>
      <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 88 }} />
    </div>
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
      Plotly.react(
        ref,
        [
          {
            type: "pie",
            labels: [usedLabel, freeLabel],
            values: [Math.max(0, used), Math.max(0, free)],
            hole: 0.55,
            textinfo: "label+percent",
            marker: { colors: ["#d45555", "#4f78e8"] },
          },
        ],
        {
          title,
          margin: { t: 36, r: 16, b: 16, l: 16 },
          paper_bgcolor: "transparent",
        },
        { responsive: true, displaylogo: false },
      );
    }
    void draw();
    return () => {
      mounted = false;
    };
  }, [ref, title, used, free, usedLabel, freeLabel]);

  return <div ref={setRef} style={{ height: 230, border: "1px solid var(--border)", borderRadius: 10 }} />;
}
