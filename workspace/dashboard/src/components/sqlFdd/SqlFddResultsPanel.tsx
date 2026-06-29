import { useMemo, useState } from "react";
import { copyToClipboard } from "../../lib/clipboard";

type Props = {
  validation: Record<string, unknown> | null;
  runResult: Record<string, unknown> | null;
  compileResult: { sql?: string; explanation?: string; dialect?: string; error?: string } | null;
  equipmentId: string;
  busy?: boolean;
  onSave: () => void;
  onExportPdf: () => void;
  actionStatus?: string;
};

type Tab = "preview" | "faults" | "validation" | "json";

function asRows(payload: Record<string, unknown> | null): Record<string, unknown>[] {
  if (!payload?.rows || !Array.isArray(payload.rows)) return [];
  return payload.rows as Record<string, unknown>[];
}

function columnKeys(rows: Record<string, unknown>[]): string[] {
  const keys = new Set<string>();
  for (const row of rows.slice(0, 20)) {
    Object.keys(row).forEach((k) => keys.add(k));
  }
  return Array.from(keys);
}

export default function SqlFddResultsPanel({
  validation,
  runResult,
  compileResult,
  equipmentId,
  busy,
  onSave,
  onExportPdf,
  actionStatus,
}: Props) {
  const [tab, setTab] = useState<Tab>("preview");
  const [copyMsg, setCopyMsg] = useState("");
  const rows = useMemo(() => asRows(runResult), [runResult]);
  const cols = useMemo(() => columnKeys(rows), [rows]);
  const confirmation = (runResult?.confirmation ?? null) as Record<string, unknown> | null;
  const confirmed = (confirmation?.confirmed ?? []) as Record<string, unknown>[];

  if (!validation && !runResult && !compileResult) return null;

  const validationErrors = (validation?.errors as string[]) ?? [];
  const validationWarnings = (validation?.warnings as string[]) ?? [];

  return (
    <section className="gf-results">
      <div className="gf-results__head">
        <div className="gf-results__tabs" role="tablist">
          {(["preview", "faults", "validation", "json"] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={`gf-results__tab${tab === t ? " is-active" : ""}`}
              onClick={() => setTab(t)}
            >
              {t === "preview" ? "Preview" : t === "faults" ? "Fault summary" : t === "validation" ? "Validation" : "JSON"}
            </button>
          ))}
        </div>
        <div className="gf-results__actions">
          {runResult ? (
            <>
              <button type="button" className="primary-btn" disabled={busy} onClick={onSave}>
                Save & activate
              </button>
              <button type="button" className="secondary-btn" disabled={busy} onClick={onExportPdf}>
                Export PDF
              </button>
            </>
          ) : null}
          <button
            type="button"
            className="secondary-btn"
            onClick={() => {
              const payload = tab === "validation" ? validation : runResult ?? compileResult;
              void copyToClipboard(JSON.stringify(payload, null, 2)).then((ok) =>
                setCopyMsg(ok ? "Copied" : "Copy failed"),
              );
            }}
          >
            Copy JSON
          </button>
        </div>
      </div>

      {actionStatus ? <p className="ok gf-results__status">{actionStatus}</p> : null}
      {copyMsg ? <p className="muted">{copyMsg}</p> : null}

      {compileResult?.explanation && tab !== "json" ? (
        <p className="gf-results__explain muted">{compileResult.explanation}</p>
      ) : null}

      {tab === "preview" ? (
        rows.length ? (
          <div className="gf-data-grid-wrap">
            <table className="gf-data-grid">
              <thead>
                <tr>
                  {cols.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 100).map((row, i) => (
                  <tr key={i}>
                    {cols.map((c) => (
                      <td key={c}>{formatCell(row[c])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > 100 ? (
              <p className="muted gf-results__trunc">Showing first 100 of {rows.length} rows.</p>
            ) : null}
          </div>
        ) : (
          <p className="muted">Run the query to preview historian rows for {equipmentId || "selected equipment"}.</p>
        )
      ) : null}

      {tab === "faults" ? (
        <div className="gf-fault-summary">
          <dl className="gf-kv-grid">
            <div>
              <dt>Raw fault samples</dt>
              <dd>{String(confirmation?.raw_fault_count ?? "—")}</dd>
            </div>
            <div>
              <dt>Confirmed faults</dt>
              <dd>{String(confirmation?.confirmed_fault_count ?? "—")}</dd>
            </div>
            <div>
              <dt>Confirmation window</dt>
              <dd>{String(confirmation?.confirmation_seconds ?? "—")}s</dd>
            </div>
            <div>
              <dt>Engine</dt>
              <dd>{String(runResult?.engine ?? "DataFusion")}</dd>
            </div>
          </dl>
          {confirmed.length ? (
            <table className="gf-data-grid">
              <thead>
                <tr>
                  <th>Start</th>
                  <th>End</th>
                  <th>Duration (s)</th>
                  <th>Equipment</th>
                </tr>
              </thead>
              <tbody>
                {confirmed.map((c, i) => (
                  <tr key={i}>
                    <td>{formatTs(c.start)}</td>
                    <td>{formatTs(c.end)}</td>
                    <td>{String(c.duration_seconds ?? "—")}</td>
                    <td>{String(c.equipment_id ?? equipmentId)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No confirmed fault streaks in this window — adjust threshold or confirmation seconds.</p>
          )}
        </div>
      ) : null}

      {tab === "validation" ? (
        <div className="gf-validation">
          <div className={`gf-validation__banner${validation?.safe ? " is-ok" : validation ? " is-error" : ""}`}>
            {validation?.safe ? "SQL passed read-only guardrails" : validation ? "Validation issues found" : "No validation yet"}
          </div>
          {validationErrors.length ? (
            <ul className="gf-validation__list gf-validation__list--error">
              {validationErrors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          ) : null}
          {validationWarnings.length ? (
            <ul className="gf-validation__list gf-validation__list--warn">
              {validationWarnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          {validation?.allowed_tables ? (
            <p className="muted">
              Allowed tables:{" "}
              {Array.isArray(validation.allowed_tables)
                ? (validation.allowed_tables as string[]).join(", ")
                : String(validation.allowed_tables)}
            </p>
          ) : null}
        </div>
      ) : null}

      {tab === "json" ? (
        <pre className="gf-json-view">{JSON.stringify(runResult ?? validation ?? compileResult, null, 2)}</pre>
      ) : null}
    </section>
  );
}

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

function formatTs(v: unknown): string {
  if (typeof v === "number" && v > 0) {
    return new Date(v * 1000).toISOString();
  }
  return String(v ?? "—");
}
