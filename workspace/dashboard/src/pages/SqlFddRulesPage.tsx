import { useCallback, useEffect, useState } from "react";
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

const GRAPH_ID = "graph:live-fdd-validation";

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
  const [graphStatus, setGraphStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
    apiFetch<{ equipment?: { id?: string }[] }>(`/api/model/sites/${encodeURIComponent(siteId)}/equipment`)
      .then((res) => {
        const first = res.equipment?.[0]?.id;
        if (first) {
          setBuilder((b) => (b.equipment_id ? b : { ...b, equipment_id: first }));
        }
      })
      .catch(() => undefined);
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

  async function proposeAssignments() {
    setBusy(true);
    setGraphStatus("");
    setError("");
    try {
      const out = await apiFetch<{ review_status?: string; proposed?: unknown[] }>(
        "/api/fdd-wires/propose-assignments",
        {
          method: "POST",
          body: JSON.stringify({ site_id: siteId || undefined, equipment_type: "ahu" }),
        },
      );
      setGraphStatus(`Proposed ${out.proposed?.length ?? 0} draft bindings — ${out.review_status ?? "needs_review"}`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function validateGraph() {
    setBusy(true);
    setGraphStatus("");
    setError("");
    try {
      const out = await apiFetch<{ ok?: boolean; issues?: unknown[] }>(
        `/api/fdd-wires/graphs/${encodeURIComponent(GRAPH_ID)}/validate${siteId ? `?site_id=${encodeURIComponent(siteId)}` : ""}`,
        { method: "POST", body: JSON.stringify({}) },
      );
      setGraphStatus(out.ok ? "Validation graph checks passed" : `Graph issues: ${(out.issues ?? []).length}`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sql-fdd-page">
      <PageHeader
        title="SQL FDD Rules"
        subtitle="DataFusion SQL rules, the rule builder, and Haystack-to-rule wiring for the active site model."
      />

      {error ? <div className="error-banner">{error}</div> : null}

      <section className="panel">
        <div className="toolbar">
          <h2 className="panel-title">SQL Rule Builder</h2>
          <button type="button" className={mode === "builder" ? "primary-btn" : "secondary-btn"} onClick={() => setMode("builder")}>
            Builder
          </button>
          <button type="button" className={mode === "raw" ? "primary-btn" : "secondary-btn"} onClick={() => setMode("raw")}>
            Raw SQL
          </button>
          <button type="button" className="secondary-btn" onClick={() => void validateSql()} disabled={busy}>
            Validate SQL
          </button>
          <button type="button" className="primary-btn" onClick={() => void runSql()} disabled={busy || !sql.trim()}>
            Run (Ctrl/Cmd+Enter)
          </button>
        </div>

        {mode === "builder" ? (
          <div className="builder-grid">
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

        {rawCustom ? <div className="warn-banner">Raw SQL is custom — builder mode may not round-trip these edits.</div> : null}

        <label className="sql-editor-label">
          Generated / raw DataFusion SQL
          <textarea
            className="sql-editor"
            value={sql}
            onChange={(e) => {
              setSql(e.target.value);
              setRawCustom(true);
            }}
            rows={8}
          />
        </label>

        {validation ? (
          <pre className="code-block">{JSON.stringify(validation, null, 2)}</pre>
        ) : null}
        {runResult ? (
          <pre className="code-block">{JSON.stringify(runResult, null, 2)}</pre>
        ) : null}
      </section>

      <section className="panel">
        <div className="toolbar">
          <h2 className="panel-title">FDD Wires — rule mapping graph</h2>
          <button type="button" className="secondary-btn" onClick={() => void proposeAssignments()} disabled={busy}>
            Propose assignments
          </button>
          <button type="button" className="secondary-btn" onClick={() => void validateGraph()} disabled={busy}>
            Validate graph
          </button>
        </div>
        <p className="muted-copy">
          Graph <code>{GRAPH_ID}</code> maps BACnet/Haystack points to FDD inputs for the active site
          {siteId ? (
            <>
              {" "}
              (<code>{siteId}</code>)
            </>
          ) : null}
          . Configure drivers and the Haystack model per building — nothing is hard-coded to a test bench.
        </p>
        {graphStatus ? <div className="status-banner">{graphStatus}</div> : null}
      </section>

      <section className="panel">
        <h2 className="panel-title">DataFusion batch demo</h2>
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
        {demo?.engine ? <p className="muted-copy">{demo.engine}</p> : null}
      </section>
    </div>
  );
}
