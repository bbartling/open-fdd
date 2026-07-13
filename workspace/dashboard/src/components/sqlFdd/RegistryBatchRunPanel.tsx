import { useEffect, useMemo, useState } from "react";
import { RULE_STATUSES } from "../../lib/ruleStatus";
import { apiFetch } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";
import type { FaultTimelinePoint } from "../charts/FaultTimeline";
import RuleResultChart from "../charts/RuleResultChart";
import { mapSeriesToFaultTimelinePoints } from "../../lib/faultTimelineMap";

type Timing = {
  rule_id: string;
  status: string;
  row_count: number;
  elapsed_ms: number;
  error?: string;
};

type BatchResponse = {
  ok?: boolean;
  error?: string;
  hint?: string;
  rules_run?: number;
  rules_succeeded?: number;
  rules_failed?: number;
  rules_skipped?: number;
  total_ms?: number;
  timings?: Timing[];
};

type EquipRow = {
  equipment_id: string;
  status?: string;
  fault_hours?: number | null;
  equipment_type?: string;
  reason?: string;
};

type SeriesResponse = {
  ok?: boolean;
  error?: string;
  rule_id?: string;
  equipment_id?: string;
  gate_mode?: string;
  point_count?: number;
  points?: FaultTimelinePoint[];
};

