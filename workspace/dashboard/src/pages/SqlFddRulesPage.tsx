import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import SqlFddQueryEditor from "../components/sqlFdd/SqlFddQueryEditor";
import SqlFddResultsPanel from "../components/sqlFdd/SqlFddResultsPanel";
import SqlFddSchemaExplorer from "../components/sqlFdd/SqlFddSchemaExplorer";
import SqlFddVisualBuilder from "../components/sqlFdd/SqlFddVisualBuilder";
import {
  DEFAULT_BUILDER,
  type BuilderState,
  type EquipmentRow,
  type FddInput,
  type QueryMode,
  type SchemaTable,
  ruleIdFromBuilder,
} from "../components/sqlFdd/types";
import { apiFetch } from "../lib/api";
import { compileNaturalLanguagePrompt, expandTimeMacros } from "../lib/fddSqlCompiler";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";

export default function SqlFddRulesPage() {
  const siteId = useActiveSiteId();
  const navigate = useNavigate();
  const [mode, setMode] = useState<QueryMode>("visual");
  const [builder, setBuilder] = useState<BuilderState>(DEFAULT_BUILDER);
  const [sql, setSql] = useState("");
  const [sqlLocked, setSqlLocked] = useState(true);
  const [prompt, setPrompt] = useState("Show OA temperature above 110 as an FDD fault");
  const [compileResult, setCompileResult] = useState<ReturnType<typeof compileNaturalLanguagePrompt> | null>(null);
  const [fddInputs, setFddInputs] = useState<FddInput[]>([]);
  const [schemaTables, setSchemaTables] = useState<SchemaTable[]>([]);
  const [equipment, setEquipment] = useState<EquipmentRow[]>([]);
  const [historian, setHistorian] = useState<Record<string, unknown> | null>(null);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionStatus, setActionStatus] = useState("");
  const [error, setError] = useState("");

  const ruleId = useMemo(() => ruleIdFromBuilder(builder), [builder]);
  const equipmentMissing = !builder.equipment_id.trim();

  useEffect(() => {
    Promise.all([
      apiFetch<{ fdd_inputs?: FddInput[] }>("/api/fdd-schema/fdd-inputs"),
      apiFetch<{ tables?: SchemaTable[] }>("/api/fdd-schema/tables"),
      apiFetch<Record<string, unknown>>("/api/dashboard/historian-health"),
    ])
      .then(([inputs, schema, hist]) => {
        setFddInputs(inputs.fdd_inputs ?? []);
        setSchemaTables(schema.tables ?? []);
        setHistorian(hist);
      })
      .catch((e) => setError(formatApiError(e)));
  }, []);

  useEffect(() => {
    if (!siteId) return;
    apiFetch<{ equipment?: EquipmentRow[] }>(`/api/model/sites/${encodeURIComponent(siteId)}/equipment`)
      .then((res) => {
        setEquipment(res.equipment ?? []);
        const first = res.equipment?.[0]?.id ?? res.equipment?.[0]?.equipment_id;
        if (first) setBuilder((b) => (b.equipment_id ? b : { ...b, equipment_id: first }));
      })
      .catch(() => setError("Could not load equipment for this site."));
  }, [siteId]);

  const previewBuilder = useCallback(async () => {
    try {
      const out = await apiFetch<{ sql?: string; validation?: Record<string, unknown> }>(
        "/api/fdd-rules/builder-sql",
        { method: "POST", body: JSON.stringify(builder) },
      );
      if (mode === "visual" && sqlLocked) setSql(out.sql ?? "");
      setValidation(out.validation ?? null);
    } catch (e) {
      setError(formatApiError(e));
    }
  }, [builder, mode, sqlLocked]);

  useEffect(() => {
    if (mode === "visual") void previewBuilder();
  }, [mode, builder.input, builder.operator, builder.value, builder.equipment_id, previewBuilder]);

  const insertSnippet = useCallback((snippet: string) => {
    setSql((prev) => (prev ? `${prev}${prev.endsWith(" ") ? "" : " "}${snippet}` : snippet));
    if (mode === "visual") {
      setMode("sql");
      setSqlLocked(false);
    }
  }, [mode]);

  async function validateSql() {
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<Record<string, unknown>>(
        `/api/fdd-rules/${encodeURIComponent(ruleId)}/validate-sql`,
        { method: "POST", body: JSON.stringify({ sql }) },
      );
      setValidation(out);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function runSql() {
    if (equipmentMissing) {
      setError("Select equipment before running — queries must scope to a Haystack equip id.");
      return;
    }
    setBusy(true);
    setError("");
    setRunResult(null);
    try {
      const execSql = expandTimeMacros(sql);
      const out = await apiFetch<Record<string, unknown>>(
        `/api/fdd-rules/${encodeURIComponent(ruleId)}/test-sql`,
        {
          method: "POST",
          body: JSON.stringify({
            sql: execSql,
            confirmation_seconds: builder.confirmation_seconds,
            params: { equipment_id: builder.equipment_id },
          }),
        },
      );
      setRunResult(out);
      if (out.validation) setValidation(out.validation as Record<string, unknown>);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  function compilePrompt() {
    setError("");
    const out = compileNaturalLanguagePrompt({
      userPrompt: prompt,
      equipmentId: builder.equipment_id,
      schema: schemaTables,
      fddInputs,
    });
    setCompileResult(out);
    if (out.ok && out.sql) {
      setSql(out.sql);
      setSqlLocked(false);
      setMode("prompt");
      setValidation(out.validation ?? null);
    } else {
      setError(out.error ?? "Could not compile prompt");
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") void runSql();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function saveActivateAndDashboard() {
    setBusy(true);
    setError("");
    setActionStatus("");
    try {
      await apiFetch("/api/fdd-rules", {
        method: "POST",
        body: JSON.stringify({
          rule_id: ruleId,
          name: builder.name,
          sql: expandTimeMacros(sql),
          confirmation_seconds: builder.confirmation_seconds,
          review_status: "approved",
          severity: builder.severity,
          output_fault_code: builder.fault_code,
          equipment_id: builder.equipment_id,
          site_id: siteId,
        }),
      });
      await apiFetch(`/api/fdd-rules/${encodeURIComponent(ruleId)}/activate`, { method: "POST", body: "{}" });
      window.dispatchEvent(new CustomEvent("ofdd-dashboard-refresh"));
      setActionStatus(`Rule "${ruleId}" saved and activated.`);
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
    try {
      const out = await apiFetch<{ report_id?: string }>("/api/reports/from-fdd-sql-run", {
        method: "POST",
        body: JSON.stringify({
          rule_name: builder.name,
          sql,
          equipment_id: builder.equipment_id,
          fault_code: builder.fault_code,
          run_result: runResult,
        }),
      });
      setActionStatus(`PDF report ${out.report_id ?? ""} created — see Reports tab.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  const selectedEquip = equipment.find(
    (e) => (e.id ?? e.equipment_id) === builder.equipment_id,
  );

  return (
    <div className="page page-wide sql-fdd-page gf-query-page">
      <PageHeader
        title="SQL FDD Rules"
        subtitle={
          <>
            DataFusion read-only SQL against site <code>{siteId || "…"}</code>. Point bindings live on{" "}
            <Link to="/model">Model &amp; FDD assignments</Link>.
          </>
        }
      />

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="gf-context-bar">
        <label className="gf-context-bar__field">
          <span className="gf-field__label">Test against equipment</span>
          <select
            value={builder.equipment_id}
            onChange={(e) => setBuilder({ ...builder, equipment_id: e.target.value })}
          >
            <option value="">Select equipment…</option>
            {equipment.map((eq) => {
              const id = eq.id ?? eq.equipment_id ?? "";
              const label = eq.name ? `${eq.name} (${id})` : id;
              return (
                <option key={id} value={id}>
                  {label}
                </option>
              );
            })}
          </select>
        </label>
        <div className="gf-context-bar__meta">
          <span className="gf-pill">{selectedEquip?.equipment_type ? String(selectedEquip.equipment_type) : "equip"}</span>
          <span className="gf-pill gf-pill--muted">
            Historian: {String(historian?.row_count ?? 0).toLocaleString()} rows
          </span>
          {historian?.latest_sample_at ? (
            <span className="gf-pill gf-pill--muted">Latest: {String(historian.latest_sample_at)}</span>
          ) : null}
        </div>
      </div>

      <div className="gf-query-layout">
        <SqlFddSchemaExplorer tables={schemaTables} fddInputs={fddInputs} onInsert={insertSnippet} />

        <div className="gf-query-main">
          <div className="gf-query-toolbar">
            <div className="gf-query-toolbar__modes">
              {(["visual", "sql", "prompt"] as QueryMode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  className={`gf-mode-btn${mode === m ? " is-active" : ""}`}
                  onClick={() => setMode(m)}
                >
                  {m === "visual" ? "Visual rule" : m === "sql" ? "SQL editor" : "NL prompt"}
                </button>
              ))}
            </div>
            <div className="gf-query-toolbar__actions">
              {mode !== "visual" || !sqlLocked ? (
                <button type="button" className="secondary-btn" disabled={busy} onClick={() => void validateSql()}>
                  Validate
                </button>
              ) : (
                <button type="button" className="secondary-btn" onClick={() => setSqlLocked(false)}>
                  Edit SQL
                </button>
              )}
              <button
                type="button"
                className="primary-btn gf-run-btn"
                disabled={busy || !sql.trim() || equipmentMissing}
                onClick={() => void runSql()}
              >
                {busy ? "Running…" : "Run query"}
              </button>
            </div>
          </div>

          <div className="gf-editor-panel">
            <div className="gf-editor-panel__head">
              <span className="gf-section-title">Query</span>
              <span className="gf-pill gf-pill--dialect">DataFusion · telemetry_pivot</span>
              <span className="muted gf-editor-panel__hint">Ctrl+Enter to run · read-only SELECT only</span>
            </div>
            <SqlFddQueryEditor
              sql={sql}
              readOnly={mode === "visual" && sqlLocked}
              onChange={(next) => {
                setSql(next);
                setSqlLocked(false);
                if (mode === "visual") setMode("sql");
              }}
            />
          </div>

          {mode === "visual" ? (
            <SqlFddVisualBuilder builder={builder} fddInputs={fddInputs} onChange={setBuilder} />
          ) : null}

          {mode === "prompt" ? (
            <div className="gf-prompt-panel">
              <label className="gf-field">
                <span className="gf-field__label">Natural language request</span>
                <textarea
                  className="gf-prompt-input"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={3}
                  placeholder="Show supply air temperature above 75 for the selected AHU over the historian range"
                />
              </label>
              <button type="button" className="secondary-btn" disabled={busy} onClick={compilePrompt}>
                Compile to SQL
              </button>
              {compileResult?.ok ? (
                <pre className="gf-compile-json">{JSON.stringify(
                  {
                    sql: compileResult.sql,
                    explanation: compileResult.explanation,
                    dialect: compileResult.dialect,
                  },
                  null,
                  2,
                )}</pre>
              ) : null}
            </div>
          ) : null}

          <SqlFddResultsPanel
            validation={validation}
            runResult={runResult}
            compileResult={compileResult}
            equipmentId={builder.equipment_id}
            busy={busy}
            onSave={() => void saveActivateAndDashboard()}
            onExportPdf={() => void exportPdfReport()}
            actionStatus={actionStatus}
          />
        </div>
      </div>
    </div>
  );
}
