import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import HaystackPointsTree, { type HaystackDevice, type HaystackPoint } from "../components/HaystackPointsTree";
import DriverDetailsPanel from "../components/DriverDetailsPanel";
import PageHeader from "../components/PageHeader";
import Spinner from "../components/Spinner";
import ActionButton from "../components/ActionButton";
import { TabDebugPanel } from "../components/TabDebugPanel";

type HaystackStatus = {
  ok?: boolean;
  enabled?: boolean;
  driver?: string;
  status?: string;
  mode?: string;
  message?: string;
  source_id?: string;
  supported_ops?: string[];
  config?: {
    base_url?: string | null;
    username?: string | null;
    password_set?: boolean;
    auth_mode?: string;
    tls_verify?: boolean;
  };
};

type HaystackTreeResponse = {
  ok?: boolean;
  enabled?: boolean;
  devices?: HaystackDevice[];
  message?: string;
};

function rowsToDevices(rows: Array<Record<string, unknown>>, baseUrl: string): HaystackDevice[] {
  const points: HaystackPoint[] = rows
    .filter((r) => r.point === "M")
    .map((r) => ({
      point_id: String(r.id ?? ""),
      label: String(r.dis ?? r.id ?? ""),
      haystack_id: String(r.id ?? ""),
      tags: r,
      kind: r.kind,
      unit: r.unit,
      curVal: r.curVal,
      present_value: r.curVal != null ? String(r.curVal) : "—",
      enabled: false,
      poll_interval_s: 0,
      poll_label: "Off",
      mapping_status:
        r.bacnetRef || r.fddInput ? ("mapped" as const) : ("unmapped" as const),
    }));
  const equipRows = rows.filter((r) => r.equip === "M");
  if (equipRows.length === 0 && points.length > 0) {
    return [
      {
        device_key: "haystack-import",
        host: baseUrl,
        site_id: "site:local",
        point_count: points.length,
        poll_count: 0,
        points,
      },
    ];
  }
  return equipRows.map((eq) => {
    const equipId = String(eq.id ?? "");
    const equipPoints = points.filter((p) => {
      const ref = (p.tags?.equipRef as string | undefined) ?? "";
      return ref === equipId || ref === "";
    });
    return {
      device_key: equipId,
      host: baseUrl,
      site_id: String(eq.siteRef ?? "site:local"),
      point_count: equipPoints.length,
      poll_count: 0,
      points: equipPoints,
    };
  });
}

