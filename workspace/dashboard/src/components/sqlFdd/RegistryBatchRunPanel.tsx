import { useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";

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

export default function RegistryBatchRunPanel() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<BatchResponse | null>(null);
  const [statusFilter, setStatusFilter] = useState("ALL");

  const rows = useMemo(() => {
    const list = result?.timings ?? [];
    if (statusFilter === "ALL") return list;
    return list.filter((t) => t.status === statusFilter);
  }, [result?.timings, statusFilter]);

  async function runBatch() {
    setBusy(true);
    setError("");
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
        <code>OPENFDD_PARQUET_CACHE</code>). Per-rule errors are isolated.
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
                <option value="PASS">PASS</option>
                <option value="FAULT">FAULT</option>
                <option value="SKIPPED_MISSING_ROLES">SKIPPED_MISSING_ROLES</option>
                <option value="ERROR">ERROR</option>
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
                  <tr key={t.rule_id}>
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
    </section>
  );
}
