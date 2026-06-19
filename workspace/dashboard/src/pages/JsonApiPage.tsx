import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { formatPollSampleAt } from "../lib/formatPollTime";
import { DEFAULT_POLL_INTERVAL_S, STANDARD_POLL_INTERVALS } from "../lib/pollIntervals";
import ActionButton from "../components/ActionButton";
import JsonApiPointsTree, { type JsonApiDevice, type JsonApiPoint } from "../components/JsonApiPointsTree";
import JsonApiTreeLegend from "../components/JsonApiTreeLegend";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import { TabDebugPanel } from "../components/TabDebugPanel";

type AuthType = "none" | "bearer" | "basic";

type RestSensorRow = {
  json_path: string;
  label: string;
  units: string;
};

type RestPreset = {
  id: string;
  name: string;
  category: string;
  description?: string;
  resource: string;
  method?: string;
  headers_json?: string;
  body_json?: string;
  sensors: RestSensorRow[];
  requires_env?: string[];
  env_note?: string;
};

type TestResult = {
  success?: boolean;
  status_code?: number;
  present_value?: string;
  error?: string;
  sensors?: Array<{ label: string; json_path: string; present_value?: string; units?: string }>;
  raw_json?: unknown;
};

const EMPTY_SENSOR: RestSensorRow = { json_path: "", label: "value", units: "" };

