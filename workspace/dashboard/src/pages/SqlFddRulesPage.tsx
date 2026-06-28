import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../lib/api";
import { copyToClipboard } from "../lib/clipboard";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";

type BuilderState = {
  name: string;
  input: string;
  operator: string;
  value: number;
  equipment_id: string;
  confirmation_seconds: number;
  severity: string;
  fault_code: string;
};

type FddInput = { id: string; label: string };

function validationSummary(payload: Record<string, unknown> | null): string {
  if (!payload) return "";
  if (typeof payload.error === "string") return payload.error;
  if (typeof payload.message === "string") return payload.message;
  if (payload.ok === true) return "SQL validation passed.";
  const issues = payload.issues;
  if (Array.isArray(issues) && issues.length > 0) {
    return issues.map((item) => String(item)).join("; ");
  }
  if (payload.valid === true) return "SQL validation passed.";
  if (payload.valid === false) return "SQL validation failed — check table/column names.";
  return "Validation finished.";
}

function runResultSummary(payload: Record<string, unknown> | null): string {
  if (!payload) return "";
  if (typeof payload.error === "string") return payload.error;
  const confirmation = payload.confirmation as Record<string, unknown> | undefined;
  const confirmed = confirmation?.confirmed_fault_count;
  const raw = confirmation?.raw_fault_count;
  if (typeof confirmed === "number" || typeof raw === "number") {
    return `Raw faults: ${raw ?? 0} · Confirmed: ${confirmed ?? 0}`;
  }
  const rows = payload.rows;
  if (Array.isArray(rows)) {
    return `Preview returned ${rows.length} row(s).`;
  }
  const count = payload.row_count ?? payload.count;
  if (typeof count === "number") return `Preview returned ${count} row(s).`;
  if (payload.ok === true) return "SQL preview completed.";
  return "Preview finished.";
}

function confirmedFaultRows(payload: Record<string, unknown> | null): Record<string, unknown>[] {
  if (!payload?.rows || !Array.isArray(payload.rows)) return [];
  return (payload.rows as Record<string, unknown>[]).filter(
    (r) => r.confirmed_fault === true || r.confirmed_fault === "true",
  );
}

function ruleIdFromBuilder(builder: BuilderState): string {
  const base = builder.fault_code.trim() || builder.name.trim() || "fdd-rule";
  return base.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "fdd-rule";
}

const DEFAULT_BUILDER: BuilderState = {
  name: "OA Temperature Out Of Range",
  input: "oa_t",
  operator: ">",
  value: 110,
  equipment_id: "",
  confirmation_seconds: 300,
  severity: "medium",
  fault_code: "OA_TEMP_OUT_OF_RANGE",
};

