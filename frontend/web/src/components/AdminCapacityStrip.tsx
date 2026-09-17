import { useCallback, useEffect, useState } from "react";
import {
  formatBytes,
  getHostStats,
  type HostStatsResponse,
} from "../api/hostStatsApi";
import { getHistorianLimits } from "../api/adminApi";

function pctLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(1)}%`;
}

/**
 * Hub-admin capacity strip — cgroup memory + workspace df + Parquet historian footprint.
 */
export function AdminCapacityStrip({ sizeGib }: { sizeGib: number | null }) {
  const [stats, setStats] = useState<HostStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await getHostStats();
      setStats(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const mem = stats?.memory;
  const storage = stats?.storage;
  const parquet = stats?.data_management?.parquet;
  const sizeCapBytes =
    sizeGib != null && Number.isFinite(sizeGib) ? sizeGib * 1024 ** 3 : null;
  const histBytes = parquet?.estimated_bytes;
  const histPct =
    sizeCapBytes != null && histBytes != null && sizeCapBytes > 0
      ? (histBytes / sizeCapBytes) * 100
      : null;

  return (
    <section
      aria-labelledby="admin-capacity-heading"
      data-testid="admin-capacity-strip"
      style={{ marginTop: "2rem" }}
    >
      <h2 id="admin-capacity-heading">Capacity</h2>
      <p className="muted" style={{ maxWidth: 560 }}>
        Container cgroup memory and workspace disk — not shared-host RAM totals.
      </p>
      <div className="ops-capacity-strip" role="status" aria-live="polite">
        <div className="ops-capacity-strip__item">
          <span className="ops-capacity-strip__label">Memory ({mem?.source ?? "—"})</span>
          <span className="ops-capacity-strip__value">
            {formatBytes(mem?.used_bytes)}
            {mem?.total_bytes != null ? ` / ${formatBytes(mem.total_bytes)}` : ""}
            {mem?.percent_used != null ? ` (${pctLabel(mem.percent_used)})` : ""}
          </span>
        </div>
        <div className="ops-capacity-strip__item">
          <span className="ops-capacity-strip__label">Workspace disk</span>
          <span className="ops-capacity-strip__value">
            {formatBytes(storage?.used_bytes)}
            {storage?.total_bytes != null ? ` / ${formatBytes(storage.total_bytes)}` : ""}
            {storage?.percent_used != null ? ` (${pctLabel(storage.percent_used)})` : ""}
          </span>
        </div>
        <div className="ops-capacity-strip__item">
          <span className="ops-capacity-strip__label">Historian Parquet</span>
          <span className="ops-capacity-strip__value">
            {formatBytes(histBytes)}
            {sizeGib != null ? ` / ${sizeGib} GiB cap` : ""}
            {histPct != null ? ` (${pctLabel(histPct)})` : ""}
          </span>
        </div>
        <div className="ops-capacity-strip__item">
          <span className="ops-capacity-strip__label">Small Parquet files</span>
          <span className="ops-capacity-strip__value">
            {parquet?.small_file_count != null ? String(parquet.small_file_count) : "—"}
            {parquet?.file_count != null ? ` / ${parquet.file_count} total` : ""}
          </span>
        </div>
        {error ? (
          <div className="ops-capacity-strip__item">
            <span className="ops-capacity-strip__label">Capacity</span>
            <span className="ops-capacity-strip__value ops-capacity-strip__value--bad">{error}</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** Loads historian size cap then renders {@link AdminCapacityStrip}. */
export function AdminCapacityStripWithLimits() {
  const [sizeGib, setSizeGib] = useState<number | null>(null);
  useEffect(() => {
    void getHistorianLimits()
      .then((lim) => setSizeGib(lim.size_gib))
      .catch(() => setSizeGib(null));
  }, []);
  return <AdminCapacityStrip sizeGib={sizeGib} />;
}
