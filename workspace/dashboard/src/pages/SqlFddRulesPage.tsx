import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import RuleRegistryPanel from "../components/sqlFdd/RuleRegistryPanel";
import SqlFddQueryEditor from "../components/sqlFdd/SqlFddQueryEditor";
import SqlFddResultsPanel from "../components/sqlFdd/SqlFddResultsPanel";
import {
  DEFAULT_BUILDER,
  type BuilderState,
  type EquipmentRow,
  type SchemaTable,
  ruleIdFromBuilder,
} from "../components/sqlFdd/types";
import { apiFetch } from "../lib/api";
import { DEFAULT_TELEMETRY_PIVOT_SQL, formatSql, setSqlEquipmentId } from "../lib/formatSql";
import { expandTimeMacros } from "../lib/fddSqlCompiler";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";

const HISTORIAN_TABLES = ["telemetry_pivot", "telemetry"] as const;

export default function SqlFddRulesPage() {
  const siteId = useActiveSiteId();
  const navigate = useNavigate();
  const [builder, setBuilder] = useState<BuilderState>(DEFAULT_BUILDER);
  const [canonicalRuleId, setCanonicalRuleId] = useState<string | null>(null);
  const [table, setTable] = useState<(typeof HISTORIAN_TABLES)[number]>("telemetry_pivot");
  const [sql, setSql] = useState(DEFAULT_TELEMETRY_PIVOT_SQL);
  const [schemaTables, setSchemaTables] = useState<SchemaTable[]>([]);
  const [equipment, setEquipment] = useState<EquipmentRow[]>([]);
  const [historian, setHistorian] = useState<Record<string, unknown> | null>(null);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const [runResult, setRunResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionStatus, setActionStatus] = useState("");
  const [error, setError] = useState("");

  const derivedRuleId = useMemo(() => ruleIdFromBuilder(builder), [builder]);
  const ruleId = canonicalRuleId ?? derivedRuleId;
  const equipmentMissing = !builder.equipment_id.trim();

  useEffect(() => {
    Promise.all([
      apiFetch<{ tables?: SchemaTable[] }>("/api/fdd-schema/tables"),
      apiFetch<Record<string, unknown>>("/api/dashboard/historian-health"),
    ])
      .then(([schema, hist]) => {
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
        if (first) {
          setBuilder((b) => (b.equipment_id ? b : { ...b, equipment_id: first }));
          setSql((prev) => setSqlEquipmentId(prev, first));
        }
      })
      .catch(() => setError("Could not load equipment for this site."));
  }, [siteId]);

  const onTableChange = useCallback(
    (next: (typeof HISTORIAN_TABLES)[number]) => {
      setTable(next);
      setSql((prev) => prev.replace(/\bFROM\s+\w+/i, `FROM ${next}`));
    },
    [],
  );

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

  const selectedTable = schemaTables.find((t) => t.name === table);
  const columnHint = selectedTable
    ? (selectedTable.columns ?? [])
        .map((c) => (typeof c === "string" ? c : c.name))
        .slice(0, 8)
        .join(", ")
    : "";

  return (
    <div className="page page-wide sql-fdd-page gf-query-page">
      <PageHeader
        title="SQL FDD Rules"
        subtitle={
          <>
            Read-only DataFusion SQL over the historian pivot. Point bindings live on{" "}
            <Link to="/model">Model &amp; FDD assignments</Link>.
          </>
        }
      />

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="gf-context-bar">
        <label className="gf-context-bar__field">
          <span className="gf-field__label">Historian table</span>
          <select value={table} onChange={(e) => onTableChange(e.target.value as typeof table)}>
            {HISTORIAN_TABLES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="gf-context-bar__field">
          <span className="gf-field__label">Equipment scope</span>
          <select
            value={builder.equipment_id}
            onChange={(e) => {
              const id = e.target.value;
              setBuilder({ ...builder, equipment_id: id });
              setSql((prev) => setSqlEquipmentId(prev, id));
            }}
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
          <span className="gf-pill gf-pill--muted">
            {Number(historian?.row_count ?? 0).toLocaleString()} rows
          </span>
          {columnHint ? (
            <span className="gf-pill gf-pill--muted" title={(selectedTable?.columns ?? []).map((c) => (typeof c === "string" ? c : c.name)).join(", ")}>
              {columnHint}
              {(selectedTable?.columns?.length ?? 0) > 8 ? "…" : ""}
            </span>
          ) : null}
        </div>
      </div>

      <div className="sql-fdd-layout">
        <RuleRegistryPanel
          selectedRuleId={ruleId}
          onSelectRuleId={(id) => {
            setCanonicalRuleId(id);
            setBuilder((b) => ({ ...b, name: id, fault_code: id }));
          }}
        />

      <div className="gf-query-main">
        <div className="gf-query-toolbar">
          <div className="gf-query-toolbar__actions">
            <button type="button" className="secondary-btn" onClick={() => setSql(formatSql(sql))}>
              Format SQL
            </button>
            <button type="button" className="secondary-btn" disabled={busy} onClick={() => void validateSql()}>
              Validate
            </button>
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
            <span className="gf-section-title">SQL</span>
            <span className="muted gf-editor-panel__hint">Ctrl+Enter to run · SELECT only</span>
          </div>
          <SqlFddQueryEditor sql={sql} onChange={setSql} />
        </div>

        <SqlFddResultsPanel
          validation={validation}
          runResult={runResult}
          compileResult={null}
          equipmentId={builder.equipment_id}
          busy={busy}
          onSave={() => void saveActivateAndDashboard()}
          onExportPdf={() => setActionStatus("PDF export — use Reports tab after saving a rule.")}
          actionStatus={actionStatus}
        />
      </div>
      </div>
    </div>
  );
}
