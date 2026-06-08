import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../lib/api";

type PredefinedQuery = {
  id: string;
  label: string;
  short_label: string;
  category?: "hvac" | "relationships";
  query: string;
  query_with_bacnet?: string;
};

type PredefinedResponse = {
  default_query: string;
  queries: PredefinedQuery[];
};

type SparqlResponse = {
  bindings: Record<string, string>[];
  row_count?: number;
  truncated?: boolean;
};

type Props = {
  onStatus?: (message: string) => void;
};

export default function DataModelSparqlPanel({ onStatus }: Props) {
  const [catalog, setCatalog] = useState<PredefinedResponse | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [includeBacnetRefs, setIncludeBacnetRefs] = useState(false);
  const [sparqlQuery, setSparqlQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [bindings, setBindings] = useState<Record<string, string>[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [hasRun, setHasRun] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiFetch<PredefinedResponse>("/api/model/sparql/predefined")
      .then((data) => {
        setCatalog(data);
        setSparqlQuery(data.default_query);
      })
      .catch((e) => setCatalogError(e instanceof Error ? e.message : String(e)));
  }, []);

  const relationshipQueries = useMemo(
    () => catalog?.queries.filter((q) => q.category === "relationships") ?? [],
    [catalog],
  );

  const hvacQueries = useMemo(
    () => catalog?.queries.filter((q) => (q.category ?? "hvac") === "hvac") ?? [],
    [catalog],
  );

  const runQuery = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed) return;
      setSparqlQuery(trimmed);
      setRunning(true);
      setError("");
      setBindings([]);
      setTruncated(false);
      setHasRun(true);
      try {
        const res = await apiFetch<SparqlResponse>("/api/model/sparql", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: trimmed }),
        });
        setBindings(res.bindings ?? []);
        setTruncated(Boolean(res.truncated));
        const count = res.row_count ?? res.bindings?.length ?? 0;
        onStatus?.(`SPARQL returned ${count} row${count === 1 ? "" : "s"}${res.truncated ? " (truncated)" : ""}.`);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        onStatus?.(`SPARQL failed: ${msg}`);
      } finally {
        setRunning(false);
      }
    },
    [onStatus],
  );

  function runPredefined(item: PredefinedQuery) {
    const q = includeBacnetRefs && item.query_with_bacnet ? item.query_with_bacnet : item.query;
    void runQuery(q);
  }

  const columns =
    bindings.length > 0
      ? Array.from(new Set(bindings.flatMap((row) => Object.keys(row)))).sort()
      : [];

  return (
    <div className="dm-sparql panel">
      <p className="muted">
        Query the synced BRICK + BACnet graph (<code>data_model.ttl</code>). Read-only SELECT queries only.
      </p>

      {catalogError ? <p className="dm-sparql-error">{catalogError}</p> : null}

      <section className="dm-sparql-presets">
        <h3>BRICK relationships</h3>
        <p className="muted">
          Trace mechanical hierarchy — <strong>feeds</strong> (AHU → VAV) and <strong>fed by</strong> (child ←
          parent). Set <code>equipment[].feeds</code> in commissioning JSON, then sync TTL.
        </p>
        <div className="dm-sparql-buttons">
          {relationshipQueries.map((item) => (
            <button
              key={item.id}
              type="button"
              title={item.label}
              disabled={running}
              onClick={() => runPredefined(item)}
            >
              {item.short_label}
            </button>
          ))}
          {running ? <span className="dm-sparql-running">Running SPARQL…</span> : null}
        </div>
      </section>

      <section className="dm-sparql-presets">
        <h3>Summarize HVAC</h3>
        <p className="muted">Predefined counts and equipment lists. Results appear in the custom section below.</p>
        <label className="dm-sparql-bacnet-toggle">
          <input
            type="checkbox"
            checked={includeBacnetRefs}
            onChange={(e) => setIncludeBacnetRefs(e.target.checked)}
          />
          <span>Include BACnet device and point IDs (for telemetry and algorithms)</span>
        </label>
        <div className="dm-sparql-buttons">
          {hvacQueries.map((item) => (
            <button
              key={item.id}
              type="button"
              className="secondary-btn"
              title={item.label}
              disabled={running}
              onClick={() => runPredefined(item)}
            >
              {item.short_label}
            </button>
          ))}
        </div>
      </section>

      <section className="dm-sparql-custom">
        <h3>Custom SPARQL</h3>
        <p className="muted">Upload a <code>.sparql</code> file or type below, then Run.</p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".sparql,text/plain"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = () => {
              const text = typeof reader.result === "string" ? reader.result : "";
              setSparqlQuery(text);
            };
            reader.readAsText(file);
            e.target.value = "";
          }}
        />
        <div className="row">
          <button type="button" className="secondary-btn" onClick={() => fileInputRef.current?.click()}>
            Upload .sparql file
          </button>
          <button type="button" disabled={running || !sparqlQuery.trim()} onClick={() => void runQuery(sparqlQuery)}>
            {running ? "Running…" : "Run SPARQL"}
          </button>
        </div>
        <textarea
          className="dm-json-editor dm-sparql-editor"
          value={sparqlQuery}
          onChange={(e) => setSparqlQuery(e.target.value)}
          spellCheck={false}
          rows={12}
        />
        {error ? <p className="dm-sparql-error">{error}</p> : null}
        {!error && hasRun && !running && bindings.length === 0 ? (
          <p className="muted">No bindings (empty result).</p>
        ) : null}
        {bindings.length > 0 && columns.length > 0 ? (
          <>
            {truncated ? (
              <p className="muted">Results truncated to 5000 rows — narrow your query if needed.</p>
            ) : null}
            <div className="dm-points-table-wrap">
              <table className="dm-points-table dm-sparql-table">
                <thead>
                  <tr>
                    {columns.map((key) => (
                      <th key={key}>{key}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {bindings.map((row, i) => (
                    <tr key={i} className="dm-points-row">
                      {columns.map((key) => (
                        <td key={key} className="dm-brick-cell">
                          {row[key] || "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}
