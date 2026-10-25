import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { apiFetch } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ProvidersPanel } from "../components/ProvidersPanel";
import { SitesPanel } from "../components/SitesPanel";
import { Button } from "../components/widgets";
import {
  buildAfddBackfillPayload,
  buildAfddSchedulePayload,
  localInputToUtc,
  type AfddScheduleKind,
} from "./afddSchedule";

type OperationsView = "afdd" | "sites" | "providers";

type AfddMode = "bulk" | "continuous";

interface AfddConfig {
  mode: AfddMode;
  interval_minutes: number;
  lookback_value: number;
  lookback_unit: "minutes" | "hours" | "days";
  schedule_kind?: AfddScheduleKind;
  wall_clock_hhmm?: string | null;
  wall_clock_timezone?: string | null;
}

interface AfddCheckpoint {
  last_completed_at_utc: string;
  analyzed_through_utc: string;
}

interface AfddCycleRecord {
  scope: string;
  trigger: string;
  started_at_utc: string;
  finished_at_utc: string;
  start_utc: string;
  end_utc: string;
  catch_up: boolean;
  ok: boolean;
  error?: string;
  rules_succeeded?: number;
  rules_failed?: number;
  rules_skipped?: number;
}

interface AfddSchedulerStatus {
  ok: boolean;
  config: AfddConfig;
  checkpoint?: AfddCheckpoint | null;
  latest_persisted_telemetry_utc?: string | null;
  next_due_at_utc?: string | null;
  next_due_local?: string | null;
  schedule_kind?: AfddScheduleKind;
  result_write?: string;
  last_error?: string | null;
  recent_cycles: AfddCycleRecord[];
  operator_schedule_editable?: boolean;
  error?: string;
}

interface AfddRunNowResponse {
  ok: boolean;
  cycle?: AfddCycleRecord;
  error?: string;
}

interface AfddConfigSaveResponse {
  ok: boolean;
  config?: AfddConfig;
  error?: string;
}

const AFDD_INTERVAL_OPTIONS: Array<{ minutes: number; label: string }> = [
  { minutes: 60, label: "Every 1 hour" },
  { minutes: 180, label: "Every 3 hours" },
  { minutes: 360, label: "Every 6 hours" },
  { minutes: 720, label: "Every 12 hours" },
  { minutes: 1440, label: "Every 24 hours" },
];

const AFDD_LOOKBACK_OPTIONS: Array<{ days: number; label: string }> = [
  { days: 1, label: "1 day" },
  { days: 2, label: "2 days" },
  { days: 3, label: "3 days" },
];

function lookbackDaysFromConfig(config?: AfddConfig | null): number {
  if (!config) return 1;
  if (config.lookback_unit === "days") return config.lookback_value;
  if (config.lookback_unit === "hours") return Math.max(1, Math.round(config.lookback_value / 24));
  if (config.lookback_unit === "minutes") {
    return Math.max(1, Math.round(config.lookback_value / (24 * 60)));
  }
  return 1;
}

function nearestIntervalMinutes(minutes?: number): number {
  if (minutes == null) return 60;
  const allowed = AFDD_INTERVAL_OPTIONS.map((option) => option.minutes);
  if (allowed.includes(minutes)) return minutes;
  return allowed.reduce((best, value) =>
    Math.abs(value - minutes) < Math.abs(best - minutes) ? value : best,
  );
}

interface FddContinuityRow {
  rule_id?: string;
  equipment_id?: string;
  first_seen_utc?: string;
  first_seen?: string;
  last_seen_utc?: string;
  last_seen?: string;
  continuity_count?: number;
  occurrences?: number;
}

interface FddResultsResponse {
  ok?: boolean;
  results?: FddContinuityRow[];
}


function formatTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString() : value;
}

function metric(label: string, value: string) {
  return (
    <div className="summary-card" key={label}>
      <div className="summary-card__label">{label}</div>
      <div className="summary-card__value">{value}</div>
    </div>
  );
}

