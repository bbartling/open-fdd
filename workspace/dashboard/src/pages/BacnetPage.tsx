import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import ActionButton from "../components/ActionButton";
import BacnetPointsTree, { type DriverDevice, type DriverPoint } from "../components/BacnetPointsTree";
import { formatBacnetValue, type PrioritySlot } from "../lib/bacnetTreeMenu";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import { TabDebugPanel } from "../components/TabDebugPanel";
import {
  extractPointDiscoveryObjects,
  extractWhoisDevices,
  parseDeviceInstanceFromWhoisRow,
  type PointDiscoveryObjectRow,
  type WhoisDeviceRow,
} from "../lib/bacnet-discovery-parse";
import { formatPollSampleAt } from "../lib/formatPollTime";

type BacnetConfig = {
  commission_agent_ok: boolean;
};

type CommissionStatus = {
  bacnet_bind?: string;
  discover_range?: [string, string];
};

type DiscoverJob = {
  job_id?: string;
  id?: string;
  status?: string;
  log_tail?: string;
  result?: unknown;
  error?: string;
};

type BatchRow = {
  instance: number;
  ok: boolean;
  objectCount?: number;
  error?: string;
};

async function waitForJob(jobId: string): Promise<DiscoverJob> {
  for (let i = 0; i < 120; i++) {
    const job = await apiFetch<DiscoverJob>(`/api/bacnet/jobs/${jobId}`);
    if (job.status && job.status !== "running") return job;
    await new Promise((r) => window.setTimeout(r, 1500));
  }
  throw new Error(`Job ${jobId} timed out`);
}