export default function JsonApiPage() {
  const [resource, setResource] = useState("https://jsonplaceholder.typicode.com/todos/1");
  const [method, setMethod] = useState<"GET" | "POST">("GET");
  const [headersJson, setHeadersJson] = useState("");
  const [bodyJson, setBodyJson] = useState("");
  const [sensors, setSensors] = useState<RestSensorRow[]>([
    { json_path: "title", label: "todo-title", units: "" },
  ]);
  const [authType, setAuthType] = useState<AuthType>("none");
  const [bearerToken, setBearerToken] = useState("");
  const [basicUser, setBasicUser] = useState("");
  const [basicPassword, setBasicPassword] = useState("");
  const [verifyTls, setVerifyTls] = useState(true);
  const [pollIntervalS, setPollIntervalS] = useState(DEFAULT_POLL_INTERVAL_S);
  const [presets, setPresets] = useState<RestPreset[]>([]);
  const [presetCategories, setPresetCategories] = useState<string[]>([]);
  const [testPending, setTestPending] = useState(false);
  const [registerPending, setRegisterPending] = useState(false);
  const [presetPending, setPresetPending] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [rawPreview, setRawPreview] = useState("");
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [log, setLog] = useState("");
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
  const [envStatus, setEnvStatus] = useState<{
    env_file?: string;
    env_file_exists?: boolean;
    variables?: Record<string, boolean>;
  } | null>(null);

  const presetsByCategory = useMemo(() => {
    const map = new Map<string, RestPreset[]>();
    for (const p of presets) {
      const cat = p.category || "other";
      const list = map.get(cat) ?? [];
      list.push(p);
      map.set(cat, list);
    }
    return map;
  }, [presets]);

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

  const refreshEnvStatus = useCallback(async () => {
    try {
      const st = await apiFetch<typeof envStatus>("/api/json-api/env/status");
      setEnvStatus(st);
    } catch {
      /* optional */
    }
  }, []);

  const loadPresets = useCallback(async () => {
    try {
      const res = await apiFetch<{ presets?: RestPreset[]; categories?: string[] }>("/api/json-api/presets");
      setPresets(res.presets ?? []);
      setPresetCategories(res.categories ?? []);
    } catch (e) {
      setLoadError(formatApiError(e));
    }
  }, []);

  useEffect(() => {
    void loadDriverTree();
    void refreshPollStatus();
    void refreshEnvStatus();
    void loadPresets();
  }, [loadDriverTree, refreshPollStatus, refreshEnvStatus, loadPresets]);

  useEffect(() => {
    const tick = window.setInterval(() => {
      void loadDriverTree();
      void refreshPollStatus();
    }, 20000);
    return () => window.clearInterval(tick);
  }, [loadDriverTree, refreshPollStatus]);

  function applyPreset(preset: RestPreset) {
    setResource(preset.resource);
    setMethod((preset.method ?? "GET").toUpperCase() === "POST" ? "POST" : "GET");
    setHeadersJson(preset.headers_json ?? "");
    setBodyJson(preset.body_json ?? "");
    setSensors(
      preset.sensors.length
        ? preset.sensors.map((s) => ({ ...s }))
        : [{ ...EMPTY_SENSOR }],
    );
    setTestResult(null);
    setRawPreview("");
    setLog(`Loaded preset: ${preset.name}`);
  }

  function updateSensor(idx: number, patch: Partial<RestSensorRow>) {
    setSensors((prev) => prev.map((row, i) => (i === idx ? { ...row, ...patch } : row)));
  }

  function addSensorRow() {
    setSensors((prev) => [...prev, { ...EMPTY_SENSOR, label: `sensor-${prev.length + 1}` }]);
  }

  function removeSensorRow(idx: number) {
    setSensors((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
  }

  function buildRequestPayload() {
    let headers: Record<string, string> = {};
    if (headersJson.trim()) {
      headers = JSON.parse(headersJson) as Record<string, string>;
    }
    let body: unknown = undefined;
    if (method === "POST" && bodyJson.trim()) {
      body = JSON.parse(bodyJson);
    }
    const cleanedSensors = sensors
      .filter((s) => s.json_path.trim() || s.label.trim())
      .map((s) => ({
        json_path: s.json_path.trim(),
        label: s.label.trim() || s.json_path.trim() || "value",
        units: s.units.trim(),
      }));
    return {
      url: resource.trim(),
      method,
      json_path: cleanedSensors[0]?.json_path ?? "",
      label: cleanedSensors[0]?.label ?? "value",
      headers,
      body,
      sensors: cleanedSensors,
      auth_type: authType,
      bearer_token: authType === "bearer" ? bearerToken : undefined,
      basic_user: authType === "basic" ? basicUser : undefined,
      basic_password: authType === "basic" ? basicPassword : undefined,
      verify_tls: verifyTls,
    };
  }

  async function runTest() {
    setTestPending(true);
    setActionError("");
    setTestResult(null);
    setRawPreview("");
    setLog(`Test GET/POST ${resource}…`);
    try {
      const payload = buildRequestPayload();
      const res = await apiFetch<TestResult>("/api/json-api/test", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setTestResult(res);
      if (res.raw_json != null) {
        setRawPreview(JSON.stringify(res.raw_json, null, 2).slice(0, 4000));
      }
      if (!res.success) {
        throw new Error(res.error || "test failed");
      }
      const parts =
        res.sensors?.map((s) => `${s.label}=${s.present_value ?? "—"}`).join(", ") ??
        res.present_value ??
        "";
      setLog(`Test OK HTTP ${res.status_code} → ${parts}`);
    } catch (e) {
      const msg = formatApiError(e);
      setActionError(msg);
      setLog(msg);
    } finally {
      setTestPending(false);
    }
  }

  async function registerBundle(pollOnce: boolean) {
    setRegisterPending(true);
    setActionError("");
    try {
      const payload = buildRequestPayload();
      const res = await apiFetch<{ count?: number; poll?: { samples?: number } }>(
        "/api/json-api/register-bundle",
        {
          method: "POST",
          body: JSON.stringify({
            resource: payload.url,
            method: payload.method,
            sensors: payload.sensors,
            headers: payload.headers,
            body: payload.body,
            auth_type: payload.auth_type,
            bearer_token: payload.bearer_token,
            basic_user: payload.basic_user,
            basic_password: payload.basic_password,
            verify_tls: payload.verify_tls,
            poll_interval_s: pollIntervalS,
            enabled: true,
            poll_once: pollOnce,
          }),
        },
      );
      setLog(
        `Registered ${res.count ?? payload.sensors.length} sensor(s) @ poll ${pollIntervalS}s` +
          (res.poll ? ` — first poll: ${res.poll.samples ?? 0} sample(s)` : ""),
      );
      await loadDriverTree();
      await refreshPollStatus();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setRegisterPending(false);
    }
  }

  async function registerPreset(preset: RestPreset) {
    setPresetPending(preset.id);
    setActionError("");
    try {
      const res = await apiFetch<{ count?: number; poll?: { samples?: number } }>(
        `/api/json-api/presets/${encodeURIComponent(preset.id)}/register`,
        {
          method: "POST",
          body: JSON.stringify({
            poll_interval_s: pollIntervalS,
            enabled: true,
            poll_once: true,
          }),
        },
      );
      setLog(
        `${preset.name}: registered ${res.count ?? preset.sensors.length} sensor(s)` +
          (res.poll ? ` — poll: ${res.poll.samples ?? 0} sample(s)` : ""),
      );
      await loadDriverTree();
      await refreshPollStatus();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPresetPending(null);
    }
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

  async function setPointPoll(pointId: string, enabled: boolean, intervalS: number) {
    setActionError("");
    try {
      await apiFetch("/api/json-api/endpoint/poll", {
        method: "PATCH",
        body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
      });
      await loadDriverTree();
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
      patchPointValue(point.point_id, String(res.present_value ?? "—"));
      setLog(`Refresh ${point.label} @ ${device.host}: ${res.present_value ?? "—"}`);
    } catch (e) {
      setActionError(formatApiError(e));
    }
  }

  async function refreshDevice(device: JsonApiDevice) {
    for (const p of device.points) await refreshPoint(device, p);
    await loadDriverTree();
  }

  async function deletePoint(pointId: string) {
    setActionError("");
    const prev = driverDevices;
    setDriverDevices((list) =>
      list.map((d) => ({
        ...d,
        points: d.points.filter((p) => p.point_id !== pointId),
      })),
    );
    try {
      await apiFetch(`/api/json-api/endpoint/${encodeURIComponent(pointId)}`, { method: "DELETE" });
    } catch (e) {
      setDriverDevices(prev);
      setActionError(formatApiError(e));
    }
  }

  async function deleteDevice(device: JsonApiDevice) {
    setActionError("");
    const prev = driverDevices;
    setDriverDevices((list) => list.filter((d) => d.host !== device.host));
    try {
      for (const p of device.points) {
        await apiFetch(`/api/json-api/endpoint/${encodeURIComponent(p.point_id)}`, { method: "DELETE" });
      }
    } catch (e) {
      setDriverDevices(prev);
      setActionError(formatApiError(e));
    }
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
    try {
      for (const pointId of pointIds) {
        await apiFetch("/api/json-api/endpoint/poll", {
          method: "PATCH",
          body: JSON.stringify({ point_id: pointId, enabled, poll_interval_s: intervalS }),
        });
      }
      await loadDriverTree();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setBulkPollPending(false);
    }
  }

  async function runPollOnce() {
    setPollOncePending(true);
    try {
      const res = await apiFetch<{ polled?: number; samples?: number }>("/api/json-api/poll/once", { method: "POST" });
      setLog(`Poll once: ${res.polled ?? 0} resource(s), ${res.samples ?? 0} sample(s).`);
      await loadDriverTree();
      await refreshPollStatus();
    } catch (e) {
      setActionError(formatApiError(e));
    } finally {
      setPollOncePending(false);
    }
  }

  const selectedPointsList = Array.from(selectedPointIds);
  const anyPending =
    testPending || registerPending || bulkPollPending || pollOncePending || presetPending != null;
  const owmKeyReady = envStatus?.variables?.OPENWEATHER_API_KEY === true;

  return (
    <div className="page page-wide json-api-page">
      <PageHeader title="REST sensors" subtitle="Poll JSON HTTP endpoints into the historian." />
      <TabDebugPanel tab="json-api" />

      {pollStatus ? (
        <div className="panel">
          <h3 className="panel-title">Poll worker</h3>
          <div className="row row-spread" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
            <span className="badge poll-badge">{pollStatus.enabled_points ?? 0} sensor(s) polling</span>
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

      <details className="panel json-api-presets-advanced">
        <summary className="panel-title" style={{ cursor: "pointer", listStyle: "none" }}>
          Show example presets (developer)
        </summary>
        <p className="muted">
          Optional demos inspired by{" "}
          <a href="https://www.home-assistant.io/integrations/sensor.rest/" target="_blank" rel="noreferrer">
            Home Assistant RESTful Sensor
          </a>
          . Register real JSON API sources in the form below for production use.
        </p>
        {presetCategories.map((cat) => (
          <div key={cat} style={{ marginTop: "0.75rem" }}>
            <h4 className="panel-subtitle" style={{ textTransform: "capitalize", marginBottom: "0.35rem" }}>
              {cat}
            </h4>
            <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
              {(presetsByCategory.get(cat) ?? []).map((preset) => {
                const needsEnv = (preset.requires_env ?? []).some(
                  (v) => envStatus?.variables?.[v] !== true,
                );
                return (
                  <div key={preset.id} className="json-api-preset-card" style={{ display: "flex", gap: "0.35rem" }}>
                    <button type="button" className="secondary-btn" onClick={() => applyPreset(preset)} title={preset.description}>
                      {preset.name}
                    </button>
                    <ActionButton
                      secondary
                      pending={presetPending === preset.id}
                      pendingLabel="…"
                      disabled={anyPending || needsEnv}
                      onClick={() => void registerPreset(preset)}
                    >
                      Register
                    </ActionButton>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {envStatus ? (
          <p className="muted" style={{ marginTop: "0.75rem" }}>
            Env: <code>{envStatus.env_file ?? "workspace/json_api.env.local"}</code>
            {envStatus.env_file_exists ? " (loaded)" : " (missing)"}
            {" — "}
            OpenWeather key {owmKeyReady ? "set" : "not set"}
          </p>
        ) : null}
      </details>

      <div className="panel">
        <div className="panel-title-row">
          <h3 className="panel-title">REST resource</h3>
          <details className="ui-advanced-fold">
            <summary>Help</summary>
            <p className="ui-help-text">
              One URL per resource; multiple JSON paths become historian columns. API keys belong in server env files.
            </p>
          </details>
        </div>
        <div className="form-grid">
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label className="field-label" htmlFor="ja-resource">
              Resource URL
            </label>
            <input
              id="ja-resource"
              value={resource}
              onChange={(e) => setResource(e.target.value)}
              placeholder="https://api.example.com/status"
            />
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
            <label className="field-label" htmlFor="ja-poll">
              Poll interval (when registered)
            </label>
            <select
              id="ja-poll"
              value={pollIntervalS}
              onChange={(e) => setPollIntervalS(Number(e.target.value))}
            >
              {STANDARD_POLL_INTERVALS.map((p) => (
                <option key={p.seconds} value={p.seconds}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label className="field-label" htmlFor="ja-headers">
              Headers (JSON object)
            </label>
            <textarea
              id="ja-headers"
              rows={2}
              value={headersJson}
              onChange={(e) => setHeadersJson(e.target.value)}
              placeholder='{"Accept": "application/json"}'
            />
          </div>
          {method === "POST" ? (
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label className="field-label" htmlFor="ja-body">
                POST payload (JSON)
              </label>
              <textarea id="ja-body" rows={3} value={bodyJson} onChange={(e) => setBodyJson(e.target.value)} />
            </div>
          ) : null}
          <div className="field">
            <label className="field-label" htmlFor="ja-auth">
              Auth
            </label>
            <select id="ja-auth" value={authType} onChange={(e) => setAuthType(e.target.value as AuthType)}>
              <option value="none">None</option>
              <option value="bearer">Bearer</option>
              <option value="basic">HTTP Basic</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ja-verify-tls">
              TLS
            </label>
            <label className="checkbox-row" htmlFor="ja-verify-tls">
              <input
                id="ja-verify-tls"
                type="checkbox"
                checked={verifyTls}
                onChange={(e) => setVerifyTls(e.target.checked)}
              />
              Verify certificate
            </label>
          </div>
          {authType === "bearer" ? (
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label className="field-label" htmlFor="ja-bearer">
                Bearer token
              </label>
              <input
                id="ja-bearer"
                type="password"
                autoComplete="off"
                value={bearerToken}
                onChange={(e) => setBearerToken(e.target.value)}
              />
            </div>
          ) : null}
          {authType === "basic" ? (
            <>
              <div className="field">
                <label className="field-label" htmlFor="ja-basic-user">
                  Username
                </label>
                <input id="ja-basic-user" value={basicUser} onChange={(e) => setBasicUser(e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="ja-basic-pass">
                  Password
                </label>
                <input
                  id="ja-basic-pass"
                  type="password"
                  autoComplete="off"
                  value={basicPassword}
                  onChange={(e) => setBasicPassword(e.target.value)}
                />
              </div>
            </>
          ) : null}
        </div>

        <h4 className="panel-subtitle" style={{ marginTop: "1rem" }}>
          Sensor paths
        </h4>
        <table className="data-table" style={{ width: "100%", marginTop: "0.5rem" }}>
          <thead>
            <tr>
              <th>JSON path</th>
              <th>Label (column)</th>
              <th>Units</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sensors.map((row, idx) => (
              <tr key={idx}>
                <td>
                  <input
                    value={row.json_path}
                    onChange={(e) => updateSensor(idx, { json_path: e.target.value })}
                    placeholder="title"
                  />
                </td>
                <td>
                  <input
                    value={row.label}
                    onChange={(e) => updateSensor(idx, { label: e.target.value })}
                    placeholder="todo-title"
                  />
                </td>
                <td>
                  <input
                    value={row.units}
                    onChange={(e) => updateSensor(idx, { units: e.target.value })}
                    placeholder="degF"
                  />
                </td>
                <td>
                  <button type="button" className="secondary-btn" onClick={() => removeSensorRow(idx)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="secondary-btn" style={{ marginTop: "0.5rem" }} onClick={addSensorRow}>
          + Add sensor from same resource
        </button>

        <div className="form-row-actions" style={{ marginTop: "1rem" }}>
          <ActionButton pending={testPending} pendingLabel="Testing…" disabled={anyPending} onClick={() => void runTest()}>
            Test resource
          </ActionButton>
          <ActionButton
            pending={registerPending}
            pendingLabel="Registering…"
            disabled={anyPending}
            onClick={() => void registerBundle(true)}
          >
            Register &amp; poll
          </ActionButton>
          <ActionButton
            secondary
            pending={registerPending}
            disabled={anyPending}
            onClick={() => void registerBundle(false)}
          >
            Register only
          </ActionButton>
        </div>

        {testResult?.sensors?.length ? (
          <div style={{ marginTop: "0.75rem" }}>
            <p className="muted">Extracted values (HTTP {testResult.status_code}):</p>
            <ul>
              {testResult.sensors.map((s) => (
                <li key={s.label}>
                  <code>{s.label}</code> [{s.json_path}] → <code>{s.present_value ?? "—"}</code>
                  {s.units ? ` ${s.units}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : testResult?.present_value ? (
          <p className="muted" style={{ marginTop: "0.75rem" }}>
            Test OK → <code>{testResult.present_value}</code>
          </p>
        ) : null}
        {rawPreview ? (
          <details style={{ marginTop: "0.75rem" }}>
            <summary className="muted">Raw JSON preview</summary>
            <pre className="console" style={{ maxHeight: "12rem", overflow: "auto" }}>
              {rawPreview}
            </pre>
          </details>
        ) : null}
      </div>

      <div className="panel">
        <h3 className="panel-title">Sensors</h3>
        <details className="ui-advanced-fold">
          <summary>Legend</summary>
          <JsonApiTreeLegend />
        </details>
        {driverDevices.length > 0 ? (
          <div className="bacnet-bulk-toolbar">
            <span className="muted">{selectedPointsList.length} selected</span>
            <button type="button" className="secondary-btn" onClick={selectAllTreePoints}>
              Select all
            </button>
            <button type="button" className="secondary-btn" onClick={() => setSelectedPointIds(new Set())}>
              Clear
            </button>
            {STANDARD_POLL_INTERVALS.map((p) => (
              <ActionButton
                key={p.seconds}
                secondary
                pending={bulkPollPending}
                disabled={anyPending || selectedPointsList.length === 0}
                onClick={() => void batchSetPointPoll(selectedPointsList, true, p.seconds)}
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
          <Spinner label="Loading REST sensors…" />
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
        <pre className="console">{log || "Ready — pick a preset or enter a resource URL, then Test."}</pre>
      </div>
    </div>
  );
}
