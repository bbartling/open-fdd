import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import ActionButton from "../components/ActionButton";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import { TabDebugPanel } from "../components/TabDebugPanel";

type ModbusReading = {
  address: number;
  function: string;
  success: boolean;
  decoded?: number | string | null;
  words?: number[] | null;
  label?: string | null;
  error?: string | null;
};

type ModbusRegister = {
  point_id: string;
  host: string;
  port: string;
  unit_id: string;
  address: string;
  function: string;
  label: string;
  units: string;
  enabled: string;
  poll_interval_s: string;
  last_value: string;
  last_read_at: string;
};

const POLL_INTERVALS = [
  { s: 60, label: "1 min" },
  { s: 300, label: "5 min" },
  { s: 600, label: "10 min" },
  { s: 900, label: "15 min" },
] as const;

export default function ModbusPage() {
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState(502);
  const [unitId, setUnitId] = useState(1);
  const [address, setAddress] = useState(0);
  const [functionKind, setFunctionKind] = useState<"holding" | "input">("holding");
  const [decode, setDecode] = useState<"uint16" | "int16" | "uint32" | "int32" | "float32" | "raw">("uint16");
  const [count, setCount] = useState(1);
  const [label, setLabel] = useState("register_0");
  const [pending, setPending] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
  const [readings, setReadings] = useState<ModbusReading[]>([]);
  const [ingest, setIngest] = useState<{ samples_appended?: number; feather_source?: string } | null>(null);
  const [registers, setRegisters] = useState<ModbusRegister[]>([]);
  const [registryLoading, setRegistryLoading] = useState(true);

  const loadRegisters = useCallback(async () => {
    setRegistryLoading(true);
    try {
      const res = await apiFetch<{ registers: ModbusRegister[] }>("/api/modbus/registers");
      setRegisters(res.registers ?? []);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setRegistryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRegisters().catch((e) => setLoadError(String(e)));
  }, [loadRegisters]);

  async function runRead(store: boolean) {
    setPending(true);
    setActionError("");
    setReadings([]);
    setIngest(null);
    setLog(`Reading ${functionKind} @ ${address} from ${host}:${port} (unit ${unitId})…`);
    try {
      const path = store ? "/api/modbus/read_and_store" : "/api/modbus/read_registers";
      const res = await apiFetch<{
        readings: ModbusReading[];
        ingest?: { samples_appended?: number; feather_source?: string; ok?: boolean; reason?: string };
      }>(path, {
        method: "POST",
        body: JSON.stringify({
          host,
          port,
          unit_id: unitId,
          timeout: 5,
          save_registers: store,
          registers: [
            {
              address,
              count: decode === "raw" ? count : Math.max(count, decode === "uint16" || decode === "int16" ? 1 : 2),
              function: functionKind,
              decode: decode === "raw" ? undefined : decode,
              label,
            },
          ],
        }),
      });
      setReadings(res.readings ?? []);
      if (res.ingest) setIngest(res.ingest);
      const ok = (res.readings ?? []).filter((r) => r.success).length;
      const stored = res.ingest?.samples_appended ?? 0;
      setLog(
        store
          ? `Read ${ok} register(s); appended ${stored} sample(s) to historian (source=${res.ingest?.feather_source ?? "modbus"}).`
          : `Read ${ok} register(s) (not stored).`,
      );
      if (store) await loadRegisters();
    } catch (e) {
      const msg = formatApiError(e);
      setActionError(msg);
      setLog(msg);
    } finally {
      setPending(false);
    }
  }

  async function setRegisterPoll(pointId: string, enabled: boolean, intervalS: number) {
    setActionError("");
    try {
      await apiFetch("/api/modbus/register/poll", {
        method: "PATCH",
        body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
      });
      await loadRegisters();
      setLog(`Poll ${enabled ? `every ${intervalS}s` : "stopped"} for ${pointId}`);
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  return (
    <div className="page page-wide modbus-page">
      <PageHeader
        title="Modbus commissioning"
        subtitle="Read holding/input registers over Modbus TCP. Store samples in the feather historian (source=modbus) like BACnet poll ingest."
      />
      <TabDebugPanel tab="modbus" />

      <div className="panel">
        <h3 className="panel-title">Read registers</h3>
        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="mb-host">
              Host
            </label>
            <input id="mb-host" value={host} onChange={(e) => setHost(e.target.value)} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-port">
              Port
            </label>
            <input
              id="mb-port"
              type="number"
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-unit">
              Unit ID
            </label>
            <input
              id="mb-unit"
              type="number"
              value={unitId}
              onChange={(e) => setUnitId(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-fn">
              Function
            </label>
            <select
              id="mb-fn"
              value={functionKind}
              onChange={(e) => setFunctionKind(e.target.value as "holding" | "input")}
            >
              <option value="holding">holding (FC3)</option>
              <option value="input">input (FC4)</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-addr">
              Address
            </label>
            <input
              id="mb-addr"
              type="number"
              value={address}
              onChange={(e) => setAddress(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-count">
              Count
            </label>
            <input
              id="mb-count"
              type="number"
              min={1}
              max={125}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-decode">
              Decode
            </label>
            <select id="mb-decode" value={decode} onChange={(e) => setDecode(e.target.value as typeof decode)}>
              <option value="uint16">uint16</option>
              <option value="int16">int16</option>
              <option value="uint32">uint32</option>
              <option value="int32">int32</option>
              <option value="float32">float32</option>
              <option value="raw">raw words</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-label">
              Label
            </label>
            <input id="mb-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
        </div>
        <div className="form-row-actions">
          <ActionButton pending={pending} pendingLabel="Reading…" onClick={() => void runRead(false)}>
            Read once
          </ActionButton>
          <ActionButton pending={pending} pendingLabel="Reading…" onClick={() => void runRead(true)}>
            Read &amp; store to historian
          </ActionButton>
        </div>
      </div>

      {readings.length > 0 ? (
        <div className="panel">
          <h3 className="panel-title">Last read</h3>
          <table className="bacnet-table">
            <thead>
              <tr>
                <th>Address</th>
                <th>Function</th>
                <th>Label</th>
                <th>Value</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {readings.map((r) => (
                <tr key={`${r.function}-${r.address}`}>
                  <td className="mono">{r.address}</td>
                  <td>{r.function}</td>
                  <td>{r.label ?? "—"}</td>
                  <td className="mono">
                    {r.decoded != null
                      ? String(r.decoded)
                      : r.words?.length
                        ? r.words.join(", ")
                        : "—"}
                  </td>
                  <td>{r.success ? <span className="ok">ok</span> : <span className="error">{r.error ?? "fail"}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {ingest ? (
            <p className="muted" style={{ marginTop: "0.75rem" }}>
              Historian: {ingest.samples_appended ?? 0} sample(s) written (source={ingest.feather_source ?? "modbus"}).
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="panel">
        <h3 className="panel-title">Register registry</h3>
        <p className="muted">
          Successful reads upsert rows here. Set poll intervals for future background polling (same CSV + feather path as BACnet).
        </p>
        {registryLoading && registers.length === 0 ? (
          <Spinner label="Loading Modbus registry…" />
        ) : registers.length === 0 ? (
          <p className="muted">No registers saved yet — use Read &amp; store.</p>
        ) : (
          <table className="bacnet-table">
            <thead>
              <tr>
                <th>Point</th>
                <th>Host</th>
                <th>Addr</th>
                <th>Last value</th>
                <th>Poll</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {registers.map((r) => {
                const polling = r.enabled === "1" || Number(r.poll_interval_s) > 0;
                return (
                  <tr key={r.point_id}>
                    <td>
                      <code>{r.point_id}</code>
                      <div className="muted">{r.label}</div>
                    </td>
                    <td className="mono">
                      {r.host}:{r.port} u{r.unit_id}
                    </td>
                    <td className="mono">
                      {r.function}@{r.address}
                    </td>
                    <td className="mono">
                      {r.last_value || "—"}
                      {r.last_read_at ? <div className="muted">{r.last_read_at}</div> : null}
                    </td>
                    <td>{polling ? <span className="badge poll-badge">⏱ {r.poll_interval_s}s</span> : <span className="badge muted-badge">idle</span>}</td>
                    <td>
                      <div className="row" style={{ gap: "0.35rem", flexWrap: "wrap" }}>
                        {POLL_INTERVALS.map((p) => (
                          <button
                            key={p.s}
                            type="button"
                            className="secondary-btn"
                            onClick={() => void setRegisterPoll(r.point_id, true, p.s)}
                          >
                            {p.label}
                          </button>
                        ))}
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => void setRegisterPoll(r.point_id, false, 0)}
                        >
                          Stop
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3>Activity</h3>
        {loadError ? <p className="error">{loadError}</p> : null}
        {actionError ? <p className="error">{actionError}</p> : null}
        <pre className="console">{log || "Ready."}</pre>
      </div>
    </div>
  );
}