export default function BacnetPage() {
  const [cfg, setCfg] = useState<BacnetConfig | null>(null);
  const [status, setStatus] = useState<CommissionStatus | null>(null);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
  const [whoisLow, setWhoisLow] = useState(1);
  const [whoisHigh, setWhoisHigh] = useState(4194303);
  const [whoisPending, setWhoisPending] = useState(false);
  const [addPending, setAddPending] = useState(false);
  const [batchPending, setBatchPending] = useState(false);
  const [whoisDevices, setWhoisDevices] = useState<WhoisDeviceRow[]>([]);
  const [selectedInstances, setSelectedInstances] = useState<Set<number>>(new Set());
  const [discoveryPreview, setDiscoveryPreview] = useState<PointDiscoveryObjectRow[]>([]);
  const [batchSummary, setBatchSummary] = useState<BatchRow[] | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [driverDevices, setDriverDevices] = useState<DriverDevice[]>([]);
  const [treeLoading, setTreeLoading] = useState(true);
  const [pollStatus, setPollStatus] = useState<{
    enabled_points?: number;
    samples?: number;
    at?: string;
    at_local_display?: string;
    at_local?: string;
    at_utc?: string;
    site_timezone?: string;
    error?: string;
  } | null>(null);
  const [activeJobLabel, setActiveJobLabel] = useState("");
  const [priorityByPointId, setPriorityByPointId] = useState<Record<string, PrioritySlot[]>>({});
  const [expandedPriorityPoints, setExpandedPriorityPoints] = useState<Set<string>>(() => new Set());

  const loadDriverTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const res = await apiFetch<{ devices: DriverDevice[] }>("/api/bacnet/driver/tree");
      setDriverDevices(res.devices ?? []);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setTreeLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    const [c, s] = await Promise.all([
      apiFetch<BacnetConfig>("/config/bacnet"),
      apiFetch<CommissionStatus>("/api/bacnet/commission/status").catch(() => null),
    ]);
    setCfg(c);
    await loadDriverTree();
    if (s) {
      setStatus(s);
      if (s.discover_range?.length === 2) {
        setWhoisLow(Number(s.discover_range[0]) || 1);
        setWhoisHigh(Number(s.discover_range[1]) || 4194303);
      }
    }
  }, [loadDriverTree]);

  useEffect(() => {
    refresh().catch((e) => setLoadError(String(e)));
  }, [refresh]);

  useEffect(() => {
    const tick = window.setInterval(() => {
      void loadDriverTree();
      apiFetch<{ enabled_points?: number; samples?: number; at?: string; error?: string }>(
        "/api/bacnet/poll/status",
      )
        .then(setPollStatus)
        .catch(() => undefined);
    }, 20000);
    return () => window.clearInterval(tick);
  }, [loadDriverTree]);

  function toggleInstance(instance: number, checked: boolean) {
    setSelectedInstances((prev) => {
      const next = new Set(prev);
      if (checked) next.add(instance);
      else next.delete(instance);
      return next;
    });
  }

  function selectAllParsable() {
    const next = new Set<number>();
    for (const row of whoisDevices) {
      const inst = parseDeviceInstanceFromWhoisRow(row);
      if (inst != null) next.add(inst);
    }
    setSelectedInstances(next);
  }

  function whoisAddress(instance: number): string {
    const row = whoisDevices.find((r) => parseDeviceInstanceFromWhoisRow(r) === instance);
    return row ? String(row["device-address"] ?? "") : "";
  }

  function whoisDescription(instance: number): string {
    const row = whoisDevices.find((r) => parseDeviceInstanceFromWhoisRow(r) === instance);
    const raw = row ? String(row["device-description"] ?? "") : "";
    if (raw.startsWith("Error:")) return raw.replace(/^Error:\s*/, "");
    return raw;
  }

  async function syncDiscoveryToDriver(
    instance: number,
    address: string,
    objects: PointDiscoveryObjectRow[],
  ) {
    if (!objects.length) return { rows_added: 0 };
    return apiFetch<{ rows_added: number; total: number }>("/api/bacnet/driver/sync-discovery", {
      method: "POST",
      body: JSON.stringify({
        device_instance: instance,
        device_address: address,
        objects,
        replace: true,
      }),
    });
  }

  async function addDevice(
    instance: number,
    addressOverride = "",
    forceRefresh = false,
  ): Promise<BatchRow> {
    if (!forceRefresh && driverDevices.some((d) => d.device_instance === String(instance))) {
      return {
        instance,
        ok: false,
        error: `Device ${instance} is already in the tree — right-click → Refresh points to update.`,
      };
    }
    setActionError("");
    try {
      const addr = addressOverride || whoisAddress(instance);
      const res = await apiFetch<DiscoverJob>("/api/bacnet/point-discovery", {
        method: "POST",
        body: JSON.stringify({
          device_instance: instance,
          device_address: addr,
        }),
      });
      const jobId = res.job_id ?? res.id;
      if (!jobId) throw new Error("No job_id returned");
      const job = await waitForJob(jobId);
      const objects = extractPointDiscoveryObjects(job.result);
      const syncAddr =
        addr ||
        String((job.result as { device_address?: string } | undefined)?.device_address ?? "");
      let synced = 0;
      if (job.status === "ok" && objects.length) {
        const sync = await syncDiscoveryToDriver(instance, syncAddr, objects);
        synced = sync.rows_added ?? objects.length;
        await loadDriverTree();
      }
      setDiscoveryPreview(objects);
      if (job.status !== "ok") {
        const err = job.error || `Add device failed for ${instance}`;
        setActionError(err);
        return { instance, ok: false, objectCount: objects.length, error: err };
      }
      if (!objects.length) {
        const err = `Device ${instance} responded but returned 0 points — check segmentation / object-list support.`;
        setActionError(err);
        return { instance, ok: false, objectCount: 0, error: err };
      }
      setStatusMsg(`Device ${instance} added — ${objects.length} point(s)${synced ? ` (${synced} new)` : ""}.`);
      return { instance, ok: true, objectCount: objects.length };
    } catch (e) {
      const msg = formatApiError(e);
      setActionError(msg);
      return { instance, ok: false, error: msg };
    }
  }

  async function runAddDevice(instance: number, address = "", forceRefresh = false) {
    setAddPending(true);
    setActiveJobLabel(forceRefresh ? `Refreshing device ${instance}` : `Adding device ${instance}`);
    setLog(`Reading points from device ${instance}…`);
    setStatusMsg("");
    try {
      const row = await addDevice(instance, address, forceRefresh);
      setLog(
        row.ok
          ? `Device ${instance}: ${row.objectCount ?? 0} point(s) loaded.`
          : `Device ${instance}: ${row.error ?? "failed"}`,
      );
    } finally {
      setAddPending(false);
      setActiveJobLabel("");
    }
  }

  async function runBatchAddDevices(instances?: number[]) {
    const list = (instances ?? Array.from(selectedInstances)).sort((a, b) => a - b);
    if (!list.length) return;
    if (instances) setSelectedInstances(new Set(list));
    setBatchPending(true);
    setBatchSummary(null);
    setActionError("");
    setStatusMsg("");
    setLog(`Adding ${list.length} device(s)…`);
    const summary: BatchRow[] = [];
    for (let i = 0; i < list.length; i++) {
      setActiveJobLabel(`Adding device ${i + 1}/${list.length} (${list[i]})`);
      const row = await addDevice(list[i], whoisAddress(list[i]), false);
      summary.push(row);
      setBatchSummary([...summary]);
    }
    setBatchPending(false);
    setActiveJobLabel("");
    const ok = summary.filter((r) => r.ok).length;
    const pts = summary.reduce((n, r) => n + (r.objectCount ?? 0), 0);
    setLog(`Finished: ${ok}/${list.length} device(s), ${pts} total point(s).`);
    if (ok > 0) setStatusMsg(`Added ${ok} device(s) with ${pts} point(s). Right-click in tree to start polling.`);
  }

  async function runWhoIs() {
    setWhoisPending(true);
    setActionError("");
    setLog(`Who-Is ${whoisLow}–${whoisHigh}…`);
    try {
      const res = await apiFetch<unknown>("/api/bacnet/whois", {
        method: "POST",
        body: JSON.stringify({ range_low: whoisLow, range_high: whoisHigh }),
      });
      const devices = extractWhoisDevices(res);
      setWhoisDevices(devices);
      setSelectedInstances(new Set());
      setBatchSummary(null);
      setLog(
        devices.length
          ? `Found ${devices.length} device(s). Check rows and click Add device.`
          : "No I-Am responses — widen range or check BACnet bind / OT network.",
      );
    } catch (e) {
      const msg = formatApiError(e);
      setActionError(msg);
      setLog(msg);
    } finally {
      setWhoisPending(false);
    }
  }

  async function setPointPoll(pointId: string, enabled: boolean, intervalS: number) {
    setActionError("");
    try {
      const res = await apiFetch<{ model_sync?: { ok?: boolean; error?: string } }>("/api/bacnet/driver/point", {
        method: "PATCH",
        body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
      });
      if (res.model_sync?.ok === false && res.model_sync.error) {
        setActionError(res.model_sync.error);
      }
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function setDevicePoll(instance: number, enabled: boolean, intervalS: number) {
    setActionError("");
    try {
      await apiFetch("/api/bacnet/driver/device", {
        method: "PATCH",
        body: JSON.stringify({ device_instance: instance, enabled, poll_interval_s: intervalS }),
      });
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function deletePoint(pointId: string) {
    if (!window.confirm("Remove this point from the driver?")) return;
    setActionError("");
    try {
      await apiFetch(`/api/bacnet/driver/point/${encodeURIComponent(pointId)}`, { method: "DELETE" });
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function deleteDevice(instance: number) {
    if (!window.confirm(`Remove device ${instance} and all its points?`)) return;
    setActionError("");
    try {
      await apiFetch(`/api/bacnet/driver/device/${instance}`, { method: "DELETE" });
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function clearRegistry() {
    if (
      !window.confirm(
        "Clear ALL BACnet devices? This removes driver CSVs, poll samples, and BACnet rows from the data model. Sites and manually modeled equipment are kept.",
      )
    ) {
      return;
    }
    setActionError("");
    setStatusMsg("");
    try {
      const res = await apiFetch<{
        model?: { points_removed?: number; equipment_removed?: number };
      }>("/api/bacnet/driver/registry", { method: "DELETE" });
      await loadDriverTree();
      const m = res.model;
      setStatusMsg(
        m
          ? `Registry cleared — removed ${m.equipment_removed ?? 0} device(s) and ${m.points_removed ?? 0} point(s) from the data model.`
          : "BACnet registry cleared.",
      );
      setLog("BACnet driver registry cleared (CSV + data model synced).");
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function remapDevice(device: DriverDevice) {
    const newInstRaw = window.prompt(
      "Device instance (BACnet device ID)",
      device.device_instance,
    );
    if (newInstRaw == null) return;
    const newInst = Number(newInstRaw.trim());
    if (!Number.isFinite(newInst) || newInst < 0) {
      setActionError("Invalid device instance");
      return;
    }
    const newAddr = window.prompt("Device address (from Who-Is)", device.device_address || "");
    if (newAddr == null) return;
    setActionError("");
    try {
      await apiFetch("/api/bacnet/driver/device/remap", {
        method: "PATCH",
        body: JSON.stringify({
          device_instance: Number(device.device_instance),
          new_device_instance: newInst,
          new_device_address: newAddr.trim(),
        }),
      });
      await loadDriverTree();
      setStatusMsg(`Device remapped to instance ${newInst} @ ${newAddr.trim()}.`);
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function refreshDevicePoints(instance: number) {
    const dev = driverDevices.find((d) => d.device_instance === String(instance));
    await runAddDevice(instance, dev?.device_address ?? whoisAddress(instance), true);
  }

  function patchPointPresentValue(pointId: string, presentValue: string) {
    setDriverDevices((prev) =>
      prev.map((dev) => ({
        ...dev,
        points: dev.points.map((p) =>
          p.point_id === pointId ? { ...p, present_value: presentValue } : p,
        ),
      })),
    );
  }

  async function refreshPointPv(device: DriverDevice, point: DriverPoint) {
    setActionError("");
    try {
      const res = await apiFetch<{ value?: unknown }>("/api/bacnet/read", {
        method: "POST",
        body: JSON.stringify({
          device_instance: Number(device.device_instance),
          object_identifier: point.object_identifier,
          property_identifier: "present-value",
        }),
      });
      const formatted = formatBacnetValue(res.value);
      patchPointPresentValue(point.point_id, formatted);
      setLog(
        `Refresh PV ${point.object_identifier} @ device ${device.device_instance}: ${formatted}`,
      );
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function readPriorityArray(device: DriverDevice, point: DriverPoint) {
    if (!point.commandable) return;
    setActionError("");
    try {
      const res = await apiFetch<{ priority_array?: PrioritySlot[] }>("/api/bacnet/priority-array", {
        method: "POST",
        body: JSON.stringify({
          device_instance: Number(device.device_instance),
          object_identifier: point.object_identifier,
        }),
      });
      const slots = res.priority_array ?? [];
      setPriorityByPointId((prev) => ({ ...prev, [point.point_id]: slots }));
      setExpandedPriorityPoints((prev) => new Set(prev).add(point.point_id));
      setLog(
        `Priority array ${point.object_identifier} @ device ${device.device_instance}: ${slots.length} slot(s)`,
      );
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function selectAllAndAddDevices() {
    const list: number[] = [];
    const inTreeSet = new Set(driverDevices.map((d) => d.device_instance));
    for (const row of whoisDevices) {
      const inst = parseDeviceInstanceFromWhoisRow(row);
      if (inst != null && !inTreeSet.has(String(inst))) list.push(inst);
    }
    if (!list.length) {
      setActionError("All discovered devices are already in the tree.");
      return;
    }
    setSelectedInstances(new Set(list));
    await runBatchAddDevices(list);
  }

  const agentOk = cfg?.commission_agent_ok === true;
  const anyPending = whoisPending || addPending || batchPending;
  const selectedList = Array.from(selectedInstances).sort((a, b) => a - b);
  const inTree = new Set(driverDevices.map((d) => d.device_instance));

  return (
    <div className="page page-wide bacnet-page">
      <PageHeader
        title="BACnet commissioning"
        subtitle="Scan the network, add devices, then right-click in the tree to set poll rates (1 / 5 / 10 / 15 min)."
      />
      <TabDebugPanel tab="bacnet" />

      {pollStatus ? (
        <div className="panel">
          <div className="status-bar">
            <div className="status-kv">
              <span className="status-kv-label">Poll driver</span>
              <span className="status-kv-value">{pollStatus.enabled_points ?? 0} enabled point(s)</span>
            </div>
            {pollStatus.at || pollStatus.at_local || pollStatus.at_local_display ? (
              <div className="status-kv">
                <span className="status-kv-label">Last sample</span>
                <span className="status-kv-value">
                  {formatPollSampleAt(pollStatus)} ({pollStatus.samples ?? 0} values)
                  {pollStatus.at_utc ? (
                    <span className="muted" style={{ display: "block", fontSize: "0.85em" }}>
                      UTC {pollStatus.at_utc}
                    </span>
                  ) : null}
                </span>
              </div>
            ) : null}
            {pollStatus.error ? (
              <div className="status-kv">
                <span className="status-kv-label">Error</span>
                <span className="status-kv-value error">{pollStatus.error}</span>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {anyPending ? (
        <div className="bacnet-active-banner" role="status">
          <Spinner label={activeJobLabel || "BACnet operation in progress…"} />
        </div>
      ) : null}

      {statusMsg ? <p className="ok bacnet-model-msg">{statusMsg}</p> : null}

      <div className="panel">
        <h3 className="panel-title">Agent</h3>
        {loadError ? <p className="error">{loadError}</p> : null}
        {cfg ? (
          <div className="host-info-grid">
            <div>
              <span className="status-kv-label">Commission agent</span>
              <div className={agentOk ? "ok" : "error"}>{agentOk ? "running" : "down"}</div>
            </div>
            <div>
              <span className="status-kv-label">BACnet bind</span>
              <div>
                <code>{status?.bacnet_bind ?? "—"}</code>
              </div>
            </div>
            <div>
              <span className="status-kv-label">Devices in driver</span>
              <div>{driverDevices.length}</div>
            </div>
          </div>
        ) : (
          <Spinner label="Loading agent…" />
        )}
        <div className="toolbar">
          <button type="button" className="secondary-btn" onClick={() => refresh().catch((e) => setLoadError(String(e)))}>
            Refresh
          </button>
        </div>
      </div>

      <div className="panel">
        <h3 className="panel-title">Network scan</h3>
        <div className="form-row">
          <div className="field">
            <label className="field-label" htmlFor="whois-low">
              Who-Is start
            </label>
            <input
              id="whois-low"
              type="number"
              value={whoisLow}
              onChange={(e) => setWhoisLow(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="whois-high">
              Who-Is end
            </label>
            <input
              id="whois-high"
              type="number"
              value={whoisHigh}
              onChange={(e) => setWhoisHigh(Number(e.target.value))}
            />
          </div>
          <div className="form-row-actions">
            <ActionButton pending={whoisPending} pendingLabel="Scanning…" disabled={!agentOk || anyPending} onClick={runWhoIs}>
              Who-Is
            </ActionButton>
            <ActionButton
              pending={batchPending}
              pendingLabel={`Adding ${selectedList.length}…`}
              disabled={!agentOk || anyPending || selectedList.length === 0}
              onClick={() => runBatchAddDevices()}
            >
              Add devices ({selectedList.length} selected)
            </ActionButton>
            <ActionButton
              secondary
              pending={batchPending}
              pendingLabel="Adding all…"
              disabled={!agentOk || anyPending || whoisDevices.length === 0}
              onClick={selectAllAndAddDevices}
            >
              Select all & add all
            </ActionButton>
          </div>
        </div>

        {whoisDevices.length > 0 ? (
          <div className="bacnet-device-table-wrap">
            <div className="row">
              <span className="muted">{whoisDevices.length} device(s) on network</span>
              <button type="button" className="secondary-btn" onClick={selectAllParsable}>
                Select all
              </button>
              <button type="button" className="secondary-btn" onClick={() => setSelectedInstances(new Set())}>
                Clear
              </button>
            </div>
            <table className="bacnet-table">
              <thead>
                <tr>
                  <th>Use</th>
                  <th>Instance</th>
                  <th>Address</th>
                  <th>Name</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {whoisDevices.map((row, i) => {
                  const inst = parseDeviceInstanceFromWhoisRow(row);
                  const added = inst != null && inTree.has(String(inst));
                  return (
                    <tr key={`${row["i-am-device-identifier"] ?? i}`}>
                      <td>
                        <input
                          type="checkbox"
                          disabled={inst == null}
                          checked={inst != null && selectedInstances.has(inst)}
                          onChange={(e) => inst != null && toggleInstance(inst, e.target.checked)}
                        />
                      </td>
                      <td className="mono">{inst ?? "—"}</td>
                      <td className="mono">{String(row["device-address"] ?? "—")}</td>
                      <td>
                        {inst != null ? whoisDescription(inst) || "—" : "—"}
                      </td>
                      <td>
                        {inst != null ? (
                          <button
                            type="button"
                            className="secondary-btn"
                            disabled={!agentOk || anyPending}
                            onClick={() =>
                              runAddDevice(inst, whoisAddress(inst), added)
                            }
                          >
                            {added ? "Re-add" : "Add device"}
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          !whoisPending && <p className="muted">Run Who-Is to find BACnet devices on the network.</p>
        )}

        {batchSummary?.length ? (
          <ul className="batch-summary">
            {batchSummary.map((r) => (
              <li key={r.instance}>
                Device {r.instance}:{" "}
                {r.ok ? (
                  <span className="ok">{r.objectCount ?? 0} points</span>
                ) : (
                  <span className="error">{r.error ?? "failed"}</span>
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="panel">
        <h3 className="panel-title">Devices &amp; points</h3>
        <div className="row row-spread">
          <p className="muted" style={{ flex: 1, margin: 0 }}>
            Right-click for Actions (refresh PV, priority array) and Polling. Present value updates on demand or from poll.
          </p>
          <button
            type="button"
            className="danger-btn"
            disabled={anyPending || driverDevices.length === 0}
            onClick={() => void clearRegistry()}
          >
            Clear all devices
          </button>
        </div>
        {treeLoading && driverDevices.length === 0 ? (
          <Spinner label="Loading BACnet driver tree (large sites may take 30–60s)…" />
        ) : (
          <BacnetPointsTree
            devices={driverDevices}
            priorityByPointId={priorityByPointId}
            expandedPriorityPoints={expandedPriorityPoints}
            onRefreshDevice={refreshDevicePoints}
            onRefreshPointPv={refreshPointPv}
            onReadPriorityArray={readPriorityArray}
            onSetPointPoll={setPointPoll}
            onSetDevicePoll={setDevicePoll}
            onDeletePoint={deletePoint}
            onDeleteDevice={deleteDevice}
            onRemapDevice={remapDevice}
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
        {activeJobLabel ? <p className="muted"><Spinner label={activeJobLabel} /></p> : null}
        {actionError ? <p className="error">{actionError}</p> : null}
        <pre className="console">{log || "Ready."}</pre>
      </div>
    </div>
  );
}
