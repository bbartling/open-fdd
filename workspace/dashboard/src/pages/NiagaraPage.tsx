import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ActionButton from "../components/ActionButton";
import NiagaraPointsTree, { type NiagaraDevice, type NiagaraPoint } from "../components/NiagaraPointsTree";
import NiagaraTreeLegend from "../components/NiagaraTreeLegend";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import { TabDebugPanel } from "../components/TabDebugPanel";
import { formatApiError } from "../lib/formatApiError";
import { formatPollSampleAt } from "../lib/formatPollTime";
import {
  deleteNiagaraStation,
  discoverNiagaraPoints,
  exportPointsCsv,
  exportPointsJson,
  fetchNiagaraDriverTree,
  fetchNiagaraHealth,
  fetchNiagaraPollStatus,
  fetchNiagaraSchedules,
  fetchNiagaraStations,
  fetchNiagaraTree,
  pollNiagaraOnce,
  readNiagaraPoints,
  saveNiagaraStation,
  startNiagaraPoll,
  stopNiagaraPoll,
  testNiagaraStation,
  type NiagaraPollStatus,
  type NiagaraSchedule,
  type NiagaraStation,
  type NiagaraTreeNode,
} from "../lib/niagara-api";
import { STANDARD_POLL_INTERVALS } from "../lib/pollIntervals";

const BENCH_DEFAULTS = {
  name: "Bench Station 9065",
  station_url: "https://192.168.204.11",
  username: "admin",
  password_env: "OPENFDD_NIAGARA_ADMIN_PASSWORD",
  verify_tls: false,
  root_ord: "slot:/Drivers",
  default_points_root: "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points",
  poll_interval_seconds: 60,
  read_batch_size: 50,
};

const emptyForm = (): Partial<NiagaraStation> => ({
  name: "",
  station_url: "",
  username: "",
  password_env: "OPENFDD_NIAGARA_ADMIN_PASSWORD",
  verify_tls: false,
  enabled: false,
  root_ord: "slot:/Drivers",
  default_points_root: "",
  poll_interval_seconds: 60,
  read_batch_size: 50,
  browse_depth: 4,
  max_nodes: 2000,
  include_patterns: [],
  exclude_patterns: [],
  follow_external: false,
  include_proxy_ext: false,
});

