import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import ActionButton from "../components/ActionButton";
import BacnetPointsTree from "../components/BacnetPointsTree";
import Spinner from "../components/Spinner";
import {
  extractPointDiscoveryObjects,
  extractWhoisDevices,
  parseDeviceInstanceFromWhoisRow,
  type InventoryDevice,
  type PointDiscoveryObjectRow,
  type PointDiscoveryObjectRow,
  type WhoisDeviceRow,
} from "../lib/bacnet-discovery-parse";

type BacnetConfig = {
  points_exists: boolean;
  discovered_exists: boolean;
  poll_exists: boolean;
  commission_agent_ok: boolean;
};

type CommissionStatus = {
  bacnet_bind?: string;
  site_id?: string;
  building_id?: string;
  discover_range?: [string, string];
};

type DiscoverJob = {
  job_id?: string;
  id?: string;
  kind?: string;
  status?: string;
  exit_code?: number | null;
  log_tail?: string;
  result?: unknown;
  error?: string;
  device_instance?: number;
};

type BatchRow = {
  instance: number;
  ok: boolean;
  objectCount?: number;
  error?: string;
};

type LiveDevice = {
  device_instance: number;
  device_address?: string;
  objects: PointDiscoveryObjectRow[];
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
  const [inventory, setInventory] = useState<InventoryDevice[]>([]);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
  const [whoisLow, setWhoisLow] = useState(1);
  const [whoisHigh, setWhoisHigh] = useState(4194303);
  const [deviceInst, setDeviceInst] = useState(5007);
  const [whoisPending, setWhoisPending] = useState(false);
  const [discoverCsvPending, setDiscoverCsvPending] = useState(false);
  const [pointDiscoveryPending, setPointDiscoveryPending] = useState(false);
  const [batchPending, setBatchPending] = useState(false);
  const [whoisDevices, setWhoisDevices] = useState<WhoisDeviceRow[]>([]);
  const [selectedInstances, setSelectedInstances] = useState<Set<number>>(new Set());
  const [liveDevices, setLiveDevices] = useState<LiveDevice[]>([]);
  const [discoveryPreview, setDiscoveryPreview] = useState<PointDiscoveryObjectRow[]>([]);
  const [batchSummary, setBatchSummary] = useState<BatchRow[] | null>(null);
  const [batchGraphPending, setBatchGraphPending] = useState(false);
  const [modelMsg, setModelMsg] = useState("");
  const [activeJobLabel, setActiveJobLabel] = useState("");

  const refresh = useCallback(async () => {
    const [c, s, inv] = await Promise.all([
      apiFetch<BacnetConfig>("/config/bacnet"),
      apiFetch<CommissionStatus>("/api/bacnet/commission/status").catch(() => null),
      apiFetch<{ devices: InventoryDevice[] }>("/api/bacnet/inventory").catch(() => ({ devices: [] })),
    ]);
    setCfg(c);
    setInventory(inv.devices ?? []);
    if (s) {
      setStatus(s);
      if (s.discover_range?.length === 2) {
        setWhoisLow(Number(s.discover_range[0]) || 1);
        setWhoisHigh(Number(s.discover_range[1]) || 4194303);
      }
    }
  }, []);

  useEffect(() => {
    refresh().catch((e) => setLoadError(String(e)));
  }, [refresh]);

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
          ? `Who-Is found ${devices.length} device(s). Select rows for point discovery.`
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

  async function runDiscoverCsv() {
    setDiscoverCsvPending(true);
    setActionError("");
    setActiveJobLabel("CSV discover");
    setLog("Starting full discover → points_discovered.csv…");
    try {
      const res = await apiFetch<DiscoverJob>("/api/bacnet/discover", {
        method: "POST",
        body: JSON.stringify({ range_low: whoisLow, range_high: whoisHigh }),
      });
      const jobId = res.job_id ?? res.id;
      if (!jobId) throw new Error("No job_id returned");
      const job = await waitForJob(jobId);
      setLog(
        [
          `Discover job ${jobId} — ${job.status}`,
          job.log_tail ? `\n--- log ---\n${job.log_tail}` : "",
          job.error ? `\nERROR: ${job.error}` : "",
        ].join(""),
      );
      if (job.status !== "ok") setActionError(job.error || "Discover job failed");
      await refresh();
    } catch (e) {
      setActionError(formatApiError(e));
      setLog(formatApiError(e));
    } finally {
      setDiscoverCsvPending(false);
      setActiveJobLabel("");
    }
  }

  async function discoverDevice(instance: number): Promise<BatchRow> {
    setActionError("");
    try {
      const res = await apiFetch<DiscoverJob>("/api/bacnet/point-discovery", {
        method: "POST",
        body: JSON.stringify({ device_instance: instance }),
      });
      const jobId = res.job_id ?? res.id;
      if (!jobId) throw new Error("No job_id returned");
      const job = await waitForJob(jobId);
      const objects = extractPointDiscoveryObjects(job.result);
      setDiscoveryPreview(objects);
      setLiveDevices((prev) => {
        const rest = prev.filter((d) => d.device_instance !== instance);
        const addr = (job.result as { device_address?: string } | undefined)?.device_address;
        return [...rest, { device_instance: instance, device_address: addr, objects }];
      });
      if (job.status !== "ok") {
        setActionError(job.error || `Point discovery failed for ${instance}`);
      }
      return {
        instance,
        ok: job.status === "ok",
        objectCount: objects.length,
        error: job.error,
      };
    } catch (e) {
      const msg = formatApiError(e);
      setActionError(msg);
      return { instance, ok: false, error: msg };
    }
  }

  async function runPointDiscoveryFor(instance: number) {
    setPointDiscoveryPending(true);
    setActiveJobLabel(`Point discovery ${instance}`);
    setLog(`Point discovery for device ${instance}…`);
    try {
      const row = await discoverDevice(instance);
      setLog(
        row.ok
          ? `Device ${instance}: ${row.objectCount ?? 0} object(s)`
          : `Device ${instance} failed: ${row.error ?? "unknown"}`,
      );
    } finally {
      setPointDiscoveryPending(false);
      setActiveJobLabel("");
    }
  }

  async function runBatchPointDiscovery() {
    const list = Array.from(selectedInstances).sort((a, b) => a - b);
    if (!list.length) return;
    setBatchPending(true);
    setBatchSummary(null);
    setActionError("");
    setLog(`Batch point discovery for ${list.length} device(s)…`);
    const summary: BatchRow[] = [];
    for (let i = 0; i < list.length; i++) {
      setActiveJobLabel(`Point discovery ${i + 1}/${list.length} (device ${list[i]})`);
      const row = await discoverDevice(list[i]);
      summary.push(row);
      setBatchSummary([...summary]);
    }
    setBatchPending(false);
    setActiveJobLabel("");
    setLog(`Batch point discovery finished for ${list.length} device(s).`);
  }

  async function importDeviceToModel(
    instance: number,
    address: string,
    objects: PointDiscoveryObjectRow[],
  ) {
    setActionError("");
    setModelMsg(`Importing device ${instance} to data model…`);
    try {
      const body: Record<string, unknown> = {
        device_instance: instance,
        device_address: address,
      };
      if (objects.length) body.objects = objects;
      const res = await apiFetch<{ points_added: number; equipment_id: string }>(
        "/api/bacnet/import-to-model",
        { method: "POST", body: JSON.stringify(body) },
      );
      setModelMsg(
        `Added ${res.points_added} point(s) for device ${instance} → equipment ${res.equipment_id}. Open Data Model to tag BRICK types.`,
      );
    } catch (e) {
      setActionError(formatApiError(e));
      setModelMsg("");
    }
  }

  async function importPointToModel(instance: number, address: string, point: { id: string; name: string }) {
    await importDeviceToModel(instance, address, [
      { object_identifier: point.id, name: point.name, commandable: false },
    ]);
  }

  async function runBatchImportToModel() {
    const list = Array.from(selectedInstances).sort((a, b) => a - b);
    if (!list.length) return;
    setBatchGraphPending(true);
    setActionError("");
    setModelMsg(`Adding ${list.length} device(s) to data model…`);
    let total = 0;
    for (const inst of list) {
      const live = liveDevices.find((d) => d.device_instance === inst);
      const addr =
        live?.device_address ??
        whoisDevices.map(parseDeviceInstanceFromWhoisRow).includes(inst)
          ? String(whoisDevices.find((r) => parseDeviceInstanceFromWhoisRow(r) === inst)?.["device-address"] ?? "")
          : "";
      try {
        const body: Record<string, unknown> = {
          device_instance: inst,
          device_address: addr,
        };
        if (live?.objects?.length) body.objects = live.objects;
        const res = await apiFetch<{ points_added: number }>("/api/bacnet/import-to-model", {
          method: "POST",
          body: JSON.stringify(body),
        });
        total += res.points_added;
      } catch (e) {
        setActionError(formatApiError(e));
        break;
      }
    }
    setBatchGraphPending(false);
    if (total > 0) setModelMsg(`Added ${total} point(s) across ${list.length} device(s).`);
  }

  const agentOk = cfg?.commission_agent_ok === true;
  const anyPending =
    whoisPending || discoverCsvPending || pointDiscoveryPending || batchPending || batchGraphPending;
  const selectedList = Array.from(selectedInstances).sort((a, b) => a - b);

  return (
    <div className="bacnet-page">
      <h2 className="title">BACnet commissioning</h2>
      <p className="muted">
        Who-Is → select devices → point discovery → add to <Link to="/data-model">Data Model</Link>.
        Right-click devices or points in the tree for actions.
      </p>

      {anyPending ? (
        <div className="bacnet-active-banner" role="status">
          <Spinner label={activeJobLabel || "BACnet operation in progress…"} />
        </div>
      ) : null}

      {modelMsg ? <p className="ok bacnet-model-msg">{modelMsg}</p> : null}

      <div className="panel">
        <h3>Agent status</h3>
        {loadError ? <p className="error">{loadError}</p> : null}
        {cfg ? (
          <div className="host-info-grid">
            <div>
              <span className="muted">Commission agent</span>
              <div className={agentOk ? "ok" : "error"}>{agentOk ? "running" : "down"}</div>
            </div>
            <div>
              <span className="muted">BACnet bind</span>
              <div>
                <code>{status?.bacnet_bind ?? "—"}</code>
              </div>
            </div>
            <div>
              <span className="muted">CSV inventory</span>
              <div>{cfg.discovered_exists ? "points_discovered.csv ready" : "not yet"}</div>
            </div>
            <div>
              <span className="muted">Poll CSV</span>
              <div>{cfg.poll_exists ? "yes" : "no"}</div>
            </div>
          </div>
        ) : (
          <Spinner label="Loading agent…" />
        )}
        <div className="row">
          <button type="button" className="secondary-btn" onClick={() => refresh().catch((e) => setLoadError(String(e)))}>
            Refresh
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Step 1 — Discover devices</h3>
        <div className="form-row">
          <label>
            Who-Is start
            <input type="number" value={whoisLow} onChange={(e) => setWhoisLow(Number(e.target.value))} />
          </label>
          <label>
            end
            <input type="number" value={whoisHigh} onChange={(e) => setWhoisHigh(Number(e.target.value))} />
          </label>
          <ActionButton pending={whoisPending} pendingLabel="Who-Is…" disabled={!agentOk || anyPending} onClick={runWhoIs}>
            Who-Is
          </ActionButton>
          <ActionButton
            secondary
            pending={discoverCsvPending}
            pendingLabel="Discover CSV…"
            disabled={!agentOk || anyPending}
            onClick={runDiscoverCsv}
          >
            Discover → CSV
          </ActionButton>
        </div>

        {whoisDevices.length > 0 ? (
          <div className="bacnet-device-table-wrap">
            <div className="row">
              <span className="muted">{whoisDevices.length} device(s)</span>
              <button type="button" className="secondary-btn" onClick={selectAllParsable}>
                Select all parsable
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
                  <th>I-Am id</th>
                  <th>Address</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {whoisDevices.map((row, i) => {
                  const inst = parseDeviceInstanceFromWhoisRow(row);
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
                      <td className="mono">{row["i-am-device-identifier"] ?? "—"}</td>
                      <td className="mono">{String(row["device-address"] ?? "—")}</td>
                      <td>{String(row["device-description"] ?? "—")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          !whoisPending && <p className="muted">Run Who-Is to populate the device table.</p>
        )}
      </div>

      <div className="panel">
        <h3>Step 2 — Point discovery</h3>
        <div className="form-row">
          <label>
            Manual device instance
            <input type="number" value={deviceInst} onChange={(e) => setDeviceInst(Number(e.target.value))} />
          </label>
          <ActionButton
            pending={pointDiscoveryPending}
            pendingLabel="Discovering…"
            disabled={!agentOk || anyPending}
            onClick={() => runPointDiscoveryFor(deviceInst)}
          >
            Point discovery (manual)
          </ActionButton>
          <ActionButton
            secondary
            pending={batchPending}
            pendingLabel={`Batch ${selectedList.length}…`}
            disabled={!agentOk || anyPending || selectedList.length === 0}
            onClick={runBatchPointDiscovery}
          >
            Point discovery ({selectedList.length} selected)
          </ActionButton>
          <ActionButton
            pending={batchGraphPending}
            pendingLabel={`Import ${selectedList.length}…`}
            disabled={!agentOk || anyPending || selectedList.length === 0}
            onClick={runBatchImportToModel}
          >
            Add selected to data model ({selectedList.length})
          </ActionButton>
        </div>

        {batchSummary?.length ? (
          <ul className="batch-summary">
            {batchSummary.map((r) => (
              <li key={r.instance}>
                Device {r.instance}:{" "}
                {r.ok ? (
                  <span className="ok">{r.objectCount ?? 0} objects</span>
                ) : (
                  <span className="error">{r.error ?? "failed"}</span>
                )}
              </li>
            ))}
          </ul>
        ) : null}

        {discoveryPreview.length > 0 ? (
          <div className="bacnet-device-table-wrap">
            <p className="muted">Latest discovery preview ({discoveryPreview.length} objects, first 30 shown)</p>
            <table className="bacnet-table">
              <thead>
                <tr>
                  <th>object_identifier</th>
                  <th>name</th>
                  <th>commandable</th>
                </tr>
              </thead>
              <tbody>
                {discoveryPreview.slice(0, 30).map((row) => (
                  <tr key={row.object_identifier}>
                    <td className="mono">{row.object_identifier}</td>
                    <td>{row.name}</td>
                    <td>{row.commandable ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div className="panel">
        <h3>Device tree</h3>
        <p className="muted">Grouped by BACnet object type. Right-click for discovery, data model import, or copy.</p>
        <BacnetPointsTree
          inventory={inventory}
          liveDevices={liveDevices}
          onAddDeviceToModel={importDeviceToModel}
          onAddPointToModel={importPointToModel}
          onDiscoverDevice={runPointDiscoveryFor}
          onCopy={(text) => navigator.clipboard.writeText(text).catch(() => undefined)}
        />
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
