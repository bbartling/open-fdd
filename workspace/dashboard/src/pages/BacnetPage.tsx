import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type BacnetConfig = {
  points_exists: boolean;
  discovered_exists: boolean;
  poll_exists: boolean;
  poll_csv: string;
  discovered_csv: string;
  points_csv: string;
  commission_agent_ok: boolean;
};

type CommissionStatus = {
  site_id?: string;
  building_id?: string;
  bacnet_bind?: string;
  discover_range?: [string, string];
  last_jobs?: Array<{ id: string; kind: string; status: string }>;
};

type DiscoverJob = {
  job_id: string;
  kind: string;
  status?: string;
  exit_code?: number | null;
  log_tail?: string;
  result?: unknown;
  output?: string;
};

type WhoIsDevice = {
  "i-am-device-identifier"?: string;
  "device-address"?: string;
  "device-description"?: string;
  "vendor-id"?: number;
};

export default function BacnetPage() {
  const [cfg, setCfg] = useState<BacnetConfig | null>(null);
  const [status, setStatus] = useState<CommissionStatus | null>(null);
  const [loadError, setLoadError] = useState("");
  const [log, setLog] = useState("");
  const [whoisLow, setWhoisLow] = useState(5007);
  const [whoisHigh, setWhoisHigh] = useState(5007);
  const [deviceInst, setDeviceInst] = useState(5007);
  const [busy, setBusy] = useState(false);
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [whoisDevices, setWhoisDevices] = useState<WhoIsDevice[]>([]);
  const [writeOid, setWriteOid] = useState("analog-value,1");
  const [writeValue, setWriteValue] = useState("72");
  const [writePriority, setWritePriority] = useState(8);

  const refresh = useCallback(async () => {
    const [c, s] = await Promise.all([
      apiFetch<BacnetConfig>("/config/bacnet"),
      apiFetch<CommissionStatus>("/api/bacnet/commission/status").catch(() => null),
    ]);
    setCfg(c);
    if (s) {
      setStatus(s);
      if (s.discover_range?.length === 2) {
        setWhoisLow(Number(s.discover_range[0]) || 1);
        setWhoisHigh(Number(s.discover_range[1]) || 4194303);
      }
    }
  }, []);

  useEffect(() => {
    refresh().catch((e) => {
      setLoadError(String(e));
      setLog(String(e));
    });
  }, [refresh]);

  useEffect(() => {
    if (!activeJob) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const job = await apiFetch<DiscoverJob>(`/api/bacnet/jobs/${activeJob}`);
        if (cancelled) return;
        const tail = job.log_tail?.trim();
        const resultText = job.result ? `\n--- result ---\n${JSON.stringify(job.result, null, 2)}` : "";
        setLog(
          [
            `Job ${job.job_id} (${job.kind ?? "?"}) — ${job.status ?? "unknown"}`,
            job.output ? `output: ${job.output}` : "",
            tail ? `\n--- log ---\n${tail}` : "",
            resultText,
          ]
            .filter(Boolean)
            .join("\n"),
        );
        if (job.status && job.status !== "running") {
          setActiveJob(null);
          setBusy(false);
          await refresh();
        }
      } catch (e) {
        if (!cancelled) setLog(String(e));
      }
    };
    poll();
    const id = window.setInterval(poll, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [activeJob, refresh]);

  async function runWhoIs() {
    setBusy(true);
    setLog(`Who-Is ${whoisLow}–${whoisHigh}…`);
    try {
      const res = await apiFetch<{ devices: WhoIsDevice[]; count: number }>("/api/bacnet/whois", {
        method: "POST",
        body: JSON.stringify({ range_low: whoisLow, range_high: whoisHigh }),
      });
      setWhoisDevices(res.devices ?? []);
      setLog(`Who-Is found ${res.count ?? 0} device(s)`);
    } catch (e) {
      setLog(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runDiscoverCsv() {
    setBusy(true);
    try {
      const res = await apiFetch<DiscoverJob>("/api/bacnet/discover", {
        method: "POST",
        body: JSON.stringify({ range_low: whoisLow, range_high: whoisHigh }),
      });
      setActiveJob(res.job_id);
      setLog(`CSV discover job ${res.job_id} started`);
    } catch (e) {
      setLog(String(e));
      setBusy(false);
    }
  }

  async function runPointDiscovery() {
    setBusy(true);
    try {
      const res = await apiFetch<DiscoverJob>("/api/bacnet/point-discovery", {
        method: "POST",
        body: JSON.stringify({ device_instance: deviceInst }),
      });
      setActiveJob(res.job_id);
      setLog(`Point discovery job ${res.job_id} for device ${deviceInst}`);
    } catch (e) {
      setLog(String(e));
      setBusy(false);
    }
  }

  async function runSupervisory() {
    setBusy(true);
    try {
      const res = await apiFetch<DiscoverJob>("/api/bacnet/supervisory-check", {
        method: "POST",
        body: JSON.stringify({ device_instance: deviceInst }),
      });
      setActiveJob(res.job_id);
      setLog(`Supervisory check job ${res.job_id} for device ${deviceInst}`);
    } catch (e) {
      setLog(String(e));
      setBusy(false);
    }
  }

  async function runWrite(release: boolean) {
    setBusy(true);
    try {
      const res = await apiFetch<Record<string, unknown>>("/api/bacnet/write", {
        method: "POST",
        body: JSON.stringify({
          device_instance: deviceInst,
          object_identifier: writeOid,
          property_identifier: "present-value",
          value: release ? null : Number.isNaN(Number(writeValue)) ? writeValue : Number(writeValue),
          priority: writePriority,
        }),
      });
      setLog(JSON.stringify(res, null, 2));
    } catch (e) {
      setLog(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function ingest() {
    try {
      const res = await apiFetch<{ ok: boolean; rows: number; feather_path: string }>(
        "/ingest/bacnet?site_id=demo",
        { method: "POST" },
      );
      setLog(`Ingested ${res.rows} rows → ${res.feather_path}`);
    } catch (e) {
      setLog(String(e));
    }
  }

  const badge = (ok: boolean) => (
    <span className={ok ? "badge ok" : "badge"}>{ok ? "yes" : "no"}</span>
  );

  return (
    <div>
      <h2>BACnet commissioning</h2>
      <p className="muted">
        Discover, point inventory, supervisory override scan, write/release, poll → ingest.
      </p>

      <div className="panel">
        <h3>Files & agent</h3>
        {loadError ? (
          <p className="error">{loadError}</p>
        ) : cfg ? (
          <ul className="file-list">
            <li>Commission agent {badge(cfg.commission_agent_ok)}</li>
            <li>points.csv {badge(cfg.points_exists)}</li>
            <li>points_discovered.csv {badge(cfg.discovered_exists)}</li>
            <li>poll CSV {badge(cfg.poll_exists)}</li>
          </ul>
        ) : (
          <p className="muted">Loading…</p>
        )}
        {status?.bacnet_bind ? (
          <p className="muted">
            Bind <code>{status.bacnet_bind}</code> · {status.site_id}/{status.building_id}
          </p>
        ) : null}
        <div className="row">
          <button type="button" className="secondary" onClick={() => refresh().catch((e) => setLog(String(e)))}>
            Refresh
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Discover devices</h3>
        <div className="form-row">
          <label>
            Start
            <input type="number" value={whoisLow} onChange={(e) => setWhoisLow(Number(e.target.value))} />
          </label>
          <label>
            End
            <input type="number" value={whoisHigh} onChange={(e) => setWhoisHigh(Number(e.target.value))} />
          </label>
          <button type="button" onClick={runWhoIs} disabled={busy || !cfg?.commission_agent_ok}>
            Who-Is (live)
          </button>
          <button type="button" className="secondary" onClick={runDiscoverCsv} disabled={busy || !cfg?.commission_agent_ok}>
            Discover → CSV
          </button>
        </div>
        {whoisDevices.length > 0 ? (
          <ul className="job-list">
            {whoisDevices.map((d, i) => (
              <li key={i}>
                <code>{d["i-am-device-identifier"]}</code> @ {d["device-address"]} — {d["device-description"]}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="panel">
        <h3>Point discovery & supervisory</h3>
        <div className="form-row">
          <label>
            Device instance
            <input type="number" value={deviceInst} onChange={(e) => setDeviceInst(Number(e.target.value))} />
          </label>
          <button type="button" onClick={runPointDiscovery} disabled={busy || !cfg?.commission_agent_ok}>
            Point discovery
          </button>
          <button type="button" className="secondary" onClick={runSupervisory} disabled={busy || !cfg?.commission_agent_ok}>
            Supervisory overrides
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Write / release (present-value)</h3>
        <div className="form-row">
          <label>
            Object id
            <input value={writeOid} onChange={(e) => setWriteOid(e.target.value)} placeholder="analog-value,1" />
          </label>
          <label>
            Value
            <input value={writeValue} onChange={(e) => setWriteValue(e.target.value)} />
          </label>
          <label>
            Priority
            <input type="number" min={1} max={16} value={writePriority} onChange={(e) => setWritePriority(Number(e.target.value))} />
          </label>
          <button type="button" onClick={() => runWrite(false)} disabled={busy || !cfg?.commission_agent_ok}>
            Write
          </button>
          <button type="button" className="secondary" onClick={() => runWrite(true)} disabled={busy || !cfg?.commission_agent_ok}>
            Release (null)
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Poll → ingest</h3>
        <div className="row">
          <button type="button" onClick={ingest} disabled={!cfg?.poll_exists}>
            Ingest poll CSV
          </button>
        </div>
        <pre className="console">{log || "Ready."}</pre>
      </div>
    </div>
  );
}
