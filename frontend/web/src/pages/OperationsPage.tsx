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

interface MqttObservedMessage {
  received_at_utc: string;
  topic: string;
  qos: string;
  retain: boolean;
  payload_bytes: number;
  payload_encoding: "json" | "text" | "hex" | string;
  payload_preview: string;
  truncated: boolean;
}

interface MqttMonitorEvent {
  at_utc: string;
  kind: string;
  message: string;
}

interface MqttMonitorSnapshot {
  connected: boolean;
  client_id?: string | null;
  subscriptions: string[];
  received_messages: number;
  reconnects: number;
  errors: number;
  buffer_capacity: number;
  recent_messages: MqttObservedMessage[];
  recent_events: MqttMonitorEvent[];
  test_publish_enabled: boolean;
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
  const [continuity, setContinuity] = useState<FddContinuityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [next, historianSummary, results] = await Promise.all([
        apiFetch<AfddSchedulerStatus>("/api/afdd/scheduler/status"),
        apiFetch<Record<string, unknown>>("/api/data-management/summary").catch(() => null),
        apiFetch<FddResultsResponse>("/api/fdd/results").catch(() => null),
      ]);
      setStatus(next);
      setHistorian(historianSummary);
      setContinuity(results?.results ?? []);
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
            Deployment-backed scheduler settings are read-only here. Run Now uses the same H8 execution engine as scheduled cycles.
          </p>
        </div>
        <div className="button-row">
          <Button id="afdd-refresh" label="Refresh" variant="secondary" loading={loading} onClick={() => void refresh()} />
          <Button id="afdd-run-now" label="Run AFDD now" loading={running} onClick={() => void runNow()} />
        </div>
      </div>

      {error ? <div className="inline-alert inline-alert--error" role="alert">{error}</div> : null}
      {status?.last_error ? <div className="inline-alert inline-alert--error" role="status">Last scheduler error: {status.last_error}</div> : null}

      <div className="summary-grid">
        {metric("Mode", config?.mode ?? "—")}
        {metric("Frequency", config ? `${config.interval_minutes} min` : "—")}
        {metric("Rolling lookback", config ? `${config.lookback_value} ${config.lookback_unit}` : "—")}
        {metric("Latest historian sample", formatTime(status?.latest_persisted_telemetry_utc))}
        {metric("BAS freshness", basFreshness(status?.latest_persisted_telemetry_utc))}
        {metric("Analyzed through", formatTime(status?.checkpoint?.analyzed_through_utc))}
        {metric("Last completed", formatTime(status?.checkpoint?.last_completed_at_utc))}
        {metric("Next due", config?.mode === "continuous" ? formatTime(status?.next_due_at_utc) : "Bulk mode")}
        {metric("Catch-up", latestCycle?.catch_up ? "Yes" : "No")}
      </div>

