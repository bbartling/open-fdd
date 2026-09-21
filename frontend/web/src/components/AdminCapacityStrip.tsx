import { useCallback, useEffect, useState } from "react";
import {
  formatBytes,
  getHistorianCompactionStatus,
  getHostStats,
  runHistorianCompaction,
  type HostStatsResponse,
} from "../api/hostStatsApi";
import { getHistorianLimits } from "../api/adminApi";
import { Button } from "./widgets/Button";

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
  const [notice, setNotice] = useState<string | null>(null);
  const [compacting, setCompacting] = useState(false);

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

  const runCompact = useCallback(
    async (wait: boolean) => {
      setCompacting(true);
      setNotice(null);
      setError(null);
      try {
        const result = await runHistorianCompaction({ confirm: true, wait });
        if (result.ok === false) {
          throw new Error(result.error ?? "Compaction failed");
        }
        const summary = result.summary;
        setNotice(
          summary
            ? `Compacted ${summary.partitions ?? 0} partition(s): ${summary.input_files ?? 0} → ${summary.output_files ?? 0} files, ${summary.rows ?? 0} rows.`
            : "Compaction finished.",
        );
        await refresh();
        await getHistorianCompactionStatus().catch(() => null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setCompacting(false);
      }
    },
    [refresh],
  );

  const mem = stats?.memory;
  const storage = stats?.storage;
  const parquet = stats?.data_management?.parquet;
  const coord = stats?.compaction_coordinator;
  const sizeCapBytes =
    sizeGib != null && Number.isFinite(sizeGib) ? sizeGib * 1024 ** 3 : null;
  const histBytes = parquet?.estimated_bytes;
  const histPct =
    sizeCapBytes != null && histBytes != null && sizeCapBytes > 0
      ? (histBytes / sizeCapBytes) * 100
      : null;
  const compactionLabel =
    coord?.mode ?? parquet?.compaction_status ?? "Not reported";

  return (
    <section
      aria-labelledby="admin-capacity-heading"
      data-testid="admin-capacity-strip"
      style={{ marginTop: "2rem" }}
    >
      <h2 id="admin-capacity-heading">Capacity</h2>
      <p className="muted" style={{ maxWidth: 560 }}>
        Container cgroup memory and workspace disk — not shared-host RAM totals.
        Small-file compaction serializes against DataFusion scans (fail closed or wait).
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
        <div className="ops-capacity-strip__item" data-testid="admin-compaction-status">
          <span className="ops-capacity-strip__label">Compaction</span>
          <span className="ops-capacity-strip__value">
            {compactionLabel}
            {coord?.scanners != null ? ` · scans ${coord.scanners}` : ""}
          </span>
        </div>
        {error ? (
          <div className="ops-capacity-strip__item">
            <span className="ops-capacity-strip__label">Capacity</span>
            <span className="ops-capacity-strip__value ops-capacity-strip__value--bad">{error}</span>
          </div>
        ) : null}
        {notice ? (
          <div className="ops-capacity-strip__item">
            <span className="ops-capacity-strip__label">Last compact</span>
            <span className="ops-capacity-strip__value">{notice}</span>
          </div>
        ) : null}
      </div>
      <div className="button-row" style={{ marginTop: "0.75rem" }}>
        <Button
          id="admin-compact-fail-closed"
          label={compacting ? "Compacting…" : "Compact now"}
          loading={compacting}
          onClick={() => void runCompact(false)}
        />
        <Button
          id="admin-compact-wait"
          label="Compact (wait for scans)"
          variant="secondary"
          loading={compacting}
          onClick={() => void runCompact(true)}
        />
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