export default function NiagaraPage() {
  const benchApplied = useRef(false);
  const [health, setHealth] = useState<{ dependencies_ok?: boolean; dependencies_error?: string } | null>(null);
  const [stations, setStations] = useState<NiagaraStation[]>([]);
  const [selectedStationId, setSelectedStationId] = useState("");
  const [form, setForm] = useState<Partial<NiagaraStation>>(emptyForm());
  const [driverDevices, setDriverDevices] = useState<NiagaraDevice[]>([]);
  const [treeNodes, setTreeNodes] = useState<NiagaraTreeNode[]>([]);
  const [browseBase, setBrowseBase] = useState("slot:/Drivers");
  const [browseDepth, setBrowseDepth] = useState(3);
  const [followExternal, setFollowExternal] = useState(false);
  const [schedules, setSchedules] = useState<NiagaraSchedule[]>([]);
  const [pollStatus, setPollStatus] = useState<NiagaraPollStatus | null>(null);
  const [selectedPointOrds, setSelectedPointOrds] = useState<Set<string>>(() => new Set());
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
  const [treeLoading, setTreeLoading] = useState(false);
  const [pending, setPending] = useState(false);

  const selectedStation = useMemo(
    () => stations.find((s) => s.id === selectedStationId) ?? null,
    [stations, selectedStationId],
  );

  const loadHealth = useCallback(async () => {
    try {
      const h = await fetchNiagaraHealth();
      setHealth(h);
    } catch {
      /* optional */
    }
  }, []);

  const loadStations = useCallback(async () => {
    const res = await fetchNiagaraStations();
    const list = (res.stations ?? []).filter(
      (s) => s.enabled && !String(s.station_url || "").includes("example.test"),
    );
    setStations(list.length ? list : res.stations ?? []);
    const pick = list[0] ?? res.stations?.[0];
    if (!selectedStationId && pick) {
      setSelectedStationId(pick.id);
      setForm(pick);
    }
  }, [selectedStationId]);

  const loadDriverTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const res = await fetchNiagaraDriverTree();
      const devices = (res.devices ?? []).map((d) => ({
        ...d,
        point_count: d.points?.length ?? 0,
        poll_running: pollStatus?.running && d.station_id === selectedStationId,
      }));
      setDriverDevices(devices);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setTreeLoading(false);
    }
  }, [pollStatus?.running, selectedStationId]);

  const refreshPollStatus = useCallback(async () => {
    if (!selectedStationId) return;
    try {
      const st = await fetchNiagaraPollStatus(selectedStationId);
      setPollStatus(st);
    } catch {
      /* optional */
    }
  }, [selectedStationId]);

  useEffect(() => {
    loadHealth().catch(() => undefined);
    loadStations()
      .then(() => loadDriverTree())
      .catch((e) => setLoadError(formatApiError(e)));
  }, [loadHealth, loadStations, loadDriverTree]);

  useEffect(() => {
    if (!selectedStationId) return;
    refreshPollStatus().catch(() => undefined);
    loadDriverTree().catch(() => undefined);
  }, [selectedStationId, refreshPollStatus, loadDriverTree]);

  useEffect(() => {
    if (benchApplied.current || stations.length > 0) return;
    benchApplied.current = true;
    setForm({ ...emptyForm(), ...BENCH_DEFAULTS });
    setBrowseBase(BENCH_DEFAULTS.default_points_root || BENCH_DEFAULTS.root_ord);
  }, [stations.length]);

  function selectStation(station: NiagaraStation) {
    setSelectedStationId(station.id);
    setForm(station);
    setBrowseBase(station.default_points_root || station.root_ord || "slot:/Drivers");
    setFollowExternal(Boolean(station.follow_external));
  }

  async function handleSaveStation() {
    if (!form.name || !form.station_url || !form.username) {
      setActionError("Name, URL, and username are required.");
      return;
    }
    setPending(true);
    setActionError("");
    try {
      const payload = { ...form, id: selectedStationId || form.id };
      const res = await saveNiagaraStation(payload as NiagaraStation);
      setLog(`Saved station ${res.station.name} (${res.station.id}).`);
      await loadStations();
      setSelectedStationId(res.station.id);
      setForm(res.station);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleDeleteStation() {
    if (!selectedStationId) return;
    setPending(true);
    try {
      await deleteNiagaraStation(selectedStationId);
      setLog(`Deleted station ${selectedStationId}.`);
      setSelectedStationId("");
      setForm(emptyForm());
      await loadStations();
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleTest() {
    if (!selectedStationId) {
      setActionError("Save the station first, then test.");
      return;
    }
    setPending(true);
    try {
      const res = await testNiagaraStation(selectedStationId);
      setLog(`Test OK — user ${res.authenticated_user ?? "unknown"}.`);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleDiscover() {
    if (!selectedStationId) {
      setActionError("Save the station first.");
      return;
    }
    setPending(true);
    try {
      const base = form.default_points_root || form.root_ord || browseBase;
      const res = await discoverNiagaraPoints(selectedStationId, {
        base,
        follow_external: followExternal,
        include_proxy_ext: Boolean(form.include_proxy_ext),
      });
      setLog(`Discovered ${res.count} point(s) under ${res.base}.`);
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleBrowse() {
    if (!selectedStationId) return;
    setPending(true);
    try {
      const res = await fetchNiagaraTree(selectedStationId, browseBase, browseDepth, followExternal);
      setTreeNodes(res.nodes ?? []);
      setLog(`Browse: ${res.count} node(s) under ${res.base}.`);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleReadSelected() {
    if (!selectedStationId || !selectedPointOrds.size) return;
    setPending(true);
    try {
      const res = await readNiagaraPoints(selectedStationId, Array.from(selectedPointOrds), true);
      setLog(`Read ${res.count} value(s).`);
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handlePollStart() {
    if (!selectedStationId) return;
    setPending(true);
    try {
      const st = await startNiagaraPoll(selectedStationId);
      setPollStatus(st);
      setLog("Background poll started.");
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handlePollStop() {
    if (!selectedStationId) return;
    setPending(true);
    try {
      const st = await stopNiagaraPoll(selectedStationId);
      setPollStatus(st);
      setLog("Background poll stopped.");
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handlePollOnce() {
    if (!selectedStationId) return;
    setPending(true);
    try {
      const res = await pollNiagaraOnce(selectedStationId);
      setLog(`Poll once: ${res.samples ?? 0} sample(s) in ${res.duration_ms ?? "?"} ms.`);
      await refreshPollStatus();
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleLoadSchedules(read = false) {
    if (!selectedStationId) return;
    setPending(true);
    try {
      const res = await fetchNiagaraSchedules(selectedStationId, "slot:/Schedules", read);
      setSchedules(res.schedules ?? []);
      setLog(`Schedules: ${res.count} under ${res.base}${read ? " (read)" : ""}.`);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  function togglePointOrd(ord: string, selected: boolean) {
    setSelectedPointOrds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(ord);
      else next.delete(ord);
      return next;
    });
  }

  function toggleDeviceSelection(device: NiagaraDevice, selected: boolean) {
    setSelectedPointOrds((prev) => {
      const next = new Set(prev);
      for (const p of device.points) {
        if (selected) next.add(p.point_ord);
        else next.delete(p.point_ord);
      }
      return next;
    });
  }

  const selectedPointsFlat: NiagaraPoint[] = useMemo(() => {
    const out: NiagaraPoint[] = [];
    for (const d of driverDevices) {
      for (const p of d.points) {
        if (selectedPointOrds.has(p.point_ord)) out.push(p);
      }
    }
    return out;
  }, [driverDevices, selectedPointOrds]);

  function downloadText(filename: string, text: string, mime: string) {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="page page-wide niagara-page">
      <PageHeader
        title="Niagara"
        subtitle="Supervisory read-only driver — same layout as BACnet/Modbus. Set OPENFDD_NIAGARA_ADMIN_PASSWORD in workspace/niagara.env.local on the edge."
      />
      <TabDebugPanel tab="niagara" />

      {health && !health.dependencies_ok ? (
        <div className="panel">
          <p className="muted">
            Connector dependencies missing: {health.dependencies_error}. Install <code>aiohttp</code> and{" "}
            <code>msgpack</code> in the bridge API venv.
          </p>
        </div>
      ) : null}

      {loadError ? <div className="panel error-panel">{loadError}</div> : null}
      {actionError ? <div className="panel error-panel">{actionError}</div> : null}
      {log ? (
        <div className="panel">
          <p className="muted">{log}</p>
        </div>
      ) : null}

      {pollStatus && selectedStationId ? (
        <div className="panel driver-poll-strip">
          <div className="row row-spread" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
            <strong>{selectedStation?.name ?? selectedStationId}</strong>
            <span className={`badge ${pollStatus.running ? "poll-badge" : "muted-badge"}`}>
              {pollStatus.running ? "polling" : "stopped"}
            </span>
            <span className="badge muted-badge">{pollStatus.connected ? "connected" : "disconnected"}</span>
            <span className="muted">{pollStatus.active_points} point(s)</span>
            {pollStatus.last_success ? (
              <span className="muted">
                Last OK: {formatPollSampleAt({ at: pollStatus.last_success }) ?? pollStatus.last_success}
              </span>
            ) : null}
            {pollStatus.last_error ? <span className="muted">Error: {pollStatus.last_error}</span> : null}
          </div>
          <div className="row" style={{ marginTop: "0.65rem", gap: "0.5rem" }}>
            <ActionButton secondary pending={pending} onClick={() => void handlePollStart()} disabled={pollStatus.running}>
              Start poll
            </ActionButton>
            <ActionButton secondary pending={pending} onClick={() => void handlePollStop()} disabled={!pollStatus.running}>
              Stop poll
            </ActionButton>
            <ActionButton secondary pending={pending} onClick={() => void handlePollOnce()}>
              Poll once
            </ActionButton>
            <ActionButton secondary pending={pending} onClick={() => void handleDiscover()} disabled={!selectedStationId}>
              Discover points
            </ActionButton>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <h3 className="panel-title">Devices &amp; points</h3>
        <NiagaraTreeLegend />
        {treeLoading ? <Spinner label="Loading driver tree…" /> : null}
        <NiagaraPointsTree
          devices={driverDevices}
          selectedPointOrds={selectedPointOrds}
          onTogglePointSelection={togglePointOrd}
          onToggleDeviceSelection={toggleDeviceSelection}
          onRefreshDevice={async (device) => {
            const ords = device.points.map((p) => p.point_ord);
            if (!ords.length) return;
            setPending(true);
            try {
              await readNiagaraPoints(device.station_id, ords, true);
              await loadDriverTree();
            } catch (e) {
              setActionError(formatApiError(e));
            } finally {
              setPending(false);
            }
          }}
          onRefreshPoint={async (device, point) => {
            setPending(true);
            try {
              await readNiagaraPoints(device.station_id, [point.point_ord], true);
              await loadDriverTree();
            } catch (e) {
              setActionError(formatApiError(e));
            } finally {
              setPending(false);
            }
          }}
          onDiscoverDevice={async (device) => {
            setSelectedStationId(device.station_id);
            await handleDiscover();
          }}
        />
        <div className="row" style={{ marginTop: "0.75rem", gap: "0.5rem", flexWrap: "wrap" }}>
          <ActionButton
            secondary
            pending={pending}
            disabled={!selectedPointOrds.size}
            onClick={() => void handleReadSelected()}
          >
            Read selected ({selectedPointOrds.size})
          </ActionButton>
          <ActionButton
            secondary
            disabled={!selectedPointsFlat.length}
            onClick={() => downloadText("niagara-points.csv", exportPointsCsv(selectedPointsFlat), "text/csv")}
          >
            Export CSV
          </ActionButton>
          <ActionButton
            secondary
            disabled={!selectedPointsFlat.length}
            onClick={() => downloadText("niagara-points.json", exportPointsJson(selectedPointsFlat), "application/json")}
          >
            Export JSON
          </ActionButton>
        </div>
      </div>

      <details className="panel">
        <summary className="panel-title" style={{ display: "inline", cursor: "pointer" }}>
          Station connection
        </summary>
        {!form.password_env || selectedStation?.password_configured === false ? (
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            Password env <code>{form.password_env || "OPENFDD_NIAGARA_ADMIN_PASSWORD"}</code> is not set on the edge —
            add <code>workspace/niagara.env.local</code> and restart the bridge.
          </p>
        ) : null}
        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap", margin: "0.75rem 0" }}>
          {stations.map((s) => (
            <button
              key={s.id}
              type="button"
              className={s.id === selectedStationId ? "primary-btn" : "secondary-btn"}
              onClick={() => selectStation(s)}
            >
              {s.name}
            </button>
          ))}
          <button
            type="button"
            className="secondary-btn"
            onClick={() => {
              setSelectedStationId("");
              setForm({ ...emptyForm(), ...BENCH_DEFAULTS });
            }}
          >
            + New station
          </button>
        </div>
        <div className="form-grid">
          <div className="field">
            <label className="field-label">Name</label>
            <input value={form.name ?? ""} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div className="field">
            <label className="field-label">Station URL</label>
            <input
              value={form.station_url ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, station_url: e.target.value }))}
              placeholder="https://192.168.204.11"
            />
          </div>
          <div className="field">
            <label className="field-label">Username</label>
            <input value={form.username ?? ""} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} />
          </div>
          <div className="field">
            <label className="field-label">Password env var</label>
            <input
              value={form.password_env ?? "OPENFDD_NIAGARA_ADMIN_PASSWORD"}
              onChange={(e) => setForm((f) => ({ ...f, password_env: e.target.value }))}
            />
          </div>
          <div className="field">
            <label className="field-label">
              <input
                type="checkbox"
                checked={Boolean(form.verify_tls)}
                onChange={(e) => setForm((f) => ({ ...f, verify_tls: e.target.checked }))}
              />{" "}
              Verify TLS
            </label>
          </div>
          <div className="field">
            <label className="field-label">Poll interval</label>
            <select
              value={form.poll_interval_seconds ?? 60}
              onChange={(e) => setForm((f) => ({ ...f, poll_interval_seconds: Number(e.target.value) }))}
            >
              {STANDARD_POLL_INTERVALS.map((p) => (
                <option key={p.seconds} value={p.seconds}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label className="field-label">Root ORD (browse)</label>
            <input value={form.root_ord ?? ""} onChange={(e) => setForm((f) => ({ ...f, root_ord: e.target.value }))} />
          </div>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label className="field-label">Default points root (discover/poll)</label>
            <input
              value={form.default_points_root ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, default_points_root: e.target.value }))}
              placeholder="slot:/Drivers/BacnetNetwork/DEVICE$20NAME/points"
            />
            <p className="muted">Preserve $20 / $2d encoding exactly — do not URL-decode ORDs.</p>
          </div>
          <div className="field">
            <label className="field-label">Read batch size</label>
            <input
              type="number"
              min={1}
              max={200}
              value={form.read_batch_size ?? 50}
              onChange={(e) => setForm((f) => ({ ...f, read_batch_size: Number(e.target.value) }))}
            />
          </div>
          <div className="field">
            <label className="field-label">
              <input
                type="checkbox"
                checked={Boolean(form.include_proxy_ext)}
                onChange={(e) => setForm((f) => ({ ...f, include_proxy_ext: e.target.checked }))}
              />{" "}
              Include proxy extensions (advanced)
            </label>
          </div>
          <div className="field">
            <label className="field-label">
              <input
                type="checkbox"
                checked={Boolean(form.follow_external)}
                onChange={(e) => setForm((f) => ({ ...f, follow_external: e.target.checked }))}
              />{" "}
              Follow external station links (debug)
            </label>
          </div>
        </div>

        <div className="row" style={{ marginTop: "0.75rem", gap: "0.5rem", flexWrap: "wrap" }}>
          <ActionButton pending={pending} pendingLabel="…" onClick={() => void handleSaveStation()}>
            Save station
          </ActionButton>
          <ActionButton secondary pending={pending} onClick={() => void handleTest()} disabled={!selectedStationId}>
            Test connection
          </ActionButton>
          <ActionButton secondary pending={pending} onClick={() => void handleDiscover()} disabled={!selectedStationId}>
            Discover points
          </ActionButton>
          {selectedStationId ? (
            <ActionButton secondary danger pending={pending} onClick={() => void handleDeleteStation()}>
              Delete
            </ActionButton>
          ) : null}
        </div>
      </details>
    </div>
  );
}
