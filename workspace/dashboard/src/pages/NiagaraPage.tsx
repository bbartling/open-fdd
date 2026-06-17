import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ActionButton from "../components/ActionButton";
import NiagaraBrowseTree from "../components/NiagaraBrowseTree";
import NiagaraStationRail, { type StationRailMeta } from "../components/NiagaraStationRail";
import NiagaraCommissionTree from "../components/NiagaraCommissionTree";
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
import {
  addBuilding,
  addDevice,
  emptyProfile,
  organizeStationPoints,
  profileSummary,
  removeBuilding,
  removeDevice,
  type NiagaraCommissionProfile,
} from "../lib/niagaraCommissionProfile";

const STATION_URL_PLACEHOLDER = "https://niagara.example.local";

const emptyForm = (): Partial<NiagaraStation> => ({
  name: "",
  station_url: "",
  username: "",
  password_env: "",
  verify_tls: false,
  enabled: true,
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
  const devBenchReady = useRef(false);
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
  const [pollStatusByStation, setPollStatusByStation] = useState<Record<string, NiagaraPollStatus>>({});
  const [connectionTestByStation, setConnectionTestByStation] = useState<Record<string, boolean>>({});
  const [isNewDraft, setIsNewDraft] = useState(false);
  const [selectedPointOrds, setSelectedPointOrds] = useState<Set<string>>(() => new Set());
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
  const [treeLoading, setTreeLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [commissionProfile, setCommissionProfile] = useState<NiagaraCommissionProfile>(() => emptyProfile());

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

  const loadAllPollStatuses = useCallback(async (stationList: NiagaraStation[]) => {
    const entries = await Promise.all(
      stationList.map(async (s) => {
        try {
          const st = await fetchNiagaraPollStatus(s.id);
          return [s.id, st] as const;
        } catch {
          return null;
        }
      }),
    );
    const map: Record<string, NiagaraPollStatus> = {};
    for (const entry of entries) {
      if (entry) map[entry[0]] = entry[1];
    }
    setPollStatusByStation(map);
  }, []);

  const loadStations = useCallback(async () => {
    const res = await fetchNiagaraStations();
    const list = res.stations ?? [];
    setStations(list);
    await loadAllPollStatuses(list);
    const pick =
      list.find((s) => s.enabled && !String(s.station_url || "").includes("example.test")) ?? list[0];
    if (!selectedStationId && !isNewDraft && pick) {
      setSelectedStationId(pick.id);
      setForm(pick);
    }
  }, [selectedStationId, isNewDraft, loadAllPollStatuses]);

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
      setPollStatusByStation((prev) => ({ ...prev, [selectedStationId]: st }));
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
    if (!selectedStationId) {
      setPollStatus(null);
      return;
    }
    setSelectedPointOrds(new Set());
    setTreeNodes([]);
    refreshPollStatus().catch(() => undefined);
    loadDriverTree().catch(() => undefined);
  }, [selectedStationId, refreshPollStatus, loadDriverTree]);

  async function loadDevBenchTemplate() {
    if (!import.meta.env.DEV) return;
    const { BENCH_DEFAULTS } = await import("../dev/niagaraBenchDefaults");
    setForm({ ...emptyForm(), ...BENCH_DEFAULTS });
    setBrowseBase(BENCH_DEFAULTS.default_points_root || BENCH_DEFAULTS.root_ord || "slot:/Drivers");
  }

  useEffect(() => {
    if (!import.meta.env.DEV || devBenchReady.current || stations.length > 0) return;
    devBenchReady.current = true;
    void loadDevBenchTemplate();
  }, [stations.length]);

  function selectStation(station: NiagaraStation) {
    setIsNewDraft(false);
    setSelectedStationId(station.id);
    setForm(station);
    setBrowseBase(station.default_points_root || station.root_ord || "slot:/Drivers");
    setFollowExternal(Boolean(station.follow_external));
    const raw = (station as NiagaraStation & { commission_profile?: NiagaraCommissionProfile }).commission_profile;
    setCommissionProfile(raw?.buildings?.length ? raw : emptyProfile());
    setActionError("");
  }

  function startNewStation() {
    setIsNewDraft(true);
    setSelectedStationId("");
    setForm(emptyForm());
    setCommissionProfile(emptyProfile());
    setBrowseBase("slot:/Drivers");
    setTreeNodes([]);
    setSelectedPointOrds(new Set());
    setPollStatus(null);
    setActionError("");
    setLog("New station — fill connection details and Save station.");
  }

  async function handleSaveStation() {
    if (!form.name || !form.station_url || !form.username) {
      setActionError("Name, URL, and username are required.");
      return;
    }
    setPending(true);
    setActionError("");
    try {
      const payload = {
        ...form,
        id: selectedStationId || form.id,
        commission_profile: commissionProfile,
      };
      const res = await saveNiagaraStation(payload as NiagaraStation);
      setLog(`Saved station ${res.station.name} (${res.station.id}).`);
      setIsNewDraft(false);
      await loadStations();
      setSelectedStationId(res.station.id);
      setForm(res.station);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleDeleteStation(stationId: string) {
    setPending(true);
    try {
      await deleteNiagaraStation(stationId);
      setLog(`Deleted station ${stationId}.`);
      setConnectionTestByStation((prev) => {
        const next = { ...prev };
        delete next[stationId];
        return next;
      });
      if (selectedStationId === stationId) {
        setSelectedStationId("");
        setForm(emptyForm());
        setIsNewDraft(false);
        setPollStatus(null);
      }
      const res = await fetchNiagaraStations();
      const list = res.stations ?? [];
      setStations(list);
      await loadAllPollStatuses(list);
      await loadDriverTree();
      if (selectedStationId === stationId) {
        if (list.length) selectStation(list[0]);
        else startNewStation();
      }
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
      setConnectionTestByStation((prev) => ({ ...prev, [selectedStationId]: true }));
      setLog(`Test OK — user ${res.authenticated_user ?? "unknown"}.`);
    } catch (e) {
      setConnectionTestByStation((prev) => ({ ...prev, [selectedStationId]: false }));
      setActionError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function handleDiscover(baseOrd?: string) {
    if (!selectedStationId) {
      setActionError("Save the station first.");
      return;
    }
    setPending(true);
    try {
      const base = baseOrd || form.default_points_root || form.root_ord || browseBase;
      if (baseOrd) {
        setForm((f) => ({ ...f, default_points_root: baseOrd }));
      }
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

  function toggleTypeSelection(device: NiagaraDevice, _typeName: string, points: NiagaraPoint[], selected: boolean) {
    setSelectedPointOrds((prev) => {
      const next = new Set(prev);
      for (const p of points) {
        if (selected) next.add(p.point_ord);
        else next.delete(p.point_ord);
      }
      return next;
    });
  }

  const stationDevices = useMemo(
    () => (selectedStationId ? driverDevices.filter((d) => d.station_id === selectedStationId) : []),
    [driverDevices, selectedStationId],
  );

  const metaById = useMemo(() => {
    const out: Record<string, StationRailMeta> = {};
    for (const s of stations) {
      const pointCount = driverDevices
        .filter((d) => d.station_id === s.id)
        .reduce((n, d) => n + (d.points?.length ?? 0), 0);
      const ps = pollStatusByStation[s.id];
      const tested = connectionTestByStation[s.id];
      out[s.id] = {
        pointCount,
        pollRunning: Boolean(ps?.running),
        connected: ps?.connected ?? null,
        connectionTested: tested === undefined ? null : tested,
      };
    }
    return out;
  }, [stations, driverDevices, pollStatusByStation, connectionTestByStation]);

  function selectAllTreePoints() {
    const all = new Set<string>();
    for (const d of stationDevices) {
      for (const p of d.points) all.add(p.point_ord);
    }
    setSelectedPointOrds(all);
  }

  function clearPointSelection() {
    setSelectedPointOrds(new Set());
  }

  async function handleSaveProfile() {
    await handleSaveStation();
    setLog(`Saved import profile — ${profileSummary(commissionProfile)}.`);
  }

  function handleAddBuilding(node: NiagaraTreeNode) {
    setCommissionProfile((p) => addBuilding(p, node, { site_id: form.name ? slugId(form.name) : undefined }));
    setLog(`Added building: ${node.name || node.ord}`);
  }

  function handleAddDevice(node: NiagaraTreeNode, buildingId: string) {
    setCommissionProfile((p) => addDevice(p, node, buildingId, treeNodes));
    setLog(`Added device: ${node.name || node.ord}`);
  }

  function slugId(text: string): string {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48);
  }

  const activeStationDevice = useMemo(
    () => stationDevices[0] ?? null,
    [stationDevices],
  );

  const organizedStation = useMemo(() => {
    if (!activeStationDevice) return null;
    return organizeStationPoints({
      station_id: activeStationDevice.station_id,
      station_name: activeStationDevice.station_name,
      station_url: activeStationDevice.station_url,
      points: activeStationDevice.points,
      profile: commissionProfile,
      poll_running: Boolean(pollStatus?.running && pollStatus.station_id === selectedStationId),
    });
  }, [activeStationDevice, commissionProfile, pollStatus, selectedStationId]);

  const useCommissionTree = commissionProfile.buildings.length > 0;

  const selectedPointsFlat: NiagaraPoint[] = useMemo(() => {
    const out: NiagaraPoint[] = [];
    for (const d of stationDevices) {
      for (const p of d.points) {
        if (selectedPointOrds.has(p.point_ord)) out.push(p);
      }
    }
    return out;
  }, [stationDevices, selectedPointOrds]);

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
        subtitle="Connect station → map folder buildings/devices → discover points for BRICK bindings and polling (BACnet-style tree)."
      />

      <div className="niagara-page-stack">
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

      <NiagaraStationRail
        stations={stations}
        selectedStationId={selectedStationId}
        isNewDraft={isNewDraft}
        metaById={metaById}
        onSelect={selectStation}
        onNew={startNewStation}
        onDelete={(id) => void handleDeleteStation(id)}
        pending={pending}
      />

          <div className="panel">
            <div className="niagara-station-header">
              <div>
                <h3 className="panel-title">{isNewDraft ? "New station" : selectedStation?.name ?? "Niagara station"}</h3>
                <div className="niagara-station-sub muted">
                  {isNewDraft
                    ? "Save before testing, browsing, or polling."
                    : selectedStation?.station_url ?? "Select or create a station in the rail."}
                </div>
              </div>
              <div className="host-info-grid" style={{ flex: "1 1 12rem", maxWidth: "22rem" }}>
                <div>
                  <span className="status-kv-label">Connector</span>
                  <div className={health?.dependencies_ok !== false ? "ok" : "error"}>
                    {health?.dependencies_ok !== false ? "ready" : "deps missing"}
                  </div>
                </div>
                <div>
                  <span className="status-kv-label">Import profile</span>
                  <div>{profileSummary(commissionProfile)}</div>
                </div>
              </div>
            </div>

            {!form.password_env || selectedStation?.password_configured === false ? (
              <p className="muted panel-warn" style={{ padding: "0.5rem 0.75rem", borderRadius: 8, marginTop: 0 }}>
                Password env not configured — set the variable below and restart the bridge.
              </p>
            ) : null}

            <div className="form-grid">
              <div className="field">
                <label className="field-label" htmlFor="niagara-name">
                  Name
                </label>
                <input
                  id="niagara-name"
                  value={form.name ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Niagara station name"
                />
              </div>
              <div className="field" style={{ gridColumn: "span 2" }}>
                <label className="field-label" htmlFor="niagara-url">
                  Station URL
                </label>
                <input
                  id="niagara-url"
                  value={form.station_url ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, station_url: e.target.value }))}
                  placeholder={STATION_URL_PLACEHOLDER}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="niagara-user">
                  Username
                </label>
                <input
                  id="niagara-user"
                  value={form.username ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="niagara-pass-env">
                  Password env var
                </label>
                <input
                  id="niagara-pass-env"
                  value={form.password_env ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, password_env: e.target.value }))}
                  placeholder="edge password env var"
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="niagara-poll">
                  Poll interval
                </label>
                <select
                  id="niagara-poll"
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
              <div className="field">
                <label className="field-label" htmlFor="niagara-batch">
                  Read batch size
                </label>
                <input
                  id="niagara-batch"
                  type="number"
                  min={1}
                  max={200}
                  value={form.read_batch_size ?? 50}
                  onChange={(e) => setForm((f) => ({ ...f, read_batch_size: Number(e.target.value) }))}
                />
              </div>
              <div className="field" style={{ gridColumn: "1 / -1" }}>
                <label className="field-label" htmlFor="niagara-points-root">
                  Default points root (discover/poll)
                </label>
                <input
                  id="niagara-points-root"
                  value={form.default_points_root ?? ""}
                  onChange={(e) => setForm((f) => ({ ...f, default_points_root: e.target.value }))}
                  placeholder="slot:/Drivers/BacnetNetwork/DEVICE$20NAME/points"
                />
                <p className="muted">Preserve $20 / $2d encoding — do not URL-decode ORDs.</p>
              </div>
              <div className="field">
                <label className="checkbox-row" htmlFor="niagara-enabled">
                  <input
                    id="niagara-enabled"
                    type="checkbox"
                    checked={form.enabled !== false}
                    onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
                  />
                  Station enabled
                </label>
              </div>
            </div>

            <details className="niagara-advanced" style={{ marginTop: "0.65rem" }}>
              <summary className="muted" style={{ cursor: "pointer" }}>
                Advanced connection &amp; browse
              </summary>
              <div className="form-grid" style={{ marginTop: "0.65rem" }}>
                <div className="field">
                  <label className="field-label" htmlFor="niagara-browse-depth">
                    Browse depth
                  </label>
                  <input
                    id="niagara-browse-depth"
                    type="number"
                    min={1}
                    max={12}
                    value={form.browse_depth ?? 4}
                    onChange={(e) => setForm((f) => ({ ...f, browse_depth: Number(e.target.value) }))}
                  />
                </div>
                <div className="field">
                  <label className="field-label" htmlFor="niagara-max-nodes">
                    Max nodes
                  </label>
                  <input
                    id="niagara-max-nodes"
                    type="number"
                    min={100}
                    max={20000}
                    value={form.max_nodes ?? 2000}
                    onChange={(e) => setForm((f) => ({ ...f, max_nodes: Number(e.target.value) }))}
                  />
                </div>
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <label className="field-label" htmlFor="niagara-root-ord">
                    Root ORD (browse)
                  </label>
                  <input
                    id="niagara-root-ord"
                    value={form.root_ord ?? ""}
                    onChange={(e) => setForm((f) => ({ ...f, root_ord: e.target.value }))}
                    placeholder="slot:/Drivers"
                  />
                </div>
                <div className="field">
                  <label className="checkbox-row" htmlFor="niagara-verify-tls">
                    <input
                      id="niagara-verify-tls"
                      type="checkbox"
                      checked={Boolean(form.verify_tls)}
                      onChange={(e) => setForm((f) => ({ ...f, verify_tls: e.target.checked }))}
                    />
                    Verify TLS
                  </label>
                </div>
                <div className="field">
                  <label className="checkbox-row" htmlFor="niagara-proxy-ext">
                    <input
                      id="niagara-proxy-ext"
                      type="checkbox"
                      checked={Boolean(form.include_proxy_ext)}
                      onChange={(e) => setForm((f) => ({ ...f, include_proxy_ext: e.target.checked }))}
                    />
                    Include proxy extensions
                  </label>
                </div>
                <div className="field">
                  <label className="checkbox-row" htmlFor="niagara-follow-ext">
                    <input
                      id="niagara-follow-ext"
                      type="checkbox"
                      checked={Boolean(form.follow_external)}
                      onChange={(e) => setForm((f) => ({ ...f, follow_external: e.target.checked }))}
                    />
                    Follow external links
                  </label>
                </div>
              </div>
            </details>

            <div className="row" style={{ marginTop: "0.75rem", gap: "0.5rem", flexWrap: "wrap" }}>
              <ActionButton pending={pending} pendingLabel="Saving…" onClick={() => void handleSaveStation()}>
                Save station
              </ActionButton>
              <ActionButton
                secondary
                pending={pending}
                onClick={() => void handleTest()}
                disabled={!selectedStationId || !form.name || !form.station_url}
              >
                Test connection
              </ActionButton>
              <ActionButton secondary pending={pending} onClick={() => void handleSaveProfile()}>
                Save import profile
              </ActionButton>
              {import.meta.env.DEV ? (
                <button type="button" className="secondary-btn" onClick={() => void loadDevBenchTemplate()}>
                  Load dev bench template
                </button>
              ) : null}
            </div>

            {selectedStationId && pollStatus ? (
              <div className="niagara-poll-strip" style={{ marginTop: "0.85rem" }}>
                <div className="status-kv">
                  <span className="status-kv-label">Poll</span>
                  <span className="status-kv-value">
                    <span className={`badge ${pollStatus.running ? "poll-badge" : "muted-badge"}`}>
                      {pollStatus.running ? "polling" : "stopped"}
                    </span>{" "}
                    {pollStatus.active_points} pt
                  </span>
                </div>
                <div className="status-kv">
                  <span className="status-kv-label">Link</span>
                  <span className={`status-kv-value ${pollStatus.connected ? "ok" : "error"}`}>
                    {pollStatus.connected ? "connected" : "disconnected"}
                  </span>
                </div>
                {connectionTestByStation[selectedStationId] !== undefined ? (
                  <div className="status-kv">
                    <span className="status-kv-label">Test</span>
                    <span className={`status-kv-value ${connectionTestByStation[selectedStationId] ? "ok" : "error"}`}>
                      {connectionTestByStation[selectedStationId] ? "OK" : "failed"}
                    </span>
                  </div>
                ) : null}
                {pollStatus.last_success ? (
                  <div className="status-kv">
                    <span className="status-kv-label">Last sample</span>
                    <span className="status-kv-value">
                      {formatPollSampleAt({ at: pollStatus.last_success }) ?? pollStatus.last_success}
                      {pollStatus.last_poll_duration_ms ? (
                        <span className="muted" style={{ display: "block", fontSize: "0.85em" }}>
                          {pollStatus.last_poll_duration_ms} ms · {pollStatus.batch_count} batch(es)
                        </span>
                      ) : null}
                    </span>
                  </div>
                ) : null}
                {pollStatus.last_error ? (
                  <div className="status-kv">
                    <span className="status-kv-label">Error</span>
                    <span className="status-kv-value error">{pollStatus.last_error}</span>
                  </div>
                ) : null}
                <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap", width: "100%" }}>
                  <ActionButton secondary pending={pending} onClick={() => void handlePollStart()} disabled={pollStatus.running}>
                    Start poll
                  </ActionButton>
                  <ActionButton secondary pending={pending} onClick={() => void handlePollStop()} disabled={!pollStatus.running}>
                    Stop poll
                  </ActionButton>
                  <ActionButton secondary pending={pending} onClick={() => void handlePollOnce()}>
                    Poll once
                  </ActionButton>
                  <ActionButton secondary pending={pending} onClick={() => void handleDiscover()}>
                    Discover points
                  </ActionButton>
                </div>
              </div>
            ) : selectedStationId ? (
              <div className="row" style={{ marginTop: "0.85rem", gap: "0.5rem", flexWrap: "wrap" }}>
                <ActionButton secondary pending={pending} onClick={() => void handleDiscover()}>
                  Discover points
                </ActionButton>
              </div>
            ) : null}
          </div>

          {selectedStationId ? (
            <>
              <div className="panel">
                <h3 className="panel-title">Station tree browse</h3>
                <p className="muted" style={{ marginTop: 0 }}>
                  <strong>Right-click</strong> folder → building or device. Left-click sets points root.
                </p>
                <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.65rem" }}>
                  <label className="field-inline">
                    Base ORD
                    <input
                      value={browseBase}
                      onChange={(e) => setBrowseBase(e.target.value)}
                      placeholder="slot:/Drivers/BacnetNetwork"
                      style={{ minWidth: "16rem" }}
                    />
                  </label>
                  <label className="field-inline">
                    Depth
                    <input
                      type="number"
                      min={1}
                      max={12}
                      value={browseDepth}
                      onChange={(e) => setBrowseDepth(Number(e.target.value) || 3)}
                      style={{ width: "4rem" }}
                    />
                  </label>
                  <label className="field-inline">
                    <input
                      type="checkbox"
                      checked={followExternal}
                      onChange={(e) => setFollowExternal(e.target.checked)}
                    />{" "}
                    Follow external
                  </label>
                  <ActionButton secondary pending={pending} onClick={() => void handleBrowse()}>
                    Preview folder tree
                  </ActionButton>
                </div>
                <NiagaraBrowseTree
                  nodes={treeNodes}
                  profile={commissionProfile}
                  onAddBuilding={handleAddBuilding}
                  onAddDevice={handleAddDevice}
                  onSetPointsRoot={(ord) => {
                    setForm((f) => ({ ...f, default_points_root: ord }));
                    setLog(`Points root → ${ord}`);
                  }}
                  onDiscoverUnder={(ord) => void handleDiscover(ord)}
                  onCopy={(text) => {
                    void navigator.clipboard.writeText(text);
                    setLog("Copied ORD to clipboard.");
                  }}
                />
              </div>

              <div className="panel">
                <h3 className="panel-title">Devices &amp; points</h3>
                <NiagaraTreeLegend />
                <p className="muted" style={{ marginTop: "0.5rem" }}>
                  Points for <strong>{selectedStation?.name}</strong> only. Map folders to BRICK IDs; select for read/export.
                </p>
                {stationDevices.length > 0 ? (
                  <div className="bacnet-bulk-toolbar">
                    <span className="muted">{selectedPointOrds.size} point(s) selected</span>
                    <button type="button" className="secondary-btn" onClick={selectAllTreePoints}>
                      Select all points
                    </button>
                    <button type="button" className="secondary-btn" onClick={clearPointSelection}>
                      Clear selection
                    </button>
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
                      onClick={() =>
                        downloadText("niagara-points.json", exportPointsJson(selectedPointsFlat), "application/json")
                      }
                    >
                      Export JSON
                    </ActionButton>
                  </div>
                ) : null}
                {treeLoading && stationDevices.length === 0 ? (
                  <Spinner label="Loading driver tree…" />
                ) : useCommissionTree && organizedStation ? (
                  <NiagaraCommissionTree
                    station={organizedStation}
                    selectedPointOrds={selectedPointOrds}
                    onTogglePointSelection={togglePointOrd}
                    onRefreshPoint={async (point) => {
                      if (!selectedStationId) return;
                      setPending(true);
                      try {
                        await readNiagaraPoints(selectedStationId, [point.point_ord], true);
                        await loadDriverTree();
                      } catch (e) {
                        setActionError(formatApiError(e));
                      } finally {
                        setPending(false);
                      }
                    }}
                    onDiscoverDevice={(ord) => void handleDiscover(ord)}
                    onRemoveBuilding={(id) => setCommissionProfile((p) => removeBuilding(p, id))}
                    onRemoveDevice={(id) => setCommissionProfile((p) => removeDevice(p, id))}
                    onCopy={(text) => {
                      void navigator.clipboard.writeText(text);
                      setLog("Copied to clipboard.");
                    }}
                  />
                ) : stationDevices.length > 0 ? (
                  <NiagaraPointsTree
                    devices={stationDevices}
                    selectedPointOrds={selectedPointOrds}
                    onTogglePointSelection={togglePointOrd}
                    onToggleDeviceSelection={toggleDeviceSelection}
                    onToggleTypeSelection={toggleTypeSelection}
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
                    onDiscoverDevice={async () => {
                      await handleDiscover();
                    }}
                  />
                ) : (
                  <p className="muted">No points yet — use Discover points above.</p>
                )}
                {treeLoading && stationDevices.length > 0 ? (
                  <p className="muted">
                    <Spinner label="Refreshing tree…" />
                  </p>
                ) : null}
              </div>
            </>
          ) : (
            <div className="panel muted">
              <p style={{ margin: 0 }}>Save a station to browse the folder tree and view points.</p>
            </div>
          )}

        <div className="panel">
          <h3>Activity</h3>
          {pending ? <p className="muted"><Spinner label="Niagara operation in progress…" /></p> : null}
          {actionError ? <p className="error">{actionError}</p> : null}
          <pre className="console">{log || "Ready."}</pre>
        </div>
      </div>
    </div>
  );
}
