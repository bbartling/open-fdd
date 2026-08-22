import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import { AppShell } from "../components/AppShell";
import { Button } from "../components/widgets";

type OperationsView = "afdd" | "mqtt";

type AfddMode = "bulk" | "continuous";

interface AfddConfig {
  mode: AfddMode;
  interval_minutes: number;
  lookback_value: number;
  lookback_unit: "minutes" | "hours" | "days";
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
  last_error?: string | null;
  recent_cycles: AfddCycleRecord[];
  error?: string;
}

interface AfddRunNowResponse {
  ok: boolean;
  cycle?: AfddCycleRecord;
  error?: string;
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

function AfddPanel() {
  const [status, setStatus] = useState<AfddSchedulerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await apiFetch<AfddSchedulerStatus>("/api/afdd/scheduler/status");
      setStatus(next);
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

  const recent = status?.recent_cycles ?? [];
  const latestCycle = recent[0];
  const config = status?.config;

  return (
    <section aria-labelledby="afdd-config-heading" data-testid="afdd-config-panel">
      <div className="section-heading-row">
        <div>
          <h2 id="afdd-config-heading">AFDD Scheduler</h2>
          <p className="muted">
            Deployment-backed scheduler settings are read-only here. Run Now uses the same H8 execution engine as scheduled cycles.
          </p>
        </div>
        <div className="button-row">
          <Button id="afdd-refresh" label="Refresh" variant="secondary" loading={loading} onClick={() => void refresh()} />
          <Button id="afdd-run-now" label="Run AFDD now" loading={running} onClick={() => void runNow()} />
        </div>
      </div>

      {error ? <div className="inline-alert inline-alert--error" role="alert">{error}</div> : null}

      <div className="summary-grid">
        {metric("Mode", config?.mode ?? "—")}
        {metric("Frequency", config ? `${config.interval_minutes} min` : "—")}
        {metric("Rolling lookback", config ? `${config.lookback_value} ${config.lookback_unit}` : "—")}
        {metric("Latest historian sample", formatTime(status?.latest_persisted_telemetry_utc))}
        {metric("Analyzed through", formatTime(status?.checkpoint?.analyzed_through_utc))}
        {metric("Last completed", formatTime(status?.checkpoint?.last_completed_at_utc))}
        {metric("Next due", config?.mode === "continuous" ? formatTime(status?.next_due_at_utc) : "Bulk mode")}
        {metric("Catch-up", latestCycle?.catch_up ? "Yes" : "No")}
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Finished</th>
              <th>Scope</th>
              <th>Trigger</th>
              <th>Window</th>
              <th>Rules</th>
              <th>Status</th>
            </tr>
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
                <td>{cycle.ok ? "Success" : cycle.error ?? "Failed"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function validTopicFilter(value: string): boolean {
  if (!value.trim()) return false;
  const levels = value.split("/");
  return levels.every((level, index) => {
    if (level.includes("#")) return level === "#" && index === levels.length - 1;
    if (level.includes("+")) return level === "+";
    return true;
  });
}

function MqttPanel() {
  const [topicFilter, setTopicFilter] = useState("openfdd/+/+/telemetry/#");
  const filterOk = useMemo(() => validTopicFilter(topicFilter), [topicFilter]);

  return (
    <section aria-labelledby="mqtt-config-heading" data-testid="mqtt-config-panel">
      <h2 id="mqtt-config-heading">MQTT Test Monitor</h2>
      <p className="muted">
        Read-only operator monitor by default. The browser never receives broker passwords, private keys, or raw deployment credentials and never connects directly to the broker.
      </p>

      <div className="summary-grid">
        {metric("Broker state", "Central monitor backend pending")}
        {metric("Publish capability", "Disabled by default")}
        {metric("Observation buffer", "Bounded")}
        {metric("Transport", "Authenticated Central API")}
      </div>

      <div className="form-row">
        <label htmlFor="mqtt-topic-filter">Topic filter</label>
        <input
          id="mqtt-topic-filter"
          value={topicFilter}
          onChange={(event) => setTopicFilter(event.target.value)}
          aria-invalid={!filterOk}
          placeholder="openfdd/+/+/telemetry/#"
        />
        <span>{filterOk ? "Valid MQTT topic filter" : "Use + for one level and # only as the final level"}</span>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Received</th><th>Topic</th><th>QoS</th><th>Retain</th><th>Bytes</th><th>Payload</th></tr>
          </thead>
          <tbody>
            <tr><td colSpan={6}>Live bounded message observation wiring is the next H9 backend slice.</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function OperationsPage() {
  const [view, setView] = useState<OperationsView>("afdd");

  return (
    <AppShell
      title="Operations"
      caption="AFDD scheduler and MQTT operator tooling"
      activeSectionId="operations"
    >
      <fieldset className="section-tabs" aria-label="Operations configuration">
        <legend className="sr-only">Operations configuration</legend>
        <label>
          <input type="radio" name="operations-view" value="afdd" checked={view === "afdd"} onChange={() => setView("afdd")} />
          AFDD Config
        </label>
        <label>
          <input type="radio" name="operations-view" value="mqtt" checked={view === "mqtt"} onChange={() => setView("mqtt")} />
          MQTT Config
        </label>
      </fieldset>
      {view === "afdd" ? <AfddPanel /> : <MqttPanel />}
    </AppShell>
  );
}
