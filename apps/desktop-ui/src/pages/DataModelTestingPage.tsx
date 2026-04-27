import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";

type PredefinedQuery = {
  id: string;
  label: string;
  query: string;
};

type QueryResult = {
  columns: string[];
  rows: Array<Record<string, string>>;
  error?: string;
};

const defaultQuery = `PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  OPTIONAL { ?site rdfs:label ?site_label . }
}`;

export function DataModelTestingPage() {
  const [predefined, setPredefined] = useState<PredefinedQuery[]>([]);
  const [queryText, setQueryText] = useState(defaultQuery);
  const [output, setOutput] = useState<QueryResult>({ columns: [], rows: [] });
  const [status, setStatus] = useState("Run SPARQL against your local desktop TTL graph.");

  useEffect(() => {
    desktopFetch<PredefinedQuery[]>("/data-model/testing/predefined")
      .then(setPredefined)
      .catch((e: Error) => setStatus(`Failed to load predefined queries: ${e.message}`));
  }, []);

  async function runQuery(query: string) {
    try {
      setStatus("Running query...");
      const out = await desktopFetch<QueryResult>("/data-model/testing/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      setOutput(out);
      setStatus(`Returned ${out.rows.length} row(s).`);
    } catch (e) {
      setStatus(`Query failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return (
    <div className="card">
      <h2 className="title">Data Model Testing (SPARQL)</h2>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        {predefined.map((q) => (
          <button
            key={q.id}
            onClick={() => {
              setQueryText(q.query);
              void runQuery(q.query);
            }}
          >
            {q.label}
          </button>
        ))}
      </div>
      <textarea value={queryText} onChange={(e) => setQueryText(e.target.value)} style={{ minHeight: 180 }} />
      <div style={{ marginTop: 10, marginBottom: 10 }}>
        <button onClick={() => void runQuery(queryText)}>Run custom SPARQL</button>
      </div>
      <textarea readOnly value={status} style={{ minHeight: 60 }} />
      <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 10, overflow: "auto", maxHeight: 300 }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {output.columns.map((c) => (
                <th key={c} style={{ textAlign: "left", padding: 8, borderBottom: "1px solid var(--border)" }}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {output.rows.map((row, idx) => (
              <tr key={idx}>
                {output.columns.map((c) => (
                  <td key={`${idx}-${c}`} style={{ padding: 8, borderBottom: "1px solid var(--border)" }}>
                    {row[c] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
