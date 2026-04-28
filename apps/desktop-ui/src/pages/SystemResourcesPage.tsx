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
  const [siteId, setSiteId] = useState("");
  const [source, setSource] = useState("");
  const [prunePoints, setPrunePoints] = useState(false);
  const [resources, setResources] = useState<SystemResources | null>(null);
  const [status, setStatus] = useState("Manage timeseries Feather storage and TTL sync status.");

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

  async function purgeTimeseries() {
    try {
      const out = await desktopFetch<{
        files_deleted: number;
        dirs_deleted: number;
        bytes_deleted: number;
        points_removed: number;
      }>("/storage/timeseries/purge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: source.trim() || null,
          site_id: siteId.trim() || null,
          prune_points: prunePoints,
        }),
      });
      setStatus(
        `Purged files=${out.files_deleted}, dirs=${out.dirs_deleted}, bytes=${out.bytes_deleted}, points_removed=${out.points_removed}`,
      );
      void refresh();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <h2 className="title">System resources + data maintenance</h2>
      <div className="grid-two">
        <div>
          <h3>Timeseries store</h3>
          <p style={{ color: "var(--muted)" }}>
            Feather files are stored under OS app data. Use purge controls to clean by source/site or wipe all.
          </p>
          <textarea
            readOnly
            value={
              stats
                ? `files=${stats.file_count}\nsources=${stats.source_count}\nsites=${stats.site_count}\nbytes=${stats.bytes_total}`
                : "Loading..."
            }
            style={{ minHeight: 120 }}
          />
        </div>
        <div>
          <h3>Host resources</h3>
          <textarea
            readOnly
            value={
              resources
                ? `Memory used: ${resources.memory.used_percent}%\n`
                  + `Memory avail: ${fmtBytes(resources.memory.available_bytes)} / ${fmtBytes(resources.memory.total_bytes)}\n`
                  + `Disk used: ${resources.disk.used_percent}%\n`
                  + `Disk free: ${fmtBytes(resources.disk.free_bytes)} / ${fmtBytes(resources.disk.total_bytes)}\n`
                  + `Disk path: ${resources.disk.path}`
                : "Loading..."
            }
            style={{ minHeight: 120 }}
          />
        </div>
        <div>
          <h3>TTL sync status</h3>
          <textarea
            readOnly
            value={
              ttl
                ? `ttl_path=${ttl.ttl_path}\ninterval_s=${ttl.sync_interval_seconds}\nlast_sync=${ttl.last_sync_path}\nerror=${ttl.last_sync_error || "none"}`
                : "Loading..."
            }
            style={{ minHeight: 120 }}
          />
        </div>
      </div>

      <h3 style={{ marginTop: 12 }}>Purge timeseries</h3>
      <div className="grid-two">
        <input value={siteId} onChange={(e) => setSiteId(e.target.value)} placeholder="site_id (optional)" />
        <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="source (optional)" />
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, marginBottom: 8 }}>
        <input
          style={{ width: "auto" }}
          type="checkbox"
          checked={prunePoints}
          onChange={(e) => setPrunePoints(e.target.checked)}
        />
        Also remove matching points from model and resync TTL
      </label>
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={() => void purgeTimeseries()}>Purge selected</button>
        <button
          onClick={() => {
            setSiteId("");
            setSource("");
            void purgeTimeseries();
          }}
        >
          Purge ALL timeseries
        </button>
        <button onClick={() => void refresh()}>Refresh stats</button>
      </div>
      <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 88 }} />
    </div>
  );
}
