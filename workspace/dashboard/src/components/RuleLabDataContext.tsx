import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../lib/api";
import { copyToClipboard } from "../lib/clipboard";
import { formatApiError } from "../lib/formatApiError";

type ColumnRow = {
  name: string;
  label: string;
  kind: string;
  sql_ref: string;
  arrow_ref: string;
};

type DataContextResponse = {
  ok?: boolean;
  site_id?: string;
  data_source?: string;
  row_count?: number;
  sql_table?: string;
  columns?: ColumnRow[];
};

type Props = {
  backend: "arrow" | "datafusion_sql";
  siteId: string;
  onInsertSql?: (sqlRef: string, columnName: string) => void;
  onInsertArrow?: (arrowRef: string, columnName: string) => void;
};

function kindLabel(kind: string): string {
  if (kind === "temperature") return "°F";
  if (kind === "humidity") return "%RH";
  if (kind === "time") return "time";
  if (kind === "meta") return "meta";
  return "";
}

export default function RuleLabDataContext({ backend, siteId, onInsertSql, onInsertArrow }: Props) {
  const [ctx, setCtx] = useState<DataContextResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  const load = useCallback(async () => {
    if (!siteId) {
      setCtx(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await apiFetch<DataContextResponse>(
        `/api/timeseries/rule-lab-context?site_id=${encodeURIComponent(siteId)}&limit=200`,
      );
      setCtx(res);
    } catch (e) {
      setCtx(null);
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [siteId]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = ctx?.columns ?? [];
  const telemetryCols = useMemo(() => columns.filter((c) => c.kind !== "meta" && c.kind !== "time"), [columns]);
  const metaCols = useMemo(() => columns.filter((c) => c.kind === "meta" || c.kind === "time"), [columns]);

  async function copyText(text: string, key: string) {
    try {
      await copyToClipboard(text);
      setCopied(key);
      window.setTimeout(() => setCopied(""), 1500);
    } catch {
      setCopied("");
    }
  }

  return (
    <section className="rule-lab-data-context panel-soft">
      <div className="rule-lab-data-context-head">
        <div>
          <h4 className="rule-lab-data-context-title">Available data columns</h4>
          <p className="muted rule-lab-data-context-lead">
            {backend === "datafusion_sql" ? (
              <>
                SQL reads the registered table <code>{ctx?.sql_table || "telemetry"}</code> — use column names below
                in <code>SELECT</code> and <code>WHERE</code>. End with{" "}
                <code>… AS {`{fault_column}`}</code> (default <code>fault</code>).
              </>
            ) : (
              <>
                PyArrow rules receive <code>table</code> (Arrow) and <code>cfg</code> (parameters). Reference columns
                with <code>table[&quot;column&quot;]</code> and thresholds with <code>cfg[&quot;key&quot;]</code>.
              </>
            )}
          </p>
        </div>
        <button type="button" className="secondary-btn" disabled={loading || !siteId} onClick={() => void load()}>
          {loading ? "Loading…" : "Refresh columns"}
        </button>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {ctx ? (
        <p className="muted rule-lab-data-context-meta">
          Site <code>{ctx.site_id}</code> · {ctx.row_count ?? 0} sample row(s) · {ctx.data_source || "historian"}
        </p>
      ) : null}

      {!siteId ? (
        <p className="ui-empty-hint">Select a site to preview historian columns.</p>
      ) : columns.length ? (
        <>
          {metaCols.length ? (
            <div className="rule-lab-col-group">
              <div className="rule-lab-col-group-label">Index / metadata</div>
              <div className="rule-lab-col-chips">
                {metaCols.map((col) => (
                  <ColumnChip
                    key={col.name}
                    col={col}
                    backend={backend}
                    copied={copied}
                    onCopy={copyText}
                    onInsertSql={onInsertSql}
                    onInsertArrow={onInsertArrow}
                  />
                ))}
              </div>
            </div>
          ) : null}

          <div className="rule-lab-col-group">
            <div className="rule-lab-col-group-label">Telemetry (historian feather columns)</div>
            <div className="rule-lab-col-chips">
              {telemetryCols.map((col) => (
                <ColumnChip
                  key={col.name}
                  col={col}
                  backend={backend}
                  copied={copied}
                  onCopy={copyText}
                  onInsertSql={onInsertSql}
                  onInsertArrow={onInsertArrow}
                />
              ))}
            </div>
          </div>

          <details className="ui-advanced-fold rule-lab-col-table-fold">
            <summary>Column reference table</summary>
            <div className="rule-lab-col-table-wrap">
              <table className="data-table rule-lab-col-table">
                <thead>
                  <tr>
                    <th>Historian column</th>
                    <th>Label</th>
                    <th>SQL</th>
                    <th>PyArrow</th>
                  </tr>
                </thead>
                <tbody>
                  {columns.map((col) => (
                    <tr key={col.name}>
                      <td>
                        <code>{col.name}</code>
                      </td>
                      <td className="muted">
                        {col.label}
                        {kindLabel(col.kind) ? ` · ${kindLabel(col.kind)}` : ""}
                      </td>
                      <td>
                        <code>{col.sql_ref}</code>
                      </td>
                      <td>
                        <code>{col.arrow_ref}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>

          <p className="muted rule-lab-data-context-foot">
            {backend === "datafusion_sql" ? (
              <>
                Example:{" "}
                <code>
                  SELECT *, {telemetryCols[0]?.sql_ref || "zone_temp"} &gt; 75.0 AS fault FROM telemetry
                </code>
              </>
            ) : (
              <>
                Example: <code>pc.greater(table[&quot;zone_temp&quot;], cfg[&quot;max_zone_temp&quot;])</code> inside{" "}
                <code>apply_faults_arrow(table, cfg, context)</code>
              </>
            )}
          </p>
        </>
      ) : loading ? (
        <p className="muted">Loading column catalog…</p>
      ) : (
        <p className="ui-empty-hint">No historian columns yet — enable BACnet/Modbus polling, then refresh.</p>
      )}
    </section>
  );
}

function ColumnChip({
  col,
  backend,
  copied,
  onCopy,
  onInsertSql,
  onInsertArrow,
}: {
  col: ColumnRow;
  backend: "arrow" | "datafusion_sql";
  copied: string;
  onCopy: (text: string, key: string) => void;
  onInsertSql?: (sqlRef: string, columnName: string) => void;
  onInsertArrow?: (arrowRef: string, columnName: string) => void;
}) {
  const kind = kindLabel(col.kind);
  const insert =
    backend === "datafusion_sql"
      ? () => onInsertSql?.(col.sql_ref, col.name)
      : () => onInsertArrow?.(col.arrow_ref, col.name);

  return (
    <div className="rule-lab-col-chip">
      <button type="button" className="rule-lab-col-chip-main" onClick={insert} title="Insert into editor">
        <span className="rule-lab-col-chip-name">{col.label !== col.name ? col.label : col.name}</span>
        <code className="rule-lab-col-chip-code">{col.name}</code>
        {kind ? <span className="rule-lab-col-chip-kind">{kind}</span> : null}
      </button>
      <button
        type="button"
        className="rule-lab-col-chip-copy"
        title="Copy reference"
        onClick={() => void onCopy(backend === "datafusion_sql" ? col.sql_ref : col.arrow_ref, col.name)}
      >
        {copied === col.name ? "✓" : "⎘"}
      </button>
    </div>
  );
}
