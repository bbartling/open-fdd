import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type SmokeStatus = {
  ok?: boolean;
  device_instance?: number;
  equipment_id?: string;
  data_source?: string;
  demo_only?: boolean;
  historian?: { row_count?: number; last_sample_at?: string; jsonl?: string; arrow_ipc?: string };
  bacnet_points?: Array<{ name: string; fdd_input: string; bacnet_id: string }>;
  modbus?: { available?: boolean; configured_host?: string; configured_port?: string; last_read?: Record<string, unknown> };
  json_api?: { ok?: boolean; url?: string; http_status?: number };
  haystack?: { equip?: string; points?: string[] };
  rule_sql?: string;
  fdd_eval?: {
    ok?: boolean;
    rows?: Array<Record<string, unknown>>;
    confirmation?: { raw_fault_count?: number; confirmed_fault_count?: number; confirmation_seconds?: number };
  };
  proof?: {
    demo_only?: boolean;
    live_fdd_pass?: boolean;
    raw_fault_samples?: number;
    confirmed_fault_samples?: number;
    message?: string;
  };
  artifact_dir?: string;
};

function FaultPill({ label, active, tone }: { label: string; active: boolean; tone: "ok" | "warn" | "bad" }) {
  return (
    <span className={`fault-pill fault-pill-${tone}${active ? " active" : ""}`}>
      {label}: {active ? "TRUE" : "false"}
    </span>
  );
}

export default function Bench5007SmokePage() {
  const [status, setStatus] = useState<SmokeStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch<SmokeStatus>("/api/bench/5007/smoke/status");
      setStatus(res);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(t);
  }, [refresh]);

  const lastRows = status?.fdd_eval?.rows ?? [];
  const latest = lastRows.length ? lastRows[lastRows.length - 1] : null;
  const rawFault = latest?.raw_fault === true;
  const confirmedFault = latest?.confirmed_fault === true;

  return (
    <div className="bench-smoke-page">
      <PageHeader
        title="Bench 5007 — FDD wiresheet"
        subtitle="BACnet 5007 → Arrow historian → DataFusion SQL → raw fault → 5-minute confirmation → confirmed fault. Inspect live proof, not demo mirrors."
      />

      {error ? <div className="error-banner">{error}</div> : null}
      {status?.demo_only ? (
        <div className="warn-banner">
          DEMO ONLY — historian/FDD data is not live BACnet. Run short smoke with live mode or simulation inject for a valid proof.
        </div>
      ) : null}
      {status?.proof?.live_fdd_pass ? (
        <div className="status-banner">Live FDD proof satisfied — raw fault, confirmed fault, and clear behavior verified.</div>
      ) : null}

      <div className="toolbar">
        <button type="button" className="secondary-btn" onClick={() => void refresh()} disabled={busy}>
          Refresh status
        </button>
        <Link to="/drivers" className="secondary-btn">
          BACnet driver tree
        </Link>
        <Link to="/sql-fdd" className="secondary-btn">
          SQL Rule Builder
        </Link>
      </div>

      <section className="panel wiresheet-grid">
        <div className="wire-col">
          <h3>BACnet 5007</h3>
          <p className="muted-copy">Device {status?.device_instance ?? 5007} — 3 temperature + 1 humidity</p>
          {(status?.bacnet_points ?? []).map((p) => (
            <div key={p.bacnet_id} className="wire-node">
              <strong>{p.name}</strong>
              <small>{p.fdd_input}</small>
              <small>{p.bacnet_id}</small>
            </div>
          ))}
        </div>
        <div className="wire-col">
          <h3>Historian (Arrow)</h3>
          <p className="muted-copy">{status?.historian?.jsonl}</p>
          <div className="wire-node">
            <strong>{status?.historian?.row_count ?? 0} rows</strong>
            <small>last: {status?.historian?.last_sample_at ?? "—"}</small>
            <small>{status?.historian?.arrow_ipc}</small>
          </div>
          <div className="wire-node">
            <strong>Modbus RPi</strong>
            <small>
              {status?.modbus?.configured_host}:{status?.modbus?.configured_port} —{" "}
              {status?.modbus?.available ? "reachable" : "unavailable"}
            </small>
          </div>
          <div className="wire-node">
            <strong>JSON API</strong>
            <small>
              HTTP {status?.json_api?.http_status ?? "—"} {status?.json_api?.ok ? "OK" : "fail"}
            </small>
          </div>
        </div>
        <div className="wire-col">
          <h3>Model / Haystack</h3>
          <p className="muted-copy">{status?.haystack?.equip}</p>
          {(status?.haystack?.points ?? []).map((p) => (
            <div key={p} className="wire-node">
              <strong>{p}</strong>
              <small>→ FDD input mapping</small>
            </div>
          ))}
        </div>
        <div className="wire-col">
          <h3>FDD SQL + confirmation</h3>
          <div className="fault-pill-row">
            <FaultPill label="raw_fault" active={rawFault} tone={rawFault ? "bad" : "ok"} />
            <FaultPill label="confirmed_fault" active={confirmedFault} tone={confirmedFault ? "bad" : "ok"} />
          </div>
          <p className="muted-copy">
            confirmation_required_minutes = 5 · raw={status?.proof?.raw_fault_samples ?? 0} · confirmed=
            {status?.fdd_eval?.confirmation?.confirmed_fault_count ?? 0}
          </p>
          <pre className="sql-block sql-block-compact">{status?.rule_sql ?? "Loading SQL…"}</pre>
        </div>
      </section>

      <section className="panel">
        <h3 className="panel-title">Latest SQL result rows</h3>
        <div className="table-like">
          {lastRows.slice(-8).map((row, i) => (
            <div key={i} className="table-row">
              <span>{String(row.timestamp ?? "")}</span>
              <span>oa_t={String(row.oa_t ?? "")}</span>
              <span>raw={String(row.raw_fault ?? false)}</span>
              <span>min={String(row.minutes_in_fault ?? 0)}</span>
              <span>confirmed={String(row.confirmed_fault ?? false)}</span>
            </div>
          ))}
        </div>
        <p className="muted-copy">
          Artifacts: {status?.artifact_dir} · data source: <strong>{status?.data_source}</strong> ·{" "}
          {status?.proof?.message}
        </p>
      </section>
    </div>
  );
}