export default function HaystackPage() {
  const [status, setStatus] = useState<HaystackStatus | null>(null);
  const [about, setAbout] = useState<Record<string, unknown> | null>(null);
  const [ops, setOps] = useState<Record<string, unknown> | null>(null);
  const [devices, setDevices] = useState<HaystackDevice[]>([]);
  const [selectedPoint, setSelectedPoint] = useState<HaystackPoint | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [log, setLog] = useState("");
  const [error, setError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advancedJson, setAdvancedJson] = useState("");

  const baseUrl = status?.config?.base_url ?? "—";
  const enabled = status?.enabled ?? false;

  const appendLog = (line: string) =>
    setLog((prev) => `${new Date().toISOString()} ${line}\n${prev}`.slice(0, 12000));

  const loadStatus = useCallback(async () => {
    const st = await apiFetch<HaystackStatus>("/api/haystack/status");
    setStatus(st);
  }, []);

  const loadTree = useCallback(async () => {
    const tree = await apiFetch<HaystackTreeResponse>("/api/haystack/driver/tree");
    if (tree.devices?.length) {
      setDevices(tree.devices);
      return;
    }
    const grid = await apiFetch<{ rows?: Array<Record<string, unknown>> }>("/api/model/haystack");
    setDevices(rowsToDevices(grid.rows ?? [], String(status?.config?.base_url ?? "")));
  }, [status?.config?.base_url]);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadStatus(), loadTree()])
      .catch((e) => setError(formatApiError(e)))
      .finally(() => setLoading(false));
  }, [loadStatus, loadTree]);

  async function testConnection() {
    setPending(true);
    setError("");
    try {
      const res = await apiFetch<HaystackStatus>("/api/haystack/test", { method: "POST", body: "{}" });
      setStatus(res);
      appendLog(`Test: ${res.message ?? res.status ?? "ok"}`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function loadAbout() {
    setPending(true);
    try {
      const res = await apiFetch<{ records?: Record<string, unknown> }>("/api/haystack/about");
      setAbout(res.records ?? res);
      appendLog("Loaded Haystack about");
      if (showAdvanced) setAdvancedJson(JSON.stringify(res, null, 2));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function loadOps() {
    setPending(true);
    try {
      const res = await apiFetch<{ records?: Record<string, unknown> }>("/api/haystack/ops");
      setOps(res.records ?? res);
      appendLog("Loaded Haystack ops");
      if (showAdvanced) setAdvancedJson(JSON.stringify(res, null, 2));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function browseNav() {
    setPending(true);
    try {
      const res = await apiFetch("/api/haystack/nav", { method: "POST", body: "{}" });
      appendLog("Haystack nav browse completed");
      if (showAdvanced) setAdvancedJson(JSON.stringify(res, null, 2));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function readSelected() {
    setPending(true);
    try {
      const ids = Array.from(selectedIds);
      const body = ids.length ? JSON.stringify({ ids }) : JSON.stringify({ filter: "point" });
      const res = await apiFetch("/api/haystack/read", { method: "POST", body });
      appendLog(`Haystack read completed (${ids.length || "filter"} points)`);
      await loadTree();
      if (showAdvanced) setAdvancedJson(JSON.stringify(res, null, 2));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function pollOnce() {
    setPending(true);
    try {
      const res = await apiFetch<{ samples?: unknown[]; message?: string }>("/api/haystack/poll-once", {
        method: "POST",
        body: JSON.stringify({ filter: "point" }),
      });
      appendLog(`Poll once: ${res.message ?? "done"} (${res.samples?.length ?? 0} samples)`);
      await loadTree();
      if (showAdvanced) setAdvancedJson(JSON.stringify(res, null, 2));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setPending(false);
    }
  }

  async function importModel() {
    setPending(true);
    try {
      const res = await apiFetch<{ imported?: number; message?: string }>("/api/haystack/import", {
        method: "POST",
        body: JSON.stringify({ filter: "site or equip or point" }),
      });
      appendLog(`Import: ${res.message ?? "done"} (${res.imported ?? 0} records)`);
      await loadTree();
      if (showAdvanced) setAdvancedJson(JSON.stringify(res, null, 2));
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
        subtitle="Haystack server workflow for Niagara nHaystack — browse nav, read points, import model entities."
      />

      {error ? <p className="error">{error}</p> : null}

      {!enabled && !loading ? (
        <div className="panel callout-panel">
          <p>
            Haystack is disabled or not configured. Set{" "}
            <code>OPENFDD_HAYSTACK_BASE</code> / credentials locally or copy{" "}
            <code>workspace/haystack/local.nhaystack.example.toml</code> to a gitignored file.
          </p>
        </div>
      ) : null}

      <div className="panel driver-connection-panel">
        <h3>Haystack server</h3>
        <dl className="detail-grid">
          <div>
            <dt>Status</dt>
            <dd>{status?.status ?? "—"}</dd>
          </div>
          <div>
            <dt>Base URL</dt>
            <dd>{baseUrl}</dd>
          </div>
          <div>
            <dt>Credentials</dt>
            <dd>
              {status?.config?.username ?? "—"}
              {status?.config?.password_set ? " · password set" : " · no password"}
            </dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{status?.source_id ?? "—"}</dd>
          </div>
        </dl>
        <div className="btn-row">
          <ActionButton pending={pending} onClick={() => void testConnection()}>
            Test connection
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void loadAbout()}>
            About
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void loadOps()}>
            Ops
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void browseNav()}>
            Browse / Nav
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void readSelected()}>
            Read selected
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void pollOnce()}>
            Poll once
          </ActionButton>
          <ActionButton pending={pending} onClick={() => void importModel()}>
            Import model
          </ActionButton>
        </div>
        {about ? (
          <p className="muted">
            About: {String((about as Record<string, unknown>).serverName ?? (about as Record<string, unknown>).productName ?? "Haystack server")}
          </p>
        ) : null}
        {ops ? (
          <p className="muted">Ops loaded — use Advanced to inspect supported operations.</p>
        ) : null}
        <label className="checkbox-inline">
          <input type="checkbox" checked={showAdvanced} onChange={(e) => setShowAdvanced(e.target.checked)} />
          Advanced (raw JSON)
        </label>
        {showAdvanced && advancedJson ? <pre className="driver-log">{advancedJson}</pre> : null}
      </div>

      <div className="driver-split">
        <div className="panel">
          <h3>Sites, equipment &amp; points</h3>
          {loading ? <Spinner label="Loading Haystack tree…" /> : null}
          <HaystackPointsTree
            devices={devices}
            onSelectPoint={(_dev, pt) => {
              setSelectedPoint(pt);
              setSelectedIds(new Set([pt.haystack_id]));
            }}
            onCopy={(text) => appendLog(`Copied ${text}`)}
          />
        </div>
        <DriverDetailsPanel
          selection={
            selectedPoint
              ? {
                  protocol: "haystack",
                  title: selectedPoint.label,
                  fields: [
                    { label: "Haystack ID", value: selectedPoint.haystack_id },
                    { label: "Kind", value: String(selectedPoint.kind ?? "—") },
                    { label: "Unit", value: String(selectedPoint.unit ?? "—") },
                    { label: "curVal", value: String(selectedPoint.curVal ?? selectedPoint.present_value ?? "—") },
                    {
                      label: "Mapping",
                      value: String(selectedPoint.mapping_status ?? "unmapped"),
                    },
                    { label: "Source", value: status?.source_id ?? "—" },
                  ],
                }
              : null
          }
        />
      </div>

      <div className="panel driver-console">
        <h3>Activity console</h3>
        <pre className="driver-log">{log || "No activity yet."}</pre>
      </div>

      <TabDebugPanel tab="haystack" endpoints={["/api/haystack/status", "/api/haystack/driver/tree"]} />
    </div>
  );
}
