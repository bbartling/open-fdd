import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { formatPollSampleAt } from "../lib/formatPollTime";
import ActionButton from "../components/ActionButton";
import JsonApiPointsTree, { type JsonApiDevice, type JsonApiPoint } from "../components/JsonApiPointsTree";
import JsonApiTreeLegend from "../components/JsonApiTreeLegend";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import { TabDebugPanel } from "../components/TabDebugPanel";

const POLL_INTERVALS = [
  { s: 60, label: "1 min" },
  { s: 300, label: "5 min" },
  { s: 600, label: "10 min" },
  { s: 900, label: "15 min" },
] as const;

const PRESETS = [
  {
    name: "Todo title",
    url: "https://jsonplaceholder.typicode.com/todos/1",
    method: "GET" as const,
    json_path: "title",
    label: "todo-title",
  },
  {
    name: "User name",
    url: "https://jsonplaceholder.typicode.com/users/1",
    method: "GET" as const,
    json_path: "name",
    label: "user-name",
  },
  {
    name: "POST todo",
    url: "https://jsonplaceholder.typicode.com/todos",
    method: "POST" as const,
    json_path: "title",
    label: "post-title",
    body: '{"title": "OT bench poll", "userId": 1, "completed": false}',
  },
];

export default function JsonApiPage() {
  const [url, setUrl] = useState(PRESETS[0].url);
  const [method, setMethod] = useState<"GET" | "POST">("GET");
  const [jsonPath, setJsonPath] = useState("title");
  const [label, setLabel] = useState("todo-title");
  const [body, setBody] = useState("");
  const [pending, setPending] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
  const [lastReading, setLastReading] = useState<{ present_value?: string; status_code?: number } | null>(null);
  const [driverDevices, setDriverDevices] = useState<JsonApiDevice[]>([]);
  const [treeLoading, setTreeLoading] = useState(true);
  const [pollStatus, setPollStatus] = useState<{
    enabled_points?: number;
    samples?: number;
    at?: string;
    error?: string;
  } | null>(null);
  const [selectedPointIds, setSelectedPointIds] = useState<Set<string>>(() => new Set());
  const [bulkPollPending, setBulkPollPending] = useState(false);
  const [pollOncePending, setPollOncePending] = useState(false);

  const loadDriverTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const res = await apiFetch<{ devices: JsonApiDevice[] }>("/api/json-api/driver/tree");
      setDriverDevices(res.devices ?? []);
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setTreeLoading(false);
    }
  }, []);

  const refreshPollStatus = useCallback(async () => {
    try {
      const st = await apiFetch<typeof pollStatus>("/api/json-api/poll/status");
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
    const tick = window.setInterval(() => {
      void loadDriverTree();
      void refreshPollStatus();
    }, 20000);
    return () => window.clearInterval(tick);
  }, [loadDriverTree, refreshPollStatus]);

  function applyPreset(idx: number) {
    const p = PRESETS[idx];
    setUrl(p.url);
    setMethod(p.method);
    setJsonPath(p.json_path);
    setLabel(p.label);
    setBody("body" in p ? p.body : "");
  }

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

  async function runRequest(store: boolean) {
    setPending(true);
    setActionError("");
    setLastReading(null);
    setLog(`${method} ${url} (path=${jsonPath || "root"})…`);
    try {
      const path = store ? "/api/json-api/read_and_store" : "/api/json-api/request";
      let parsedBody: unknown = undefined;
      if (method === "POST" && body.trim()) {
        parsedBody = JSON.parse(body);
      }
      const res = await apiFetch<{
        success?: boolean;
        present_value?: string;
        status_code?: number;
        error?: string;
        ingest?: { samples_appended?: number; feather_source?: string };
      }>(path, {
        method: "POST",
        body: JSON.stringify({
          url,
          method,
          json_path: jsonPath,
          label,
          body: parsedBody,
          save_endpoint: store,
        }),
      });
      setLastReading(res);
      if (!res.success) {
        throw new Error(res.error || "request failed");
      }
      setLog(
        store
          ? `OK ${res.status_code} → ${res.present_value} (historian source=${res.ingest?.feather_source ?? "json_api"})`
          : `OK ${res.status_code} → ${res.present_value}`,
      );
      if (store) await loadDriverTree();
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
      await apiFetch("/api/json-api/endpoint/poll", {
        method: "PATCH",
        body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
      });
      await loadDriverTree();
      setLog(`Poll ${enabled ? `every ${intervalS}s` : "stopped"} for ${pointId}`);
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function refreshPoint(device: JsonApiDevice, point: JsonApiPoint) {
    setActionError("");
    try {
      const res = await apiFetch<{ present_value?: string }>("/api/json-api/refresh", {
        method: "POST",
        body: JSON.stringify({ point_id: point.point_id, store: false }),
      });
      const formatted = String(res.present_value ?? "—");
      patchPointValue(point.point_id, formatted);
      setLog(`Refresh ${point.label} @ ${device.host}: ${formatted}`);
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function refreshDevice(device: JsonApiDevice) {
    for (const p of device.points) {
      await refreshPoint(device, p);
    }
    await loadDriverTree();
  }

  async function deletePoint(pointId: string) {
    if (!window.confirm("Remove this endpoint?")) return;
    await apiFetch(`/api/json-api/endpoint/${encodeURIComponent(pointId)}`, { method: "DELETE" });
    await loadDriverTree();
  }

  async function deleteDevice(device: JsonApiDevice) {
    if (!window.confirm(`Remove all endpoints on ${device.host}?`)) return;
    for (const p of device.points) {
      await apiFetch(`/api/json-api/endpoint/${encodeURIComponent(p.point_id)}`, { method: "DELETE" });
    }
    await loadDriverTree();
  }

  async function setDevicePoll(device: JsonApiDevice, enabled: boolean, intervalS: number) {
    for (const p of device.points) await setPointPoll(p.point_id, enabled, intervalS);
  }

  function togglePointSelection(pointId: string, selected: boolean) {
    setSelectedPointIds((prev) => {
      const next = new Set(prev);
      if (selected) next.add(pointId);
      else next.delete(pointId);
      return next;
    });
  }

  function toggleDevicePointSelection(device: JsonApiDevice, selected: boolean) {
    setSelectedPointIds((prev) => {
      const next = new Set(prev);
      for (const p of device.points) {
        if (selected) next.add(p.point_id);
        else next.delete(p.point_id);
      }
      return next;
    });
  }

  function toggleTypePointSelection(_d: JsonApiDevice, _t: string, points: JsonApiPoint[], selected: boolean) {
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

  async function batchSetPointPoll(pointIds: string[], enabled: boolean, intervalS: number) {
    if (!pointIds.length) return;
    setBulkPollPending(true);
    for (const pointId of pointIds) {
      await apiFetch("/api/json-api/endpoint/poll", {
        method: "PATCH",
        body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
      });
    }
    await loadDriverTree();
    setBulkPollPending(false);
  }

  async function runPollOnce() {
    setPollOncePending(true);
    try {
      const res = await apiFetch<{ polled?: number; samples?: number }>("/api/json-api/poll/once", { method: "POST" });
      setLog(`Poll once: ${res.polled ?? 0} endpoint(s), ${res.samples ?? 0} sample(s).`);
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
    <div className="page page-wide json-api-page">
      <PageHeader
        title="JSON API commissioning"
        subtitle="Poll HTTP GET/POST endpoints like BACnet/Modbus — test with JSONPlaceholder or any OT LAN JSON device."
      />
      <TabDebugPanel tab="json-api" />

      {pollStatus ? (
        <div className="panel">
          <h3 className="panel-title">Poll worker</h3>
          <div className="row row-spread" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
            <span className="badge poll-badge">{pollStatus.enabled_points ?? 0} endpoint(s) polling</span>
            {pollStatus.at ? (
              <span className="muted">
                Last cycle: {formatPollSampleAt(pollStatus) ?? pollStatus.at}
                {pollStatus.samples != null ? ` — ${pollStatus.samples} sample(s)` : ""}
              </span>
            ) : (
              <span className="muted">No poll cycle yet</span>
            )}
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
        <h3 className="panel-title">Add endpoint</h3>
        <p className="muted">
          Demo API:{" "}
          <a href="https://jsonplaceholder.typicode.com/" target="_blank" rel="noreferrer">
            JSONPlaceholder
          </a>{" "}
          — free fake REST for testing.
        </p>
        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
          {PRESETS.map((p, i) => (
            <button key={p.name} type="button" className="secondary-btn" onClick={() => applyPreset(i)}>
              {p.name}
            </button>
          ))}
        </div>
        <div className="form-grid">
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label className="field-label" htmlFor="ja-url">
              URL
            </label>
            <input id="ja-url" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ja-method">
              Method
            </label>
            <select id="ja-method" value={method} onChange={(e) => setMethod(e.target.value as "GET" | "POST")}>
              <option value="GET">GET</option>
              <option value="POST">POST</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ja-path">
              JSON path
            </label>
            <input id="ja-path" value={jsonPath} onChange={(e) => setJsonPath(e.target.value)} placeholder="title" />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ja-label">
              Label (historian column)
            </label>
            <input id="ja-label" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          {method === "POST" ? (
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label className="field-label" htmlFor="ja-body">
                POST body (JSON)
              </label>
              <textarea id="ja-body" rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
            </div>
          ) : null}
        </div>
        <div className="form-row-actions">
          <ActionButton pending={pending} pendingLabel="Requesting…" disabled={anyPending} onClick={() => void runRequest(false)}>
            Request once
          </ActionButton>
          <ActionButton pending={pending} pendingLabel="Requesting…" disabled={anyPending} onClick={() => void runRequest(true)}>
            Request &amp; store to historian
          </ActionButton>
        </div>
        {lastReading?.present_value ? (
          <p className="muted" style={{ marginTop: "0.75rem" }}>
            Last: HTTP {lastReading.status_code} → <code>{lastReading.present_value}</code>
          </p>
        ) : null}
      </div>

      <div className="panel">
        <h3 className="panel-title">Hosts &amp; endpoints</h3>
        <JsonApiTreeLegend />
        {driverDevices.length > 0 ? (
          <div className="bacnet-bulk-toolbar">
            <span className="muted">{selectedPointsList.length} selected</span>
            <button type="button" className="secondary-btn" onClick={selectAllTreePoints}>
              Select all
            </button>
            <button type="button" className="secondary-btn" onClick={() => setSelectedPointIds(new Set())}>
              Clear
            </button>
            {POLL_INTERVALS.map((p) => (
              <ActionButton
                key={p.s}
                secondary
                pending={bulkPollPending}
                disabled={anyPending || selectedPointsList.length === 0}
                onClick={() => void batchSetPointPoll(selectedPointsList, true, p.s)}
              >
                Poll {p.label}
              </ActionButton>
            ))}
            <ActionButton
              secondary
              pending={bulkPollPending}
              disabled={anyPending || selectedPointsList.length === 0}
              onClick={() => void batchSetPointPoll(selectedPointsList, false, 0)}
            >
              Stop polling
            </ActionButton>
          </div>
        ) : null}
        {treeLoading && driverDevices.length === 0 ? (
          <Spinner label="Loading JSON API tree…" />
        ) : (
          <JsonApiPointsTree
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
