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

type FddPresetMeta = {
  preset_id: string;
  title: string;
  description: string;
};

type FddPresetResult = FddPresetMeta & {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count?: number;
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
  const [fddPresets, setFddPresets] = useState<FddPresetMeta[]>([]);
  const [fddPresetId, setFddPresetId] = useState("");
  const [fddRows, setFddRows] = useState<Record<string, unknown>[]>([]);
  const [fddColumns, setFddColumns] = useState<string[]>([]);
  const [fddDescription, setFddDescription] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiFetch<PredefinedResponse>("/api/model/sparql/predefined")
      .then((data) => {
        setCatalog(data);
        setSparqlQuery(data.default_query);
      })
      .catch((e) => setCatalogError(e instanceof Error ? e.message : String(e)));
    apiFetch<{ presets: FddPresetMeta[] }>("/api/model/fdd-query-presets")
      .then((data) => setFddPresets(data.presets ?? []))
      .catch(() => undefined);
  }, []);

  const relationshipQueries = useMemo(
    () => catalog?.queries.filter((q) => q.category === "relationships") ?? [],
    [catalog],
  );

  const hvacQueries = useMemo(
    () => catalog?.queries.filter((q) => (q.category ?? "hvac") === "hvac") ?? [],
    [catalog],
  );

  const dataSourcePreset = useMemo(
    () => fddPresets.find((p) => p.preset_id === "rules_by_data_source") ?? null,
    [fddPresets],
  );

  const coveragePresets = useMemo(
    () => fddPresets.filter((p) => p.preset_id !== "rules_by_data_source"),
    [fddPresets],
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
      setFddRows([]);
      setFddColumns([]);
      setFddDescription("");
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

  async function runFddPreset(presetId: string) {
    setRunning(true);
    setError("");
    setFddPresetId(presetId);
    setFddRows([]);
    setFddColumns([]);
    setBindings([]);
    setHasRun(false);
    try {
      const res = await apiFetch<FddPresetResult>(`/api/model/fdd-query-presets/${presetId}`);
      setFddRows(res.rows ?? []);
      setFddColumns(res.columns ?? []);
      setFddDescription(res.description ?? "");
      onStatus?.(`FDD preset ${res.title}: ${res.row_count ?? res.rows?.length ?? 0} row(s).`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onStatus?.(`FDD preset failed: ${msg}`);
    } finally {
      setRunning(false);
    }
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
        <h3>Rules by data source</h3>
        <p className="muted">
          Source-agnostic FDD rules with bound points grouped by BACnet vs Niagara driver. Rule names stay generic —
          data source appears only here for commissioning coverage.
        </p>
        <div className="dm-sparql-buttons">
          {dataSourcePreset ? (
            <button
              type="button"
              title={dataSourcePreset.description}
              disabled={running}
              onClick={() => void runFddPreset(dataSourcePreset.preset_id)}
            >
              {dataSourcePreset.title}
            </button>
          ) : null}
        </div>
      </section>

      <section className="dm-sparql-presets">
        <h3>FDD / BRICK query presets</h3>
        <p className="muted">
          Composed coverage queries across rules, equipment, sensors, and BACnet bindings (no parallel model store).
        </p>
        <div className="dm-sparql-buttons">
          {coveragePresets.map((item) => (
            <button
              key={item.preset_id}
              type="button"
              className="secondary-btn"
              title={item.description}
              disabled={running}
              onClick={() => void runFddPreset(item.preset_id)}
            >
              {item.title}
            </button>
          ))}
        </div>
        {fddDescription ? <p className="muted">{fddDescription}</p> : null}
        {fddRows.length > 0 && fddColumns.length > 0 ? (
          <div className="dm-points-table-wrap">
            <table className="dm-points-table dm-sparql-table">
              <thead>
                <tr>
                  {fddColumns.map((key) => (
                    <th key={key}>{key}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fddRows.map((row, i) => (
                  <tr key={`${fddPresetId}-${i}`} className="dm-points-row">
                    {fddColumns.map((key) => (
                      <td key={key} className="dm-brick-cell">
                        {row[key] == null || row[key] === "" ? "—" : String(row[key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="dm-sparql-presets">
        <h3>Summarize HVAC (SPARQL)</h3>
        <p className="muted">Predefined BRICK counts and equipment lists. Results appear in the custom section below.</p>
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