function findScalar(root: unknown, names: string[]): string | null {
  const wanted = new Set(names.map((name) => name.toLowerCase()));
  const visit = (value: unknown, depth: number): string | null => {
    if (depth > 4 || value == null || typeof value !== "object") return null;
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      if (wanted.has(key.toLowerCase()) && ["string", "number", "boolean"].includes(typeof child)) {
        return String(child);
      }
    }
    for (const child of Object.values(value as Record<string, unknown>)) {
      const found = visit(child, depth + 1);
      if (found != null) return found;
    }
    return null;
  };
  return visit(root, 0);
}

function basFreshness(value?: string | null): string {
  if (!value) return "No persisted sample";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "Unknown";
  const ageMinutes = Math.max(0, Math.round((Date.now() - parsed) / 60000));
  return ageMinutes > 15 ? `Stale · ${ageMinutes} min old` : `Fresh · ${ageMinutes} min old`;
}

function cycleState(cycle: AfddCycleRecord): string {
  if (!cycle.ok) return cycle.error ?? "Failed";
  if ((cycle.rules_failed ?? 0) > 0) return "Partial";
  return "Success";
}

function AfddPanel() {
  const [status, setStatus] = useState<AfddSchedulerStatus | null>(null);
  const [historian, setHistorian] = useState<Record<string, unknown> | null>(null);
  const [timescaleOk, setTimescaleOk] = useState<boolean | null>(null);
  const [continuity, setContinuity] = useState<FddContinuityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [intervalMinutes, setIntervalMinutes] = useState(60);
  const [lookbackDays, setLookbackDays] = useState(1);
  const [scheduleKind, setScheduleKind] = useState<AfddScheduleKind>("interval");
  const [wallClockHhmm, setWallClockHhmm] = useState("05:00");
  const [wallClockTimezone, setWallClockTimezone] = useState("");
  const [backfillStart, setBackfillStart] = useState("");
  const [backfillEnd, setBackfillEnd] = useState("");
  const [backfilling, setBackfilling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [next, historianSummary, results, health] = await Promise.all([
        apiFetch<AfddSchedulerStatus>("/api/afdd/scheduler/status"),
        apiFetch<Record<string, unknown>>("/api/data-management/summary").catch(() => null),
        apiFetch<FddResultsResponse>("/api/fdd/results").catch(() => null),
        apiFetch<{ timescale_ok?: boolean; historian?: string }>("/api/health").catch(() => null),
      ]);
      setStatus(next);
      setHistorian(historianSummary);
      setTimescaleOk(
        health?.timescale_ok === true && health.historian === "timescale" ? true : health ? false : null,
      );
      setContinuity(results?.results ?? []);
      if (next.config) {
        setIntervalMinutes(nearestIntervalMinutes(next.config.interval_minutes));
        const days = lookbackDaysFromConfig(next.config);
        setLookbackDays([1, 2, 3].includes(days) ? days : 1);
        setScheduleKind(next.config.schedule_kind === "wall_clock" ? "wall_clock" : "interval");
        setWallClockHhmm(next.config.wall_clock_hhmm || "05:00");
        setWallClockTimezone(next.config.wall_clock_timezone || "");
      }
      setError(next.ok ? null : next.error ?? "AFDD scheduler status unavailable");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runNow = useCallback(async () => {
    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch<AfddRunNowResponse>("/api/afdd/scheduler/run-now", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!result.ok) {
        setError(result.error ?? result.cycle?.error ?? "AFDD run failed");
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [refresh]);

  const saveSchedule = useCallback(async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch<AfddConfigSaveResponse>("/api/afdd/scheduler/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          buildAfddSchedulePayload({
            scheduleKind,
            intervalMinutes,
            lookbackDays,
            wallClockHhmm,
            wallClockTimezone,
          }),
        ),
      });
      if (!result.ok) {
        throw new Error(result.error ?? "Failed to save AFDD schedule");
      }
      setNotice(
        scheduleKind === "wall_clock"
          ? `Saved daily wall-clock AFDD at ${wallClockHhmm} ${wallClockTimezone} · lookback ${lookbackDays} day${lookbackDays === 1 ? "" : "s"}.`
          : `Saved AFDD schedule: every ${intervalMinutes / 60}h · lookback ${lookbackDays} day${lookbackDays === 1 ? "" : "s"}.`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [intervalMinutes, lookbackDays, refresh, scheduleKind, wallClockHhmm, wallClockTimezone]);

  const runBackfill = useCallback(async () => {
    setBackfilling(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiFetch<{ ok: boolean; error?: string }>("/api/afdd/scheduler/backfill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          buildAfddBackfillPayload({
            startUtc: localInputToUtc(backfillStart),
            endUtc: localInputToUtc(backfillEnd),
            chunkHours: 24,
          }),
        ),
      });
      if (!result.ok) {
        throw new Error(result.error ?? "Bounded backfill failed");
      }
      setNotice("Bounded backfill finished. Rows outside that range were not rewritten.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBackfilling(false);
    }
  }, [backfillEnd, backfillStart, refresh]);

  const recent = status?.recent_cycles ?? [];
  const latestCycle = recent[0];
  const config = status?.config;
  const scheduleEditable = status?.operator_schedule_editable === true;
  const historianBackend = findScalar(historian, ["backend", "storage_backend", "storage", "scheme"]);
  const historianFiles = findScalar(historian, ["file_count", "files", "part_count", "parts"]);
  const historianBytes = findScalar(historian, ["total_bytes", "bytes", "size_bytes"]);
  const smallFiles = findScalar(historian, ["small_file_count", "small_files"]);
  const compaction = findScalar(historian, ["compaction_status", "compaction", "compaction_health"]);
  const continuityRows = continuity.filter((row) => row.first_seen_utc || row.first_seen || row.last_seen_utc || row.last_seen);

  return (
    <section aria-labelledby="afdd-config-heading" data-testid="afdd-config-panel">
      <div className="section-heading-row">
        <div>
          <h2 id="afdd-config-heading">AFDD Scheduler</h2>
          <p className="muted">
            Continuous AFDD frequency and rolling lookback are operator-selectable (hours / days).
            Mode stays deployment-owned. Run Now uses the same H8 engine as scheduled cycles.
          </p>
        </div>
        <div className="button-row">
          <Button id="afdd-refresh" label="Refresh" variant="secondary" loading={loading} onClick={() => void refresh()} />
          <Button id="afdd-run-now" label="Run AFDD now" loading={running} onClick={() => void runNow()} />
        </div>
      </div>

      {error ? <div className="inline-alert inline-alert--error" role="alert">{error}</div> : null}
      {notice ? <div className="inline-alert" role="status">{notice}</div> : null}
      {status?.last_error ? <div className="inline-alert inline-alert--error" role="status">Last scheduler error: {status.last_error}</div> : null}

      <div className="form-row" data-testid="afdd-schedule-controls">
        <label htmlFor="afdd-schedule-kind">Schedule</label>
        <select
          id="afdd-schedule-kind"
          data-testid="afdd-schedule-kind"
          value={scheduleKind}
          disabled={!scheduleEditable || saving}
          onChange={(event) => setScheduleKind(event.target.value as AfddScheduleKind)}
        >
          <option value="interval">Interval since last run</option>
          <option value="wall_clock">Daily wall clock</option>
        </select>
        <label htmlFor="afdd-wall-clock">Local time</label>
        <input
          id="afdd-wall-clock"
          data-testid="afdd-wall-clock"
          type="time"
          value={wallClockHhmm}
          disabled={!scheduleEditable || saving || scheduleKind !== "wall_clock"}
          onChange={(event) => setWallClockHhmm(event.target.value)}
        />
        <label htmlFor="afdd-timezone">Timezone</label>
        <input
          id="afdd-timezone"
          data-testid="afdd-timezone"
          type="text"
          value={wallClockTimezone}
          placeholder="IANA name, for example America/Chicago"
          disabled={!scheduleEditable || saving || scheduleKind !== "wall_clock"}
          onChange={(event) => setWallClockTimezone(event.target.value)}
        />
        <label htmlFor="afdd-frequency">Frequency</label>
        <select
          id="afdd-frequency"
          value={intervalMinutes}
          disabled={!scheduleEditable || saving || scheduleKind === "wall_clock"}
          onChange={(event) => setIntervalMinutes(Number(event.target.value))}
        >
          {AFDD_INTERVAL_OPTIONS.map((option) => (
            <option key={option.minutes} value={option.minutes}>
              {option.label}
            </option>
          ))}
        </select>
        <label htmlFor="afdd-lookback">Rolling lookback</label>
        <select
          id="afdd-lookback"
          value={lookbackDays}
          disabled={!scheduleEditable || saving}
          onChange={(event) => setLookbackDays(Number(event.target.value))}
        >
          {AFDD_LOOKBACK_OPTIONS.map((option) => (
            <option key={option.days} value={option.days}>
              {option.label}
            </option>
          ))}
        </select>
        <Button
          id="afdd-save-schedule"
          label={saving ? "Saving…" : "Save schedule"}
          loading={saving}
          disabled={!scheduleEditable}
          onClick={() => void saveSchedule()}
        />
        {!scheduleEditable ? (
          <span className="muted">
            Save requires Central with schedule API (after next GHCR central). Showing live values below.
          </span>
        ) : null}
      </div>

      <h3>Bounded backfill</h3>
      <div className="form-row" data-testid="afdd-backfill-controls">
        <label htmlFor="afdd-backfill-start">Start</label>
        <input
          id="afdd-backfill-start"
          type="datetime-local"
          value={backfillStart}
          disabled={backfilling}
          onChange={(event) => setBackfillStart(event.target.value)}
        />
        <label htmlFor="afdd-backfill-end">End</label>
        <input
          id="afdd-backfill-end"
          type="datetime-local"
          value={backfillEnd}
          disabled={backfilling}
          onChange={(event) => setBackfillEnd(event.target.value)}
        />
        <Button
          id="afdd-backfill"
          label={backfilling ? "Running…" : "Run bounded backfill"}
          loading={backfilling}
          disabled={!backfillStart || !backfillEnd}
          onClick={() => void runBackfill()}
        />
      </div>

      <div className="summary-grid">
        {metric("Mode", config?.mode ?? "—")}
        {metric(
          "Schedule",
          config?.schedule_kind === "wall_clock"
            ? `Daily ${config.wall_clock_hhmm ?? "—"} ${config.wall_clock_timezone ?? ""}`.trim()
            : "Interval",
        )}
        {metric("Frequency", config ? `every ${config.interval_minutes / 60} h (${config.interval_minutes} min)` : "—")}
        {metric(
          "Rolling lookback",
          config
            ? config.lookback_unit === "days"
              ? `${config.lookback_value} day${config.lookback_value === 1 ? "" : "s"}`
              : `${config.lookback_value} ${config.lookback_unit}`
            : "—",
        )}
        {metric("Latest historian sample", formatTime(status?.latest_persisted_telemetry_utc))}
        {metric("BAS freshness", basFreshness(status?.latest_persisted_telemetry_utc))}
        {metric("Analyzed through", formatTime(status?.checkpoint?.analyzed_through_utc))}
        {metric("Last completed", formatTime(status?.checkpoint?.last_completed_at_utc))}
        {metric(
          "Next due",
          config?.mode === "continuous"
            ? status?.next_due_local
              ? `${formatTime(status.next_due_at_utc)} · local ${status.next_due_local}`
              : formatTime(status?.next_due_at_utc)
            : "Bulk mode",
        )}
        {metric(
          "Result write",
          status?.result_write === "lookback_window" ? "Lookback window only" : status?.result_write ?? "—",
        )}
        {metric("Catch-up", latestCycle?.catch_up ? "Yes" : "No")}
      </div>

      <h3>Historian health</h3>
      <p className="muted">
        Product historian is Timescale. Optional analytics-result cache figures (files, bytes,
        compaction) are not telemetry and appear only when Central reports them. Missing values
        stay unavailable rather than synthesized.
      </p>
      <div className="summary-grid">
        {metric(
          "Timescale",
          timescaleOk == null ? "Not reported" : timescaleOk ? "Connected" : "Not connected",
        )}
        {metric("Backend", historianBackend ?? "Not reported")}
        {metric(
          "Analytics cache files",
          historianFiles ?? "Not reported",
        )}
        {metric(
          "Analytics cache bytes",
          historianBytes ?? "Not reported",
        )}
        {metric(
          "Analytics cache small files",
          smallFiles ?? "Not reported",
        )}
        {metric(
          "Analytics cache compaction",
          timescaleOk
            ? "Not applicable (Timescale historian)"
            : compaction ?? "Not reported",
        )}
      </div>

      <h3>Recent AFDD cycles</h3>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Finished</th><th>Scope</th><th>Trigger</th><th>Window</th><th>Rules</th><th>Status</th></tr>
          </thead>
          <tbody>
            {recent.length === 0 ? (
              <tr><td colSpan={6}>No AFDD cycles recorded in this Central process yet.</td></tr>
            ) : recent.map((cycle) => (
              <tr key={`${cycle.finished_at_utc}-${cycle.scope}-${cycle.trigger}`}>
                <td>{formatTime(cycle.finished_at_utc)}</td>
                <td>{cycle.scope}</td>
                <td>{cycle.trigger}{cycle.catch_up ? " · catch-up" : ""}</td>
                <td>{formatTime(cycle.start_utc)} → {formatTime(cycle.end_utc)}</td>
                <td>{cycle.rules_succeeded ?? 0}✓ / {cycle.rules_failed ?? 0}✗ / {cycle.rules_skipped ?? 0} skipped</td>
                <td>{cycleState(cycle)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Finding continuity</h3>
      <p className="muted">First/last-seen values are shown only when the current findings contract exposes them; the UI never invents continuity timestamps.</p>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Rule</th><th>Equipment</th><th>First seen</th><th>Last seen</th><th>Occurrences</th></tr></thead>
          <tbody>
            {continuityRows.length === 0 ? (
              <tr><td colSpan={5}>Current findings do not expose first/last-seen continuity fields.</td></tr>
            ) : continuityRows.map((row) => (
              <tr
                key={`${row.rule_id ?? "rule"}-${row.equipment_id ?? "equipment"}-${String(row.first_seen_utc ?? row.first_seen ?? "")}-${String(row.last_seen_utc ?? row.last_seen ?? "")}-${String(row.continuity_count ?? row.occurrences ?? "")}`}
              >
                <td>{row.rule_id ?? "—"}</td>
                <td>{row.equipment_id ?? "—"}</td>
                <td>{formatTime(row.first_seen_utc ?? row.first_seen)}</td>
                <td>{formatTime(row.last_seen_utc ?? row.last_seen)}</td>
                <td>{row.continuity_count ?? row.occurrences ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}



export function OperationsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawView = searchParams.get("view");
  const view: OperationsView =
    rawView === "afdd" || rawView === "sites" || rawView === "providers"
      ? (rawView as OperationsView)
      : "providers";

  const setView = (next: OperationsView) => {
    const params = new URLSearchParams(searchParams);
    if (next === "providers") params.delete("view");
    else params.set("view", next);
    if (rawView === "mqtt") params.delete("protocol");
    setSearchParams(params, { replace: true });
  };

  return (
    <AppShell
      title="Operations"
      activeSectionId="operations"
    >
      <fieldset className="section-tabs" aria-label="Operations configuration">
        <legend className="sr-only">Operations configuration</legend>
        <label>
          <input
            type="radio"
            name="operations-view"
            value="providers"
            checked={view === "providers"}
            onChange={() => setView("providers")}
            data-testid="operations-view-providers"
          />
          Providers
        </label>
        <label>
          <input
            type="radio"
            name="operations-view"
            value="sites"
            checked={view === "sites"}
            onChange={() => setView("sites")}
            data-testid="operations-view-sites"
          />
          Sites
        </label>
        <label>
          <input
            type="radio"
            name="operations-view"
            value="afdd"
            checked={view === "afdd"}
            onChange={() => setView("afdd")}
            data-testid="operations-view-afdd"
          />
          AFDD Config
        </label>
      </fieldset>
      {view === "providers" ? (
        <ProvidersPanel />
      ) : view === "sites" ? (
        <SitesPanel />
      ) : (
        <AfddPanel />
      )}
    </AppShell>
  );
}
