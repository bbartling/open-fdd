import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";

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

type LineagePoint = {
  point_id: string;
  site_id: string;
  external_id: string;
  brick_type: string;
  fdd_input: string;
  feather_or_ref: string;
};

type LineageInput = {
  input_key: string;
  brick_tag: string | null;
  resolved_engine_column: string;
  model_points: LineagePoint[];
  match_count: number;
};

type LineageRule = {
  yaml: string;
  name?: string;
  type?: string;
  flag?: string;
  error?: string;
  inputs?: LineageInput[];
};

type LineagePayload = {
  rules_dir?: string;
  ttl_path?: string;
  column_map_size?: number;
  site_filter?: string | null;
  rules: LineageRule[];
  note?: string;
};

const defaultQuery = `PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?site ?site_label WHERE {
  ?site a brick:Site .
  OPTIONAL { ?site rdfs:label ?site_label . }
}`;

function parseLineagePayload(raw: Record<string, unknown>): LineagePayload {
  const rules = Array.isArray(raw.rules) ? (raw.rules as LineageRule[]) : [];
  return {
    rules_dir: typeof raw.rules_dir === "string" ? raw.rules_dir : undefined,
    ttl_path: typeof raw.ttl_path === "string" ? raw.ttl_path : undefined,
    column_map_size: typeof raw.column_map_size === "number" ? raw.column_map_size : undefined,
    site_filter: raw.site_filter === null || raw.site_filter === undefined
      ? null
      : String(raw.site_filter),
    note: typeof raw.note === "string" ? raw.note : undefined,
    rules,
  };
}

function fileTail(path: string, maxLen = 56): string {
  if (!path) return "";
  const norm = path.replace(/\\/g, "/");
  const seg = norm.split("/").filter(Boolean);
  const base = seg.length ? seg[seg.length - 1]! : norm;
  return base.length > maxLen ? `${base.slice(0, maxLen - 1)}…` : base;
}

function LineageTreeView({ data }: { data: LineagePayload }) {
  return (
    <div className="dm-lineage-tree">
      <div className="dm-lineage-meta">
        <div><strong>rules_dir</strong> {data.rules_dir ?? "—"}</div>
        <div><strong>ttl_path</strong> {data.ttl_path ?? "—"}</div>
        <div>
          <strong>column_map_size</strong> {data.column_map_size ?? "—"}
          {" · "}
          <strong>site_filter</strong> {data.site_filter || "(all sites)"}
        </div>
      </div>
      {data.rules.map((rule) => {
        const inputs = rule.inputs ?? [];
        const hasGap = inputs.some((i) => (i.match_count ?? 0) === 0);
        return (
          <details key={rule.yaml} className="dm-lineage-rule" open={hasGap}>
            <summary>
              <span className="dm-lineage-file">{rule.yaml}</span>
              {rule.error ? (
                <span style={{ color: "var(--danger)" }}>{rule.error}</span>
              ) : (
                <>
                  <span>{rule.name ?? "—"}</span>
                  <span className="dm-lineage-flag">{rule.flag ?? ""}</span>
                  {rule.type ? <span className="muted" style={{ fontSize: 11 }}>{rule.type}</span> : null}
                </>
              )}
            </summary>
            {!rule.error && inputs.map((inp) => (
              <details key={inp.input_key} className="dm-lineage-input" open={inp.match_count === 0}>
                <summary>
                  <span className="inline-code">{inp.input_key}</span>
                  {inp.brick_tag ? (
                    <span className="muted" style={{ marginLeft: 6, fontSize: 12 }}>BRICK: {inp.brick_tag}</span>
                  ) : null}
                  <span className="muted" style={{ marginLeft: 8 }}>→</span>
                  <span className="inline-code" style={{ marginLeft: 4 }}>{inp.resolved_engine_column}</span>
                  <span className={`dm-lineage-badge ${inp.match_count > 0 ? "ok" : "warn"}`}>
                    {inp.match_count} point{inp.match_count === 1 ? "" : "s"}
                  </span>
                </summary>
                {inp.model_points.length === 0 ? (
                  <div className="muted" style={{ margin: "6px 0 0 4px", fontSize: 12 }}>
                    No model point matched <code>external_id</code> or <code>fdd_input</code> for this input.
                  </div>
                ) : (
                  inp.model_points.map((pt, pi) => (
                    <div key={pt.point_id ? pt.point_id : `row-${pi}-${pt.external_id}`} className="dm-lineage-point">
                      <div><strong>Point</strong> <span className="inline-code">{pt.external_id}</span></div>
                      <div className="dm-lineage-point-row">
                        <span className="muted">id</span>{" "}
                        <span className="inline-code" style={{ fontSize: 11 }}>{pt.point_id}</span>
                      </div>
                      <div className="dm-lineage-point-row">
                        <span className="muted">brick_type</span>{" "}
                        <span>{pt.brick_type || "—"}</span>
                        <span className="muted">fdd_input</span>{" "}
                        <span>{pt.fdd_input || "—"}</span>
                      </div>
                      <div style={{ marginTop: 6 }}>
                        <span className="muted">Feather / ref</span>{" "}
                        <span title={pt.feather_or_ref}>{fileTail(pt.feather_or_ref, 72)}</span>
                      </div>
                    </div>
                  ))
                )}
              </details>
            ))}
          </details>
        );
      })}
      {data.note ? (
        <p className="muted" style={{ marginTop: 12, fontSize: 12, lineHeight: 1.5 }}>{data.note}</p>
      ) : null}
    </div>
  );
}

