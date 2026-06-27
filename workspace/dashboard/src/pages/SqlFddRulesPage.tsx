import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../lib/api";
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
type FddFault = {
  equip: string;
  fault_code: string;
  severity: string;
  sample_count: number;
  max_abs_error: number;
};

type DemoResult = {
  engine?: string;
  sql?: string;
  faults?: FddFault[];
};

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
  const rows = payload.rows;
  if (Array.isArray(rows)) {
    return `Preview returned ${rows.length} row(s).`;
  }
  const count = payload.row_count ?? payload.count;
  if (typeof count === "number") return `Preview returned ${count} row(s).`;
  if (payload.ok === true) return "SQL preview completed.";
  return "Preview finished.";
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
  const [mode, setMode] = useState<"builder" | "raw">("builder");
  const [builder, setBuilder] = useState<BuilderState>(DEFAULT_BUILDER);
  const [sql, setSql] = useState("");
  const [rawCustom, setRawCustom] = useState(false);
  const [fddInputs, setFddInputs] = useState<FddInput[]>([]);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [demo, setDemo] = useState<DemoResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState("");
  const equipmentMissing = mode === "builder" && !builder.equipment_id.trim();

  useEffect(() => {
    Promise.all([
      apiFetch<{ fdd_inputs?: FddInput[] }>("/api/fdd-schema/fdd-inputs"),
      apiFetch<DemoResult>("/api/fdd/datafusion/demo"),
    ])
      .then(([inputs, demoRes]) => {
        setFddInputs(inputs.fdd_inputs ?? []);
        setDemo(demoRes);
      })
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
            <div className="action-bar">
              <button type="button" className={mode === "builder" ? "primary-btn" : "secondary-btn"} onClick={() => setMode("builder")}>
                Builder
              </button>
              <button type="button" className={mode === "raw" ? "primary-btn" : "secondary-btn"} onClick={() => setMode("raw")}>
                Raw SQL
              </button>
              <button type="button" className="secondary-btn" onClick={() => void validateSql()} disabled={busy}>
                Validate
              </button>
              <button type="button" className="primary-btn" onClick={() => void runSql()} disabled={busy || !sql.trim() || equipmentMissing}>
                Run preview
              </button>
              <Link className="secondary-btn" to="/wiresheet">
                Open FDD Wiresheet
              </Link>
            </div>
          </div>

          {equipmentMissing ? <div className="warn-banner">Select Haystack equipment id before running preview.</div> : null}

          {mode === "builder" ? (
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
          ) : null}

          {rawCustom ? <div className="warn-banner">Raw SQL edited manually — builder may not round-trip.</div> : null}

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
            />
          </label>

          <div className="sql-fdd-results">
            {validation ? <div className="status-banner">{validationSummary(validation)}</div> : null}
            {runResult ? <div className="status-banner">{runResultSummary(runResult)}</div> : null}
          </div>
          {(validation || runResult) && showAdvanced ? (
            <details className="advanced-json" open>
              <summary>Raw JSON</summary>
              {validation ? <pre className="code-block">{JSON.stringify(validation, null, 2)}</pre> : null}
              {runResult ? <pre className="code-block">{JSON.stringify(runResult, null, 2)}</pre> : null}
            </details>
          ) : null}
          {(validation || runResult) && !showAdvanced ? (
            <button type="button" className="secondary-btn" onClick={() => setShowAdvanced(true)}>
              Show raw JSON
            </button>
          ) : null}
        </section>
      </div>

      <details className="panel demo-panel-collapsible">
        <summary>DataFusion batch demo (sample data only)</summary>
        {demo?.sql ? <pre className="sql-block">{demo.sql}</pre> : null}
        <div className="table-like">
          {(demo?.faults ?? []).map((f) => (
            <div key={`${f.equip}-${f.fault_code}`} className={`table-row severity-${f.severity}`}>
              <span>{f.equip}</span>
              <strong>{f.fault_code}</strong>
              <span>samples {f.sample_count}</span>
              <span>max error {f.max_abs_error}</span>
            </div>
          ))}
        </div>
        {demo?.engine ? <p className="muted">{demo.engine}</p> : null}
      </details>
    </div>
  );
}
