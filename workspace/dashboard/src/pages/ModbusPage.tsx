import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { formatPollSampleAt } from "../lib/formatPollTime";
import ActionButton from "../components/ActionButton";
import ModbusPointsTree, { type ModbusDevice, type ModbusPoint } from "../components/ModbusPointsTree";
import ModbusTreeLegend from "../components/ModbusTreeLegend";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import { TabDebugPanel } from "../components/TabDebugPanel";

const POLL_INTERVALS = [
  { s: 60, label: "1 min" },
  { s: 300, label: "5 min" },
  { s: 600, label: "10 min" },
  { s: 900, label: "15 min" },
] as const;

export default function ModbusPage() {
  const [benchHintAvailable, setBenchHintAvailable] = useState(false);
  const benchDefaultsApplied = useRef(false);
  const [host, setHost] = useState("");
  const [port, setPort] = useState(502);
  const [unitId, setUnitId] = useState(1);
  const [address, setAddress] = useState(0);
  const [functionKind, setFunctionKind] = useState<"holding" | "input">("holding");
  const [decode, setDecode] = useState<"uint16" | "int16" | "uint32" | "int32" | "float32" | "raw">("uint16");
  const [scale, setScale] = useState(1);
  const [count, setCount] = useState(1);
  const [label, setLabel] = useState("register");
  const [units, setUnits] = useState("");
  const [pending, setPending] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
  const [driverDevices, setDriverDevices] = useState<ModbusDevice[]>([]);
  const [treeLoading, setTreeLoading] = useState(true);
  const [pollStatus, setPollStatus] = useState<{
    enabled_points?: number;
    samples?: number;
    at?: string;
    at_local_display?: string;
    error?: string;
  } | null>(null);
  const [selectedPointIds, setSelectedPointIds] = useState<Set<string>>(() => new Set());
  const [bulkPollPending, setBulkPollPending] = useState(false);
  const [pollOncePending, setPollOncePending] = useState(false);

  const loadDriverTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const res = await apiFetch<{ devices: ModbusDevice[]; bench_hint_available?: boolean }>(
        "/api/modbus/driver/tree",
      );
      setDriverDevices(res.devices ?? []);
      setBenchHintAvailable(Boolean(res.bench_hint_available));
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setTreeLoading(false);
    }
  }, []);

  const refreshPollStatus = useCallback(async () => {
    try {
      const st = await apiFetch<typeof pollStatus>("/api/modbus/poll/status");
      setPollStatus(st);
    } catch {
      /* optional */
    }
  }, []);

  useEffect(() => {
    loadDriverTree().catch((e) => setLoadError(String(e)));
    refreshPollStatus().catch(() => undefined);
  }, [loadDriverTree, refreshPollStatus]);

  useEffect(() => {
    if (!benchHintAvailable || benchDefaultsApplied.current) return;
    benchDefaultsApplied.current = true;
    setHost("127.0.0.1");
    setPort(5502);
    setAddress(100);
    setScale(0.1);
    setLabel("fake-temp");
    setUnits("degF");
  }, [benchHintAvailable]);

  useEffect(() => {
    const tick = window.setInterval(() => {
      void loadDriverTree();
      void refreshPollStatus();
    }, 20000);
    return () => window.clearInterval(tick);
  }, [loadDriverTree, refreshPollStatus]);

  function patchPointValue(pointId: string, presentValue: string) {
    setDriverDevices((prev) =>
      prev.map((dev) => ({
        ...dev,
        points: dev.points.map((p) =>
          p.point_id === pointId ? { ...p, present_value: presentValue } : p,
        ),
      })),
    );
  }

  async function runRead(store: boolean) {
    setPending(true);
    setActionError("");
    if (
      !Number.isInteger(port) ||
      port < 1 ||
      port > 65535 ||
      !Number.isInteger(unitId) ||
      unitId < 0 ||
      unitId > 255 ||
      !Number.isInteger(address) ||
      address < 0 ||
      address > 65535 ||
      !Number.isInteger(count) ||
      count < 1
    ) {
      const msg = "Invalid Modbus parameters — check port (1–65535), unit (0–255), address, and count.";
      setActionError(msg);
      setLog(msg);
      setPending(false);
      return;
    }
    setLog(`Reading ${functionKind} @ ${address} from ${host}:${port} (unit ${unitId})…`);
    try {
      const path = store ? "/api/modbus/read_and_store" : "/api/modbus/read_registers";
      const res = await apiFetch<{
        readings: { success: boolean; decoded?: number; error?: string }[];
        ingest?: { samples_appended?: number; feather_source?: string };
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
              scale: decode === "raw" ? undefined : scale,
              label,
            },
          ],
        }),
      });
      const ok = (res.readings ?? []).filter((r) => r.success).length;
      const stored = res.ingest?.samples_appended ?? 0;
      setLog(
        store
          ? `Read ${ok} register(s); appended ${stored} sample(s) (source=${res.ingest?.feather_source ?? "modbus"}).`
          : `Read ${ok} register(s) (not stored).`,
      );
      if (store) {
        await apiFetch("/api/modbus/registers", {
          method: "POST",
          body: JSON.stringify({
            host,
            port,
            unit_id: unitId,
            address,
            function: functionKind,
            count,
            decode,
            scale: decode === "raw" ? undefined : scale,
            label,
            units,
          }),
        });
        await loadDriverTree();
      }
    } catch (e) {
      const msg = formatApiError(e);
      setActionError(msg);
      setLog(msg);
    } finally {
      setPending(false);
    }
  }

  async function setPointPoll(pointId: string, enabled: boolean, intervalS: number) {
    setActionError("");
    try {
      await apiFetch("/api/modbus/register/poll", {
        method: "PATCH",
        body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
      });
      await loadDriverTree();
      setLog(`Poll ${enabled ? `every ${intervalS}s` : "stopped"} for ${pointId}`);
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function refreshPoint(device: ModbusDevice, point: ModbusPoint) {
    setActionError("");
    try {
      const res = await apiFetch<{ present_value?: string; value?: unknown }>("/api/modbus/refresh", {
        method: "POST",
        body: JSON.stringify({ point_id: point.point_id, store: false }),
      });
      const formatted = String(res.present_value ?? res.value ?? "—");
      patchPointValue(point.point_id, formatted);
      setLog(`Refresh ${point.label} @ ${device.host}:${device.port}: ${formatted}`);
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function refreshDevice(device: ModbusDevice) {
    setActionError("");
    setLog(`Refreshing ${device.points.length} register(s) on ${device.host}:${device.port}…`);
    for (const p of device.points) {
      await refreshPoint(device, p);
    }
    await loadDriverTree();
  }

  async function deletePoint(pointId: string) {
    if (!window.confirm("Remove this register from the driver?")) return;
    setActionError("");
    try {
      await apiFetch(`/api/modbus/register/${encodeURIComponent(pointId)}`, { method: "DELETE" });
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function deleteDevice(device: ModbusDevice) {
    if (!window.confirm(`Remove all registers on ${device.host}:${device.port}?`)) return;
    setActionError("");
    try {
      for (const p of device.points) {
        await apiFetch(`/api/modbus/register/${encodeURIComponent(p.point_id)}`, { method: "DELETE" });
      }
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function setDevicePoll(device: ModbusDevice, enabled: boolean, intervalS: number) {
    for (const p of device.points) {
      await setPointPoll(p.point_id, enabled, intervalS);
    }
  }

  function togglePointSelection(pointId: string, selected: boolean) {
    setSelectedPointIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(pointId);
      else next.delete(pointId);
      return next;
    });
  }

  function toggleDevicePointSelection(device: ModbusDevice, selected: boolean) {
    setSelectedPointIds((prev) => {
      const next = new Set(prev);
      for (const p of device.points) {
        if (selected) next.add(p.point_id);
        else next.delete(p.point_id);
      }
      return next;
    });
  }

  function toggleTypePointSelection(_device: ModbusDevice, _type: string, points: ModbusPoint[], selected: boolean) {
    setSelectedPointIds((prev) => {
      const next = new Set(prev);
      for (const p of points) {
        if (selected) next.add(p.point_id);
        else next.delete(p.point_id);
      }
      return next;
    });
  }

  function selectAllTreePoints() {
    const next = new Set<string>();
    for (const dev of driverDevices) {
      for (const p of dev.points) next.add(p.point_id);
    }
    setSelectedPointIds(next);
  }

  function clearPointSelection() {
    setSelectedPointIds(new Set());
  }

  async function batchSetPointPoll(pointIds: string[], enabled: boolean, intervalS: number) {
    if (!pointIds.length) return;
    setBulkPollPending(true);
    setLog(`Setting poll ${enabled ? `every ${intervalS}s` : "off"} for ${pointIds.length} register(s)…`);
    for (const pointId of pointIds) {
      try {
        await apiFetch("/api/modbus/register/poll", {
          method: "PATCH",
          body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
        });
      } catch (e) {
        setActionError(formatApiError(e));
        break;
      }
    }
    await loadDriverTree();
    setBulkPollPending(false);
    setLog(`Poll update complete for ${pointIds.length} register(s).`);
  }

  async function runPollOnce() {
    setPollOncePending(true);
    setActionError("");
    try {
      const res = await apiFetch<{ polled?: number; samples?: number; error?: string }>("/api/modbus/poll/once", {
        method: "POST",
      });
      setLog(`Poll once: ${res.polled ?? 0} register(s), ${res.samples ?? 0} sample(s).`);
      if (res.error) setActionError(res.error);
      await loadDriverTree();
      await refreshPollStatus();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPollOncePending(false);
    }
  }

  const selectedPointsList = Array.from(selectedPointIds);
  const anyPending = pending || bulkPollPending || pollOncePending;

  return (
    <div className="page page-wide modbus-page">
      <PageHeader
        title="Modbus commissioning"
        subtitle="TCP register reads with BACnet-style tree, polling, and refresh. Try the local fake sensor on port 5502."
      />
      <TabDebugPanel tab="modbus" />

      {pollStatus ? (
        <div className="panel">
          <h3 className="panel-title">Poll worker</h3>
          <div className="row row-spread" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
            <span className="badge poll-badge">{pollStatus.enabled_points ?? 0} register(s) polling</span>
            {pollStatus.at ? (
              <span className="muted">
                Last cycle: {formatPollSampleAt(pollStatus) ?? pollStatus.at}
                {pollStatus.samples != null ? ` — ${pollStatus.samples} sample(s)` : ""}
              </span>
            ) : (
              <span className="muted">No poll cycle completed yet</span>
            )}
            {pollStatus.error ? <span className="error">{pollStatus.error}</span> : null}
          </div>
          <div className="row" style={{ marginTop: "0.65rem", gap: "0.5rem" }}>
            <ActionButton
              secondary
              pending={pollOncePending}
              pendingLabel="Polling…"
              disabled={anyPending || (pollStatus.enabled_points ?? 0) === 0}
              onClick={() => void runPollOnce()}
            >
              Poll all now
            </ActionButton>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <h3 className="panel-title">Add register</h3>
        {benchHintAvailable ? (
          <p className="muted modbus-bench-hint">
            Local dev: start{" "}
            <code>./scripts/fake_modbus_temp_server.py --port 5502 --flatline 72.5</code> then use defaults below
            (addr 100, scale 0.1).
          </p>
        ) : null}
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
            <input id="mb-port" type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-unit">
              Unit ID
            </label>
            <input id="mb-unit" type="number" value={unitId} onChange={(e) => setUnitId(Number(e.target.value))} />
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
            <input id="mb-addr" type="number" value={address} onChange={(e) => setAddress(Number(e.target.value))} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="mb-scale">
              Scale
            </label>
            <input
              id="mb-scale"
              type="number"
              step="0.01"
              value={scale}
              onChange={(e) => setScale(Number(e.target.value))}
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
              Label (historian column)
            </label>
            <input id="mb-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
        </div>
        <div className="form-row-actions">
          <ActionButton pending={pending} pendingLabel="Reading…" disabled={anyPending} onClick={() => void runRead(false)}>
            Read once
          </ActionButton>
          <ActionButton pending={pending} pendingLabel="Reading…" disabled={anyPending} onClick={() => void runRead(true)}>
            Read &amp; store to historian
          </ActionButton>
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">Connections &amp; registers</h3>
        <ModbusTreeLegend />
        <div className="row row-spread" style={{ marginTop: "0.65rem" }}>
          <p className="muted" style={{ flex: 1, margin: 0 }}>
            Right-click for Refresh value (works with or without polling) and poll intervals. Check boxes for bulk
            poll setup — same pattern as BACnet.
          </p>
        </div>
        {driverDevices.length > 0 ? (
          <div className="bacnet-bulk-toolbar">
            <span className="muted">{selectedPointsList.length} register(s) selected</span>
            <button type="button" className="secondary-btn" onClick={selectAllTreePoints}>
              Select all
            </button>
            <button type="button" className="secondary-btn" onClick={clearPointSelection}>
              Clear selection
            </button>
            {POLL_INTERVALS.map((p) => (
              <ActionButton
                key={p.s}
                secondary
                pending={bulkPollPending}
                pendingLabel="Updating…"
                disabled={anyPending || selectedPointsList.length === 0}
                onClick={() => void batchSetPointPoll(selectedPointsList, true, p.s)}
              >
                Poll {p.label}
              </ActionButton>
            ))}
            <ActionButton
              secondary
              pending={bulkPollPending}
              pendingLabel="Stopping…"
              disabled={anyPending || selectedPointsList.length === 0}
              onClick={() => void batchSetPointPoll(selectedPointsList, false, 0)}
            >
              Stop polling
            </ActionButton>
          </div>
        ) : null}
        {treeLoading && driverDevices.length === 0 ? (
          <Spinner label="Loading Modbus driver tree…" />
        ) : (
          <ModbusPointsTree
            devices={driverDevices}
            selectedPointIds={selectedPointIds}
            onTogglePointSelection={togglePointSelection}
            onToggleDeviceSelection={toggleDevicePointSelection}
            onToggleTypeSelection={toggleTypePointSelection}
            onRefreshDevice={refreshDevice}
            onRefreshPoint={refreshPoint}
            onSetPointPoll={setPointPoll}
            onSetDevicePoll={setDevicePoll}
            onDeletePoint={deletePoint}
            onDeleteDevice={deleteDevice}
            onCopy={(text) => navigator.clipboard.writeText(text).catch(() => undefined)}
          />
        )}
        {treeLoading && driverDevices.length > 0 ? (
          <p className="muted">
            <Spinner label="Refreshing tree…" />
          </p>
        ) : null}
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