export function DataModelTestingPage() {
  const siteContext = useSite();
  /** `null` = all sites (not filtered). Never fall back to top-bar site in the select value (avoids overwriting explicit “All sites”). */
  const [lineageSiteId, setLineageSiteId] = useState<string | null>(() => siteContext.selectedSiteId ?? null);
  const [lineageData, setLineageData] = useState<LineagePayload | null>(null);
  const [lineageRawJson, setLineageRawJson] = useState("");
  const [predefined, setPredefined] = useState<PredefinedQuery[]>([]);
  const [queryText, setQueryText] = useState(defaultQuery);
  const [output, setOutput] = useState<QueryResult>({ columns: [], rows: [] });
  const [health, setHealth] = useState<HealthSummary | null>(null);
  const [healthPanelMessage, setHealthPanelMessage] = useState("Run the health check to score the JSON model and TTL sync readiness.");
  const [lineagePanelMessage, setLineagePanelMessage] = useState(
    "Build a rule → BRICK → Feather linkage map for the managed YAML pack and current TTL.",
  );
  const [sparqlPanelMessage, setSparqlPanelMessage] = useState("Run SPARQL against your local desktop TTL graph.");

  useEffect(() => {
    desktopFetch<PredefinedQuery[]>("/data-model/testing/predefined")
      .then(setPredefined)
      .catch((e: Error) => setSparqlPanelMessage(`Failed to load predefined queries: ${e.message}`));
  }, []);

  async function runQuery(query: string) {
    try {
      setSparqlPanelMessage("Running query...");
      const out = await desktopFetch<QueryResult>("/data-model/testing/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      setOutput(out);
      setSparqlPanelMessage(`Returned ${out.rows.length} row(s).`);
    } catch (e) {
      setSparqlPanelMessage(`Query failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function runHealthCheck() {
    try {
      setHealthPanelMessage("Running compact data model health check...");
      setHealth(null);
      const out = await desktopFetch<HealthSummary>("/data-model/testing/health-summary");
      setHealth(out);
      setHealthPanelMessage("Health check complete.");
    } catch (e) {
      setHealth(null);
      setHealthPanelMessage(`Health check failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function runRuleDataLineage() {
    try {
      setLineagePanelMessage("Building FDD rule ↔ BRICK ↔ Feather lineage report…");
      setLineageData(null);
      setLineageRawJson("");
      const q = lineageSiteId && lineageSiteId.trim()
        ? `?site_id=${encodeURIComponent(lineageSiteId.trim())}`
        : "";
      const raw = await desktopFetch<Record<string, unknown>>(`/data-model/testing/rule-data-lineage${q}`);
      const parsed = parseLineagePayload(raw);
      setLineageData(parsed);
      setLineageRawJson(JSON.stringify(raw, null, 2));
      const n = parsed.rules.length;
      const gaps = parsed.rules.reduce(
        (acc, r) => acc + (r.inputs?.filter((i) => i.match_count === 0).length ?? 0),
        0,
      );
      setLineagePanelMessage(
        `Loaded ${n} rule file(s); ${gaps} input row(s) with zero model matches (expand red “0 points” rows).`,
      );
    } catch (e) {
      setLineageData(null);
      setLineageRawJson("");
      setLineagePanelMessage(`Lineage report failed: ${e instanceof Error ? e.message : String(e)}`);
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

  const categoryOrder: QueryCategory[] = ["Plant", "Airside", "Relationships", "DCV", "Summary", "General"];

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Data Model Testing</h2>
        <p className="muted" style={{ marginBottom: 0 }}>
          SPARQL against the local TTL graph, compact health scoring, and FDD rule lineage (YAML → BRICK map → Feather-backed points).
        </p>
      </div>

      <div className="card">
        <h3 className="title" style={{ fontSize: "1.05rem", marginBottom: 8 }}>1. Data model health</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Sites, equipment, points, orphan links, missing BRICK / FDD fields, and duplicate external IDs.
        </p>
        <button type="button" onClick={() => void runHealthCheck()}>
          Run data model health (compact)
        </button>
        <div className={`dm-test-result-panel ${health ? "" : "dm-test-result-empty"}`}>
          {health ? (
            <div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--primary-strong)" }}>
                Score {health.score}
                <span className="muted" style={{ fontSize: 13, fontWeight: 500, marginLeft: 10 }}>/ 100</span>
              </div>
              <div style={{ marginTop: 10, display: "grid", gap: 6, fontSize: 14 }}>
                <div>
                  <strong>Inventory</strong>
                  {" — "}
                  sites {health.counts.sites}, equipment {health.counts.equipment}, points {health.counts.points}
                </div>
                <div>
                  <strong>Orphans</strong>
                  {" — "}
                  equipment {health.counts.orphan_equipment}, points (bad site) {health.counts.orphan_points_site},
                  {" "}points (bad equipment) {health.counts.orphan_points_equipment}
                </div>
                <div>
                  <strong>Mapping gaps</strong>
                  {" — "}
                  missing <code>brick_type</code> {health.counts.missing_brick_type},
                  {" "}missing <code>fdd_input</code> {health.counts.missing_fdd_input},
                  {" "}duplicate external_id groups {health.counts.duplicate_external_ids}
                </div>
              </div>
              <p style={{ marginTop: 12, marginBottom: 0, lineHeight: 1.5 }}>{health.summary}</p>
            </div>
          ) : (
            <span>{healthPanelMessage}</span>
          )}
        </div>
      </div>

      <div className="card">
        <h3 className="title" style={{ fontSize: "1.05rem", marginBottom: 8 }}>2. FDD rules ↔ BRICK ↔ Feather lineage</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Each YAML rule input is resolved to the engine column (TTL <code>ofdd:mapsToRuleInput</code> and BRICK labels),
          then matched to model points and <code>metadata.external_ref</code> (Feather path).
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginBottom: 10 }}>
          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            Site filter
            <select
              value={lineageSiteId === null ? "__ALL__" : lineageSiteId}
              onChange={(e) => {
                const v = e.target.value;
                setLineageSiteId(v === "__ALL__" ? null : v);
              }}
              style={{ width: "auto", minWidth: 220 }}
              aria-label="Site filter for lineage report"
            >
              <option value="__ALL__">All sites</option>
              {siteContext.sites.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => void runRuleDataLineage()}>
            Build lineage map
          </button>
        </div>
        <div className={`dm-test-result-panel ${lineageData ? "" : "dm-test-result-empty"}`} style={{ minHeight: lineageData ? 200 : 140 }}>
          {lineageData ? (
            <LineageTreeView data={lineageData} />
          ) : (
            <span>{lineagePanelMessage}</span>
          )}
        </div>
        <p className="muted" style={{ marginTop: 8, marginBottom: 0 }}>{lineagePanelMessage}</p>
        {lineageRawJson ? (
          <details style={{ marginTop: 12 }}>
            <summary className="muted" style={{ cursor: "pointer", fontSize: 13 }}>Raw JSON (export / debug)</summary>
            <textarea
              readOnly
              value={lineageRawJson}
              style={{ marginTop: 8, minHeight: 160, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}
            />
          </details>
        ) : null}
      </div>

      <div className="card dm-sparql-explorer">
        <h3 className="title" style={{ fontSize: "1.05rem", marginBottom: 8 }}>3. SPARQL explorer</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Preset queries by domain; results appear in the table at the bottom of this section.
        </p>
        <div className="dm-sparql-grid">
          {categoryOrder.map((category) => (
            grouped[category].length > 0 ? (
              <div key={category} className="dm-sparql-category">
                <span className="dm-sparql-cat-label">{category}</span>
                <div className="dm-sparql-buttons">
                  {grouped[category].map((q) => (
                    <button
                      key={q.id}
                      type="button"
                      className="secondary-btn"
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
        <label style={{ display: "block", marginTop: 14, marginBottom: 6 }}>Custom SPARQL</label>
        <textarea value={queryText} onChange={(e) => setQueryText(e.target.value)} style={{ minHeight: 160 }} />
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" onClick={() => void runQuery(queryText)}>Run custom SPARQL</button>
        </div>
        <textarea readOnly value={sparqlPanelMessage} style={{ marginTop: 10, minHeight: 52 }} />
        <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 10, overflow: "auto", maxHeight: 320 }}>
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
    </div>
  );
}