export default function RegistryBatchRunPanel() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<BatchResponse | null>(null);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [equipRows, setEquipRows] = useState<EquipRow[]>([]);
  const [equipBusy, setEquipBusy] = useState(false);
  const [selectedEquipmentId, setSelectedEquipmentId] = useState<string | null>(null);
  const [series, setSeries] = useState<SeriesResponse | null>(null);
  const [seriesBusy, setSeriesBusy] = useState(false);
  const [seriesError, setSeriesError] = useState("");

  const rows = useMemo(() => {
    const list = result?.timings ?? [];
    if (statusFilter === "ALL") return list;
    return list.filter((t) => t.status === statusFilter);
  }, [result?.timings, statusFilter]);

  const chartPoints = useMemo(
    () => mapSeriesToFaultTimelinePoints(series?.points ?? []),
    [series?.points],
  );

  async function runBatch() {
    setBusy(true);
    setError("");
    setSelectedRuleId(null);
    setSelectedEquipmentId(null);
    setEquipRows([]);
    setSeries(null);
    try {
      const out = await apiFetch<BatchResponse>("/api/fdd/run", {
        method: "POST",
        body: JSON.stringify({ mode: "registry" }),
      });
      setResult(out);
      if (!out.ok) setError(out.error ?? "Batch run failed");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function selectRule(ruleId: string) {
    setSelectedRuleId(ruleId);
    setSelectedEquipmentId(null);
    setSeries(null);
    setSeriesError("");
    setError("");
    setEquipBusy(true);
    try {
      const out = await apiFetch<{
        ok?: boolean;
        error?: string;
        result?: { rows?: EquipRow[] };
      }>(`/api/fdd/results/${encodeURIComponent(ruleId)}`);
      if (!out.ok) {
        setEquipRows([]);
        setError(out.error ?? "Failed to load rule results");
        return;
      }
      setEquipRows(out.result?.rows ?? []);
    } catch (e) {
      setEquipRows([]);
      setError(formatApiError(e));
    } finally {
      setEquipBusy(false);
    }
  }

  useEffect(() => {
    if (!selectedRuleId || !selectedEquipmentId) return;
    let cancelled = false;
    (async () => {
      setSeriesBusy(true);
      setSeriesError("");
      try {
        const q = new URLSearchParams({
          equipment_id: selectedEquipmentId,
          max_points: "4000",
        });
        const out = await apiFetch<SeriesResponse>(
          `/api/fdd/results/${encodeURIComponent(selectedRuleId)}/series?${q}`,
        );
        if (cancelled) return;
        setSeries(out);
        if (!out.ok) setSeriesError(out.error ?? "Series load failed");
      } catch (e) {
        if (!cancelled) {
          setSeries(null);
          setSeriesError(formatApiError(e));
        }
      } finally {
        if (!cancelled) setSeriesBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedRuleId, selectedEquipmentId]);

  return (
    <section className="panel registry-batch-panel">
      <div className="panel-head">
        <h3>Batch analytics (registry)</h3>
        <button type="button" className="primary-btn" disabled={busy} onClick={() => void runBatch()}>
          {busy ? "Running…" : "Run all SQL rules"}
        </button>
      </div>
      <p className="muted small">
        Executes <code>sql_rules/registry.yaml</code> against the Parquet cache (
        <code>OPENFDD_PARQUET_CACHE</code>). Click a rule, then equipment, to open the Plotly fault
        timeline (gate / raw / confirmed).
      </p>
      {error ? <p className="error-text">{error}</p> : null}
      {result?.ok ? (
        <>
          <div className="gf-context-bar">
            <span className="gf-pill gf-pill--muted">run {result.rules_run}</span>
            <span className="gf-pill gf-pill--muted">ok {result.rules_succeeded}</span>
            <span className="gf-pill gf-pill--muted">skip {result.rules_skipped}</span>
            <span className="gf-pill gf-pill--muted">error {result.rules_failed}</span>
            <span className="gf-pill gf-pill--muted">{result.total_ms} ms</span>
            <label className="gf-context-bar__field">
              <span className="gf-field__label">Status</span>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="ALL">All</option>
                {RULE_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Status</th>
                  <th>Rows</th>
                  <th>ms</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr
                    key={t.rule_id}
                    className={selectedRuleId === t.rule_id ? "is-selected" : undefined}
                    style={{ cursor: "pointer" }}
                    tabIndex={0}
                    role="button"
                    aria-pressed={selectedRuleId === t.rule_id}
                    onClick={() => void selectRule(t.rule_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        void selectRule(t.rule_id);
                      }
                    }}
                  >
                    <td>
                      <code>{t.rule_id}</code>
                    </td>
                    <td>{t.status}</td>
                    <td>{t.row_count}</td>
                    <td>{t.elapsed_ms}</td>
                    <td className="muted">{t.error ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {selectedRuleId ? (
        <div className="registry-batch-detail" style={{ marginTop: "1rem" }}>
          <h4>
            Equipment results — <code>{selectedRuleId}</code>
          </h4>
          {equipBusy ? <p className="muted">Loading equipment rows…</p> : null}
          {!equipBusy && equipRows.length === 0 ? (
            <p className="muted">No equipment rows in cached result.</p>
          ) : null}
          {equipRows.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Equipment</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Fault hours</th>
                  </tr>
                </thead>
                <tbody>
                  {equipRows.map((r) => (
                    <tr
                      key={r.equipment_id}
                      className={selectedEquipmentId === r.equipment_id ? "is-selected" : undefined}
                      style={{ cursor: "pointer" }}
                      tabIndex={0}
                      role="button"
                      aria-pressed={selectedEquipmentId === r.equipment_id}
                      onClick={() => setSelectedEquipmentId(r.equipment_id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedEquipmentId(r.equipment_id);
                        }
                      }}
                    >
                      <td>
                        <code>{r.equipment_id}</code>
                      </td>
                      <td>{r.equipment_type ?? ""}</td>
                      <td>{r.status ?? ""}</td>
                      <td>{r.fault_hours ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      {selectedRuleId && selectedEquipmentId ? (
        <div className="registry-batch-chart" style={{ marginTop: "1rem" }}>
          <h4>
            Fault timeline — <code>{selectedRuleId}</code> / <code>{selectedEquipmentId}</code>
            {series?.gate_mode ? (
              <span className="muted small"> · gate {series.gate_mode}</span>
            ) : null}
          </h4>
          {seriesBusy ? <p className="muted">Loading series…</p> : null}
          {seriesError ? <p className="error-text">{seriesError}</p> : null}
          {!seriesBusy && !seriesError && chartPoints.length === 0 ? (
            <p className="muted">No sample points for this selection.</p>
          ) : null}
          {!seriesBusy && chartPoints.length > 0 ? (
            <RuleResultChart
              ruleId={selectedRuleId}
              equipmentId={selectedEquipmentId}
              gateMode={series?.gate_mode}
              points={chartPoints}
              height={260}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
