import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";

type PredefinedQuery = {
  id: string;
  label: string;
  query: string;
};

type QueryCategory = "Plant" | "Airside" | "Relationships" | "DCV" | "Summary" | "General";

type QueryResult = {
  columns: string[];
  rows: Array<Record<string, string>>;
  error?: string;
};

type HealthSummary = {
  score: number;
  counts: {
    sites: number;
    equipment: number;
    points: number;
    orphan_equipment: number;
    orphan_points_site: number;
    orphan_points_equipment: number;
    missing_brick_type: number;
    missing_fdd_input: number;
    duplicate_external_ids: number;
  };
  summary: string;
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
  const [health, setHealth] = useState<HealthSummary | null>(null);

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

  async function runHealthCheck() {
    try {
      setStatus("Running compact data model health check...");
      const out = await desktopFetch<HealthSummary>("/data-model/testing/health-summary");
      setHealth(out);
      setStatus("Health check complete.");
    } catch (e) {
      setStatus(`Health check failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  function categoryForQuery(id: string): QueryCategory {
    if (
      [
        "plant_equipment_counts",
        "water_cooled_chiller_plant_counts",
        "chiller_leaving_temp",
      ].includes(id)
    ) {
      return "Plant";
    }
    if (["ahu_count", "vav_count", "ahu_vav_system_counts", "ahu_setpoints", "heat_pump_vrf_counts"].includes(id)) {
      return "Airside";
    }
    if (id === "feeds_relationships") {
      return "Relationships";
    }
    if (["dcv_co2_summary", "economizer_free_cooling_summary"].includes(id)) {
      return "DCV";
    }
    if (["class_summary", "mechanical_system_summary"].includes(id)) {
      return "Summary";
    }
    return "General";
  }

  const grouped = predefined.reduce<Record<QueryCategory, PredefinedQuery[]>>(
    (acc, q) => {
      const category = categoryForQuery(q.id);
      acc[category].push(q);
      return acc;
    },
    { Plant: [], Airside: [], Relationships: [], DCV: [], Summary: [], General: [] },
  );

  return (
    <div className="card">
      <h2 className="title">Data Model Testing (SPARQL)</h2>
      <div style={{ marginBottom: 10 }}>
        <button className="secondary-btn" onClick={() => void runHealthCheck()}>
          Run Data Model Health (compact)
        </button>
      </div>
      {health ? (
        <div
          style={{
            marginBottom: 10,
            border: "1px solid var(--border)",
            borderRadius: 10,
            padding: 10,
            background: "var(--panel-soft)",
          }}
        >
          <strong>Health Score: {health.score}</strong>
          <div style={{ marginTop: 6 }}>
            Sites={health.counts.sites}, Equipment={health.counts.equipment}, Points={health.counts.points}
          </div>
          <div style={{ marginTop: 4 }}>
            Orphans: equipment={health.counts.orphan_equipment}, points(site)={health.counts.orphan_points_site},
            points(equipment)={health.counts.orphan_points_equipment}
          </div>
          <div style={{ marginTop: 4 }}>
            Missing mappings: brick_type={health.counts.missing_brick_type}, fdd_input={health.counts.missing_fdd_input},
            duplicate external_id groups={health.counts.duplicate_external_ids}
          </div>
          <div style={{ marginTop: 6 }}>{health.summary}</div>
        </div>
      ) : null}
      <div style={{ marginBottom: 8 }}>
        {(Object.keys(grouped) as QueryCategory[]).map((category) => (
          grouped[category].length > 0 ? (
            <div key={category} style={{ marginBottom: 10 }}>
              <strong style={{ display: "block", marginBottom: 6 }}>{category}</strong>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {grouped[category].map((q) => (
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
            </div>
          ) : null
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
              <tr key={`${output.columns.map((c) => row[c] ?? "").join("|")}::${idx}`}>
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