export default function SqlFddRulesPage() {
  const siteId = useActiveSiteId();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"builder" | "raw">("builder");
  const [builder, setBuilder] = useState<BuilderState>(DEFAULT_BUILDER);
  const [sql, setSql] = useState("");
  const [rawCustom, setRawCustom] = useState(false);
  const [fddInputs, setFddInputs] = useState<FddInput[]>([]);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const [actionStatus, setActionStatus] = useState("");
  const [error, setError] = useState("");
  const equipmentMissing = mode === "builder" && !builder.equipment_id.trim();
  const confirmedRows = useMemo(() => confirmedFaultRows(runResult), [runResult]);

  useEffect(() => {
    apiFetch<{ fdd_inputs?: FddInput[] }>("/api/fdd-schema/fdd-inputs")
      .then((inputs) => setFddInputs(inputs.fdd_inputs ?? []))
      .catch((e) => setError(formatApiError(e)));
  }, []);

  const previewBuilder = useCallback(async () => {
    try {
      const out = await apiFetch<{ sql?: string; validation?: Record<string, unknown> }>(
        "/api/fdd-rules/builder-sql",
        { method: "POST", body: JSON.stringify(builder) },
      );
      setSql(out.sql ?? "");
      setValidation(out.validation ?? null);
      setRawCustom(false);
    } catch (e) {
      setError(formatApiError(e));
    }
  }, [builder]);

  useEffect(() => {
    if (mode === "builder") void previewBuilder();
  }, [mode, builder.input, builder.operator, builder.value, builder.equipment_id, previewBuilder]);

  async function runSql() {
    if (equipmentMissing) {
      setError("Select equipment first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<Record<string, unknown>>("/api/fdd-rules/oa_temp_out_of_range/test-sql", {
        method: "POST",
        body: JSON.stringify({
          sql,
          confirmation_seconds: builder.confirmation_seconds,
          params: { equipment_id: builder.equipment_id },
        }),
      });
      setRunResult(out);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!siteId) return;
    apiFetch<{ equipment?: { id?: string; equipment_id?: string }[] }>(
      `/api/model/sites/${encodeURIComponent(siteId)}/equipment`,
    )
      .then((res) => {
        const first = res.equipment?.[0]?.id ?? res.equipment?.[0]?.equipment_id;
        if (first) {
          setBuilder((b) => (b.equipment_id ? b : { ...b, equipment_id: first }));
        }
      })
      .catch(() => setError("Could not load equipment for this site — enter an equip id manually."));
  }, [siteId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") void runSql();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function validateSql() {
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<Record<string, unknown>>("/api/fdd-rules/oa_temp_out_of_range/validate-sql", {
        method: "POST",
        body: JSON.stringify({ sql }),
      });
      setValidation(out);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveActivateAndDashboard() {
    const ruleId = ruleIdFromBuilder(builder);
    setBusy(true);
    setError("");
    setActionStatus("");
    try {
      await apiFetch("/api/fdd-rules", {
        method: "POST",
        body: JSON.stringify({
          rule_id: ruleId,
          name: builder.name,
          sql,
          confirmation_seconds: builder.confirmation_seconds,
          review_status: "approved",
          severity: builder.severity,
          output_fault_code: builder.fault_code,
          equipment_id: builder.equipment_id,
          site_id: siteId,
        }),
      });
      await apiFetch(`/api/fdd-rules/${encodeURIComponent(ruleId)}/activate`, {
        method: "POST",
        body: "{}",
      });
      window.dispatchEvent(new CustomEvent("ofdd-dashboard-refresh"));
      setActionStatus(`Rule "${ruleId}" saved and activated — faults appear on the main dashboard.`);
      navigate("/");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function exportPdfReport() {
    setBusy(true);
    setError("");
    setActionStatus("");
    try {
      const out = await apiFetch<{ report_id?: string; pdf?: { download_url?: string } }>(
        "/api/reports/from-fdd-sql-run",
        {
          method: "POST",
          body: JSON.stringify({
            rule_name: builder.name,
            sql,
            equipment_id: builder.equipment_id,
            fault_code: builder.fault_code,
            run_result: runResult,
          }),
        },
      );
      const url = out.pdf?.download_url;
      setActionStatus(
        url
          ? `PDF report ${out.report_id ?? ""} ready — open Reports tab or download.`
          : `Report draft ${out.report_id ?? ""} created.`,
      );
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page page-wide sql-fdd-page">
      <PageHeader
        title="SQL FDD Rules"
        subtitle={
          <>
            DataFusion SQL rules for site <code>{siteId || "…"}</code>. Map points on{" "}
            <Link to="/model">Model & FDD assignments</Link> or the{" "}
            <Link to="/wiresheet">FDD Wiresheet</Link>.
          </>
        }
      />

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="sql-fdd-layout">
        <section className="panel sql-fdd-builder-panel">
          <div className="sql-fdd-toolbar">
            <h2 className="panel-title">Rule builder</h2>
            <div className="action-bar sql-fdd-mode-bar">
              <button
                type="button"
                className={mode === "builder" ? "primary-btn" : "secondary-btn"}
                onClick={() => {
                  setMode("builder");
                  setRawCustom(false);
                }}
              >
                Visual builder
              </button>
              <button
                type="button"
                className={mode === "raw" ? "primary-btn" : "secondary-btn"}
                onClick={() => setMode("raw")}
              >
                Raw SQL
              </button>
              {mode === "raw" ? (
                <button type="button" className="secondary-btn" onClick={() => void validateSql()} disabled={busy}>
                  Validate SQL
                </button>
              ) : null}
              <button
                type="button"
                className="primary-btn"
                onClick={() => void runSql()}
                disabled={busy || (mode === "raw" ? !sql.trim() : equipmentMissing)}
              >
                Test query
              </button>
              <Link className="secondary-btn" to="/wiresheet">
                FDD Wiresheet
              </Link>
            </div>
          </div>

          <p className="muted sql-fdd-mode-hint">
            {mode === "builder"
              ? "Visual builder generates DataFusion SQL from FDD inputs — no manual SQL editing in this mode (Grafana-style)."
              : "Raw SQL mode: write full SELECT against telemetry_pivot. Builder fields are hidden."}
          </p>

          {mode === "builder" ? (
            <>
              <div className="sql-vars-panel">
                <h3 className="panel-subtitle">Available variables</h3>
                <p className="muted">
                  Table <code>telemetry_pivot</code> columns from mapped FDD inputs. Filter with{" "}
                  <code>equipment_id = &apos;…&apos;</code>.
                </p>
                <div className="sql-var-chips">
                  {fddInputs.map((i) => (
                    <span key={i.id} className="chip" title={i.label}>
                      {i.id}
                    </span>
                  ))}
                </div>
              </div>
              <div className="builder-grid sql-fdd-builder-grid">
              <label>
                Rule name
                <input value={builder.name} onChange={(e) => setBuilder({ ...builder, name: e.target.value })} />
              </label>
              <label>
                FDD input
                <select value={builder.input} onChange={(e) => setBuilder({ ...builder, input: e.target.value })}>
                  {fddInputs.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Operator
                <select value={builder.operator} onChange={(e) => setBuilder({ ...builder, operator: e.target.value })}>
                  {[">", "<", ">=", "<="].map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Threshold
                <input
                  type="number"
                  value={builder.value}
                  onChange={(e) => setBuilder({ ...builder, value: Number(e.target.value) })}
                />
              </label>
              <label>
                Equipment (Haystack equip id)
                <input
                  value={builder.equipment_id}
                  onChange={(e) => setBuilder({ ...builder, equipment_id: e.target.value })}
                />
              </label>
              <label>
                Confirmation (sec)
                <input
                  type="number"
                  value={builder.confirmation_seconds}
                  onChange={(e) => setBuilder({ ...builder, confirmation_seconds: Number(e.target.value) })}
                />
              </label>
              <label>
                Fault code
                <input value={builder.fault_code} onChange={(e) => setBuilder({ ...builder, fault_code: e.target.value })} />
              </label>
            </div>
              <details className="generated-sql-details">
                <summary>Generated SQL (read-only)</summary>
                <pre className="sql-block">{sql || "—"}</pre>
              </details>
            </>
          ) : (
            <label className="sql-editor-label">
              DataFusion SQL
              <textarea
                className="sql-editor sql-editor--large"
                value={sql}
                onChange={(e) => {
                  setSql(e.target.value);
                  setRawCustom(true);
                }}
                spellCheck={false}
                placeholder="SELECT timestamp, equipment_id, oa_t, … FROM telemetry_pivot WHERE …"
              />
            </label>
          )}

          {equipmentMissing && mode === "builder" ? (
            <div className="warn-banner">Select Haystack equipment id before testing the query.</div>
          ) : null}

          {rawCustom && mode === "raw" ? (
            <div className="warn-banner">Editing raw SQL — switch to Visual builder to use the form again.</div>
          ) : null}

          <div className="sql-fdd-results">
            {validation ? <div className="status-banner">{validationSummary(validation)}</div> : null}
            {runResult ? <div className="status-banner">{runResultSummary(runResult)}</div> : null}
          </div>

          {runResult ? (
            <section className="panel sql-test-query-panel">
              <div className="panel-head-row">
                <h3 className="panel-title">FDD query results</h3>
                <div className="action-bar">
                  <button type="button" className="primary-btn" disabled={busy} onClick={() => void saveActivateAndDashboard()}>
                    Save rule → dashboard
                  </button>
                  <button type="button" className="secondary-btn" disabled={busy} onClick={() => void exportPdfReport()}>
                    Export PDF report
                  </button>
                  <Link className="secondary-btn" to="/">
                    Main dashboard
                  </Link>
                  <Link className="secondary-btn" to="/exports">
                    Reports tab
                  </Link>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => {
                      void copyToClipboard(JSON.stringify(runResult, null, 2)).then((ok) =>
                        setCopyStatus(ok ? "Copied JSON" : "Copy failed"),
                      );
                    }}
                  >
                    Copy JSON
                  </button>
                </div>
              </div>
              {actionStatus ? <p className="ok">{actionStatus}</p> : null}
              {copyStatus ? <p className="muted">{copyStatus}</p> : null}
              {confirmedRows.length ? (
                <div className="table-like sql-fdd-confirmed-table">
                  <div className="table-row table-head">
                    <span>Timestamp</span>
                    <span>Equipment</span>
                    <span>Confirmed</span>
                    <span>Minutes in fault</span>
                  </div>
                  {confirmedRows.slice(0, 12).map((row, i) => (
                    <div key={i} className="table-row">
                      <span>{String(row.timestamp ?? "")}</span>
                      <span>{String(row.equipment_id ?? builder.equipment_id)}</span>
                      <span>{String(row.confirmed_fault ?? true)}</span>
                      <span>{String(row.minutes_in_fault ?? row.minutes_in_raw_fault ?? "—")}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">No confirmed faults in this preview — adjust threshold or confirmation window.</p>
              )}
              <details className="advanced-json">
                <summary>Full JSON response</summary>
                <pre className="code-block sql-query-json">{JSON.stringify(runResult, null, 2)}</pre>
              </details>
            </section>
          ) : null}

          {(validation || runResult) && showAdvanced ? (
            <details className="advanced-json" open>
              <summary>Validation JSON</summary>
              {validation ? <pre className="code-block">{JSON.stringify(validation, null, 2)}</pre> : null}
            </details>
          ) : null}
          {(validation || runResult) && !showAdvanced ? (
            <button type="button" className="secondary-btn" onClick={() => setShowAdvanced(true)}>
              Show validation JSON
            </button>
          ) : null}
        </section>
      </div>
    </div>
  );
}