      <h3>Historian health</h3>
      <p className="muted">Read-only values from Central data-management health. Missing values are reported as unavailable rather than synthesized.</p>
      <div className="summary-grid">
        {metric("Backend", historianBackend ?? "Not reported")}
        {metric("Files / parts", historianFiles ?? "Not reported")}
        {metric("Bytes", historianBytes ?? "Not reported")}
        {metric("Small files", smallFiles ?? "Not reported")}
        {metric("Compaction", compaction ?? "Not reported")}
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
            ) : continuityRows.map((row, index) => (
              <tr key={`${row.rule_id ?? "rule"}-${row.equipment_id ?? "equipment"}-${index}`}>
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

function validTopicFilter(value: string): boolean {
  if (!value.trim()) return false;
  const levels = value.split("/");
  return levels.every((level, index) => {
    if (level.includes("#")) return level === "#" && index === levels.length - 1;
    if (level.includes("+")) return level === "+";
    return true;
  });
}

function topicMatchesFilter(topic: string, filter: string): boolean {
  if (!validTopicFilter(filter)) return false;
  const topicLevels = topic.split("/");
  const filterLevels = filter.split("/");
  for (let index = 0; index < filterLevels.length; index += 1) {
    const expected = filterLevels[index];
    if (expected === "#") return true;
    if (index >= topicLevels.length) return false;
    if (expected !== "+" && expected !== topicLevels[index]) return false;
  }
  return topicLevels.length === filterLevels.length;
}

interface IngestStats {
  ok?: boolean;
  ingest_ok?: number;
  ingest_dup?: number;
  ingest_reject?: number;
  dead_letters?: number;
}

interface EdgesListResponse {
  ok?: boolean;
  edges?: Array<{ edge_id: string; site_id?: string | null; has_telemetry?: boolean }>;
}

function OtStatusStrip() {
  const [mqtt, setMqtt] = useState<MqttMonitorSnapshot | null>(null);
  const [ingest, setIngest] = useState<IngestStats | null>(null);
  const [edges, setEdges] = useState<EdgesListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextMqtt, nextIngest, nextEdges] = await Promise.all([
        apiFetch<MqttMonitorSnapshot>("/api/mqtt/monitor"),
        apiFetch<IngestStats>("/api/ingest/stats").catch(() => null),
        apiFetch<EdgesListResponse>("/api/edges").catch(() => null),
      ]);
      setMqtt(nextMqtt);
      setIngest(nextIngest);
      setEdges(nextEdges);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const liveEdges = (edges?.edges ?? []).filter((edge) => edge.has_telemetry).length;

  return (
    <div className="ops-ot-strip" data-testid="ops-ot-strip" role="status" aria-live="polite">
      <div className="ops-ot-strip__item">
        <span className="ops-ot-strip__label">MQTT</span>
        <span className={`ops-ot-strip__value${mqtt?.connected ? " ops-ot-strip__value--ok" : " ops-ot-strip__value--bad"}`}>
          {mqtt ? (mqtt.connected ? "Connected" : "Disconnected") : "—"}
        </span>
      </div>
      <div className="ops-ot-strip__item">
        <span className="ops-ot-strip__label">Ingest OK</span>
        <span className="ops-ot-strip__value">{ingest?.ingest_ok != null ? String(ingest.ingest_ok) : "—"}</span>
      </div>
      <div className="ops-ot-strip__item">
        <span className="ops-ot-strip__label">Rejects</span>
        <span className="ops-ot-strip__value">{ingest?.ingest_reject != null ? String(ingest.ingest_reject) : "—"}</span>
      </div>
      <div className="ops-ot-strip__item">
        <span className="ops-ot-strip__label">Edges w/ telemetry</span>
        <span className="ops-ot-strip__value">{edges ? String(liveEdges) : "—"}</span>
      </div>
      <div className="ops-ot-strip__item">
        <span className="ops-ot-strip__label">Monitor msgs</span>
        <span className="ops-ot-strip__value">{mqtt ? String(mqtt.received_messages) : "—"}</span>
      </div>
      {error ? (
        <div className="ops-ot-strip__item">
          <span className="ops-ot-strip__label">Strip</span>
          <span className="ops-ot-strip__value ops-ot-strip__value--bad">{error}</span>
        </div>
      ) : null}
    </div>
  );
}

function MqttPanel() {
  const [topicFilter, setTopicFilter] = useState("openfdd/#");
  const [snapshot, setSnapshot] = useState<MqttMonitorSnapshot | null>(null);
  /** Off by default — cell-modem / bandwidth: no polling until Start listening. */
  const [listening, setListening] = useState(false);
  const [paused, setPaused] = useState(false);
  /** Live console default 1s while listening; slower options for cell-modem. */
  const [pollMs, setPollMs] = useState(1000);
  const [clearedAt, setClearedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const filterOk = useMemo(() => validTopicFilter(topicFilter), [topicFilter]);

  const refresh = useCallback(async () => {
    try {
      const next = await apiFetch<MqttMonitorSnapshot>("/api/mqtt/monitor");
      setSnapshot(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (!listening || paused) return undefined;
    void refresh();
    const timer = window.setInterval(() => void refresh(), pollMs);
    return () => window.clearInterval(timer);
  }, [listening, paused, pollMs, refresh]);

  const messages = useMemo(() => {
    const cutoff = clearedAt ?? Number.NEGATIVE_INFINITY;
    return (snapshot?.recent_messages ?? []).filter((message) => {
      const received = Date.parse(message.received_at_utc);
      return received > cutoff && filterOk && topicMatchesFilter(message.topic, topicFilter);
    });
  }, [clearedAt, filterOk, snapshot?.recent_messages, topicFilter]);

  return (
    <section aria-labelledby="mqtt-config-heading" data-testid="mqtt-config-panel">
      <div className="section-heading-row">
        <div>
          <h2 id="mqtt-config-heading">MQTT Test Client</h2>
          <p className="muted">
            AWS IoT–style operator monitor: subscribe filter, live truncated payload feed, connection events.
            Browser uses authenticated Central API snapshots (not broker credentials). Listening is off by
            default and throttled for cell-modem sites. Full WSS-to-broker is optional later; production path
            remains fieldbus → MQTTS → central ingest.
          </p>
        </div>
        <div className="button-row">
          <Button
            id="mqtt-listen"
            label={listening ? "Stop listening" : "Start listening"}
            variant={listening ? "secondary" : "primary"}
            onClick={() => {
              setListening((value) => !value);
              if (!listening) setPaused(false);
            }}
          />
          <Button
            id="mqtt-pause"
            label={paused ? "Resume display" : "Pause display"}
            variant="secondary"
            onClick={() => setPaused((value) => !value)}
            disabled={!listening}
          />
          <Button id="mqtt-clear" label="Clear local view" variant="secondary" onClick={() => setClearedAt(Date.now())} />
          <Button id="mqtt-refresh" label="Refresh once" variant="secondary" onClick={() => void refresh()} />
        </div>
      </div>

      {error ? <div className="inline-alert inline-alert--error" role="alert">{error}</div> : null}

      <div className="form-row">
        <label htmlFor="mqtt-poll-ms">Poll interval (cell-aware)</label>
        <select
          id="mqtt-poll-ms"
          value={pollMs}
          onChange={(event) => setPollMs(Number(event.target.value))}
        >
          <option value={1000}>1 s (live)</option>
          <option value={2000}>2 s</option>
          <option value={5000}>5 s</option>
          <option value={10000}>10 s</option>
          <option value={30000}>30 s (cell)</option>
        </select>
        <span>{listening ? (paused ? "Display paused" : `Polling every ${pollMs / 1000}s`) : "Not listening — no background traffic"}</span>
      </div>

      <div className="summary-grid">
        {metric("Broker state", snapshot?.connected ? "Connected" : "Disconnected")}
        {metric("Client identity", snapshot?.client_id ?? "—")}
        {metric("Messages observed", String(snapshot?.received_messages ?? 0))}
        {metric("Reconnects", String(snapshot?.reconnects ?? 0))}
        {metric("Errors", String(snapshot?.errors ?? 0))}
        {metric("Observation buffer", snapshot ? `${snapshot.recent_messages.length}/${snapshot.buffer_capacity}` : "—")}
        {metric("Subscriptions", String(snapshot?.subscriptions.length ?? 0))}
        {metric("Publish capability", snapshot?.test_publish_enabled ? "Enabled" : "Disabled")}
      </div>

      <div className="form-row">
        <label htmlFor="mqtt-topic-filter">Topic filter</label>
        <input
          id="mqtt-topic-filter"
          value={topicFilter}
          onChange={(event) => setTopicFilter(event.target.value)}
          aria-invalid={!filterOk}
          placeholder="openfdd/v1/sites/<site>/#"
        />
        <span>{filterOk ? `${messages.length} buffered messages match` : "Use + for one level and # only as the final level"}</span>
      </div>

      <details>
        <summary>Central subscriptions</summary>
        <ul>
          {(snapshot?.subscriptions ?? []).map((subscription) => <li key={subscription}><code>{subscription}</code></li>)}
        </ul>
      </details>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Received</th><th>Topic</th><th>QoS</th><th>Retain</th><th>Bytes</th><th>Payload</th></tr>
          </thead>
          <tbody>
            {messages.length === 0 ? (
              <tr>
                <td colSpan={6}>
                  {!listening
                    ? "Start listening to pull bounded observation snapshots."
                    : paused
                      ? "Display paused."
                      : "No buffered messages match the current filter."}
                </td>
              </tr>
            ) : messages.map((message) => (
              <tr key={`${message.received_at_utc}-${message.topic}-${message.payload_bytes}`}>
                <td>{formatTime(message.received_at_utc)}</td>
                <td><code>{message.topic}</code></td>
                <td>{message.qos}</td>
                <td>{message.retain ? "Yes" : "No"}</td>
                <td>{message.payload_bytes}</td>
                <td>
                  <details>
                    <summary>{message.payload_encoding}{message.truncated ? " · truncated" : ""}</summary>
                    <pre>{message.payload_preview}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Connection and error events</h3>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Time</th><th>Kind</th><th>Event</th></tr></thead>
          <tbody>
            {(snapshot?.recent_events ?? []).length === 0 ? (
              <tr><td colSpan={3}>No connection events recorded yet.</td></tr>
            ) : snapshot?.recent_events.map((event) => (
              <tr key={`${event.at_utc}-${event.kind}-${event.message}`}>
                <td>{formatTime(event.at_utc)}</td><td>{event.kind}</td><td>{event.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TelemetrySuspendPanel() {
  const [siteId, setSiteId] = useState("local");
  const [edgeId, setEdgeId] = useState("fieldbus-1");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const issue = useCallback(
    async (action: "suspend" | "resume") => {
      if (
        action === "suspend" &&
        !window.confirm(
          `Suspend telemetry for site=${siteId} edge=${edgeId}?\n\nStops BACnet poll, weather fetch, and MQTT publish. Hosted BACnet server stays up.`,
        )
      ) {
        return;
      }
      setBusy(true);
      setError(null);
      setMessage(null);
      try {
        const body = await apiFetch<{
          ok: boolean;
          published?: boolean;
          command?: { command_id: string };
          hint?: string;
          error?: string;
        }>("/api/commands", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            site_id: siteId,
            edge_id: edgeId,
            target_id: "edge:telemetry",
            approved_by: "operations-ui",
            value: { action },
            ttl_secs: 120,
          }),
        });
        if (!body.ok) {
          throw new Error(body.error ?? "command rejected");
        }
        const commandId = body.command?.command_id;
        let ackDetail = body.published ? "published" : body.hint ?? "stored pending";
        if (commandId) {
          for (let i = 0; i < 8; i += 1) {
            await new Promise((r) => window.setTimeout(r, 750));
            try {
              const ack = await apiFetch<{
                ok: boolean;
                ack?: { status?: string; detail?: string };
              }>(`/api/commands/${commandId}/ack`);
              if (ack.ack?.status) {
                ackDetail = `${ack.ack.status}${ack.ack.detail ? ` · ${ack.ack.detail}` : ""}`;
                if (["executed", "failed", "rejected", "expired"].includes(ack.ack.status)) {
                  break;
                }
              }
            } catch {
              /* keep waiting */
            }
          }
        }
        setMessage(`${action} → ${ackDetail}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [edgeId, siteId],
  );

  return (
    <section aria-labelledby="telemetry-suspend-heading" data-testid="telemetry-suspend-panel">
      <div className="section-heading-row">
        <div>
          <h2 id="telemetry-suspend-heading">Suspend telemetry</h2>
          <p className="muted">
            Per site/edge: stop BACnet client poll, weather fetch, and MQTT publish. Hosted BACnet server
            stays up so the edge remains discoverable. Resume restores poll + weather + publish.
          </p>
        </div>
        <div className="button-row">
          <Button
            id="telemetry-suspend"
            label="Suspend telemetry"
            variant="secondary"
            disabled={busy}
            onClick={() => void issue("suspend")}
          />
          <Button
            id="telemetry-resume"
            label="Resume telemetry"
            variant="primary"
            disabled={busy}
            onClick={() => void issue("resume")}
          />
        </div>
      </div>
      {error ? <div className="inline-alert inline-alert--error" role="alert">{error}</div> : null}
      {message ? <div className="inline-alert" role="status">{message}</div> : null}
      <div className="form-row">
        <label htmlFor="telemetry-site-id">Site id</label>
        <input id="telemetry-site-id" value={siteId} onChange={(e) => setSiteId(e.target.value)} />
        <label htmlFor="telemetry-edge-id">Edge id</label>
        <input id="telemetry-edge-id" value={edgeId} onChange={(e) => setEdgeId(e.target.value)} />
      </div>
    </section>
  );
}

export function OperationsPage() {
  const [view, setView] = useState<OperationsView>("mqtt");

  return (
    <AppShell
      title="Operations"
      caption="OT strip, MQTT live console, AFDD scheduler — Sites stays inventory; this tab is not nested under Sites."
      activeSectionId="operations"
    >
      <OtStatusStrip />
      <fieldset className="section-tabs" aria-label="Operations configuration">
        <legend className="sr-only">Operations configuration</legend>
        <label>
          <input type="radio" name="operations-view" value="mqtt" checked={view === "mqtt"} onChange={() => setView("mqtt")} />
          MQTT Test Client
        </label>
        <label>
          <input type="radio" name="operations-view" value="afdd" checked={view === "afdd"} onChange={() => setView("afdd")} />
          AFDD Config
        </label>
      </fieldset>
      {view === "afdd" ? <AfddPanel /> : (
        <>
          <MqttPanel />
          <TelemetrySuspendPanel />
        </>
      )}
    </AppShell>
  );
}
