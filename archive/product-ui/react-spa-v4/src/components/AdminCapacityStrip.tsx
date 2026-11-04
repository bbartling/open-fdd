import { useCallback, useEffect, useState } from "react";
import {
  formatBytes,
  getHistorianCompactionStatus,
  getHostStats,
  runHistorianCompaction,
  type HistorianCompactionResponse,
  type HostStatsResponse,
} from "../api/hostStatsApi";
import { getHistorianLimits } from "../api/adminApi";
import { Button } from "./widgets/Button";

function pctLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(1)}%`;
}

/**
 * Hub-admin capacity strip — cgroup memory, workspace disk, and an honest
 * historian/cache split. Timescale figures appear only when the API reports them.
 */
export function AdminCapacityStrip({ sizeGib }: { sizeGib: number | null }) {
  const [stats, setStats] = useState<HostStatsResponse | null>(null);
  const [engine, setEngine] = useState<HistorianCompactionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [engineNote, setEngineNote] = useState<string | null>(null);
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
    try {
      const status = await getHistorianCompactionStatus();
      setEngine(status);
      setEngineNote(null);
    } catch (err) {
      setEngine(null);
      setEngineNote(err instanceof Error ? err.message : String(err));
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
  const cacheBytes = parquet?.estimated_bytes;
  const cachePct =
    sizeCapBytes != null && cacheBytes != null && sizeCapBytes > 0
      ? (cacheBytes / sizeCapBytes) * 100
      : null;
  const timescale =
    engine?.engine === "timescale-sql" || engine?.parquet_compaction === "not_applicable";
  const showCacheControls = engine != null && !timescale;
  const compactionLabel = timescale
    ? "not applicable"
    : coord?.mode ?? parquet?.compaction_status ?? "not reported";

  return (
    <section
      aria-labelledby="admin-capacity-heading"
      data-testid="admin-capacity-strip"
      style={{ marginTop: "2rem" }}
    >
      <h2 id="admin-capacity-heading">Capacity</h2>
      <p className="muted" style={{ maxWidth: 640 }}>
        Memory and workspace disk come from the host. The product historian is Timescale.
        Parquet figures here are an optional analytics-result cache, not telemetry. Database
        size, chunks, WAL, pool pressure, and ingest-queue age appear only when an API
        reports them. A missing figure is not a healthy database.
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
        <div className="ops-capacity-strip__item" data-testid="admin-timescale-capacity">
          <span className="ops-capacity-strip__label">Timescale historian</span>
          <span className="ops-capacity-strip__value">
            {timescale
              ? "Engine reported. Size, chunks, WAL, and pool pressure are not in this payload."
              : engine
                ? "Engine did not report Timescale. Do not treat the cache footprint as the historian."
                : "Not reported"}
          </span>
        </div>
        <div className="ops-capacity-strip__item" data-testid="admin-ingest-queue">
          <span className="ops-capacity-strip__label">Ingest queue</span>
          <span className="ops-capacity-strip__value">Not reported</span>
        </div>
        <div className="ops-capacity-strip__item">
          <span className="ops-capacity-strip__label">Analytics cache (Parquet)</span>
          <span className="ops-capacity-strip__value">
            {cacheBytes == null ? "not reported" : formatBytes(cacheBytes)}
            {sizeGib != null ? ` / ${sizeGib} GiB cap` : ""}
            {cachePct != null ? ` (${pctLabel(cachePct)})` : ""}
          </span>
        </div>
        <div className="ops-capacity-strip__item">
          <span className="ops-capacity-strip__label">Small cache files</span>
          <span className="ops-capacity-strip__value">
            {parquet?.small_file_count != null ? String(parquet.small_file_count) : "not reported"}
            {parquet?.file_count != null ? ` / ${parquet.file_count} total` : ""}
          </span>
        </div>
        <div className="ops-capacity-strip__item" data-testid="admin-compaction-status">
          <span className="ops-capacity-strip__label">Cache compaction</span>
          <span className="ops-capacity-strip__value">
            {compactionLabel}
            {!timescale && coord?.scanners != null ? ` · scans ${coord.scanners}` : ""}
            {engine?.note ? ` · ${engine.note}` : ""}
          </span>
        </div>
        {error ? (
          <div className="ops-capacity-strip__item">
            <span className="ops-capacity-strip__label">Host stats</span>
            <span className="ops-capacity-strip__value ops-capacity-strip__value--bad">{error}</span>
          </div>
        ) : null}
        {engineNote ? (
          <div className="ops-capacity-strip__item" data-testid="admin-engine-unknown">
            <span className="ops-capacity-strip__label">Historian engine</span>
            <span className="ops-capacity-strip__value">{engineNote}</span>
          </div>
        ) : null}
        {notice ? (
          <div className="ops-capacity-strip__item">
            <span className="ops-capacity-strip__label">Last cache compact</span>
            <span className="ops-capacity-strip__value">{notice}</span>
          </div>
        ) : null}
      </div>
      {showCacheControls ? (
        <div className="button-row" style={{ marginTop: "0.75rem" }}>
          <Button
            id="admin-compact-fail-closed"
            label={compacting ? "Compacting…" : "Compact analytics cache"}
            loading={compacting}
            onClick={() => void runCompact(false)}
          />
          <Button
            id="admin-compact-wait"
            label="Compact cache (wait for scans)"
            variant="secondary"
            loading={compacting}
            onClick={() => void runCompact(true)}
          />
        </div>
      ) : (
        <p className="muted" data-testid="admin-compact-disabled">
          Cache compaction controls stay off until the historian engine is reported, and they
          stay off when the engine is Timescale.
        </p>
      )}
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
