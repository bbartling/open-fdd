import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import HaystackPointsTree, { type HaystackDevice, type HaystackPoint } from "../components/HaystackPointsTree";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import ActionButton from "../components/ActionButton";

type HaystackStatus = {
  ok?: boolean;
  driver?: string;
  status?: string;
  mode?: string;
  supported_ops?: string[];
};

export default function HaystackPage() {
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8080/api/haystack");
  const [verifyTls, setVerifyTls] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [status, setStatus] = useState<HaystackStatus | null>(null);
  const [about, setAbout] = useState<Record<string, unknown> | null>(null);
  const [devices, setDevices] = useState<HaystackDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [log, setLog] = useState("");
  const [error, setError] = useState("");

  const appendLog = (line: string) => setLog((prev) => `${new Date().toISOString()} ${line}\n${prev}`.slice(0, 8000));

  const loadStatus = useCallback(async () => {
    const st = await apiFetch<HaystackStatus>("/api/haystack/status");
    setStatus(st);
    const ab = await apiFetch<Record<string, unknown>>("/api/haystack/about");
    setAbout(ab);
  }, []);

  const loadModelTree = useCallback(async () => {
    const grid = await apiFetch<{ rows?: Array<Record<string, unknown>> }>("/api/model/haystack");
    const rows = grid.rows ?? [];
    const points: HaystackPoint[] = rows
      .filter((r) => r.point === "M")
      .map((r) => ({
        point_id: String(r.id ?? ""),
        label: String(r.dis ?? r.id ?? ""),
        haystack_id: String(r.id ?? ""),
        tags: {},
        kind: r.kind,
        unit: r.unit,
        curVal: r.curVal,
        present_value: r.curVal != null ? String(r.curVal) : "—",
        enabled: false,
        poll_interval_s: 0,
        poll_label: "Off",
      }));
    setDevices([
      {
        device_key: "haystack-model",
        host: baseUrl,
        site_id: "site:validation",
        point_count: points.length,
        poll_count: 0,
        points,
      },
    ]);
  }, [baseUrl]);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadStatus(), loadModelTree()])
      .catch((e) => setError(formatApiError(e)))
      .finally(() => setLoading(false));
  }, [loadStatus, loadModelTree]);

  async function testConnection() {
    setPending(true);
    setError("");
    try {
      await loadStatus();
      appendLog(`Connection OK — mode=${status?.mode ?? "unknown"}`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function importFromSmokeProfile() {
    setPending(true);
    setError("");
    try {
      const res = await apiFetch<{ ok?: boolean; imported?: number; path?: string }>(
        "/api/model/haystack/from-smoke-profile",
        { method: "POST", body: "{}" },
      );
      appendLog(`Imported smoke profile → ${res.imported ?? 0} rows (${res.path ?? "model"})`);
      await loadModelTree();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function readSelected() {
    setPending(true);
    try {
      await apiFetch("/api/haystack/read", { method: "POST", body: "{}" });
      appendLog("Haystack read completed");
      await loadModelTree();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="page page-wide driver-page">
      <PageHeader
        title="Haystack"
        subtitle="Haystack server workflow — replaces the old Niagara station tab. Browse nav, read points, import model entities."
      />

      {error ? <p className="error">{error}</p> : null}

      <div className="panel driver-connection-panel">
        <h3>Haystack server</h3>
        <div className="form-grid">
          <label>
            Server URL
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://host/api/haystack" />
          </label>
          <label className="checkbox-inline">
            <input type="checkbox" checked={verifyTls} onChange={(e) => setVerifyTls(e.target.checked)} />
            Verify TLS (uncheck for self-signed lab certs)
          </label>
          <label className="checkbox-inline">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Enabled
          </label>
        </div>
        <div className="btn-row">
          <ActionButton pending={pending} onClick={() => void testConnection()}>
            Test connection
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void importFromSmokeProfile()}>
            Import validation smoke profile
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void readSelected()}>
            Read / refresh
          </ActionButton>
        </div>
        {status ? (
          <p className="muted">
            Driver: {status.driver ?? "haystack"} · {status.mode ?? status.status ?? "unknown"} · ops:{" "}
            {(status.supported_ops ?? []).join(", ") || "about, ops, read, nav"}
          </p>
        ) : null}
        {about ? (
          <p className="muted">
            About: {String(about.serverName ?? "open-fdd")} · Haystack {String(about.haystackVersion ?? "3.0")}
          </p>
        ) : null}
        <p className="muted">Schedules: not supported on fixture gateway — omit unless your Haystack server exposes them.</p>
      </div>

      <div className="panel">
        <h3>Sites, equipment &amp; points</h3>
        {loading ? <Spinner label="Loading Haystack model tree…" /> : null}
        <HaystackPointsTree devices={devices} onCopy={(text) => appendLog(`Copied ${text}`)} />
      </div>

      <div className="panel driver-console">
        <h3>Activity console</h3>
        <pre className="driver-log">{log || "No activity yet."}</pre>
      </div>
    </div>
  );
}
