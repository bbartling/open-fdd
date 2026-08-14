import { useEffect, useMemo, useState } from "react";
import { Button, DataTable, Expander, InlineAlert, Metric, Select } from "./widgets";
import { postVavHealth, type AnalyticsEnvelope } from "../api/analyticsApi";
import { downloadRowsCsv } from "../api/csvDownload";
import { naturalCompare } from "../lib/naturalSort";

type Score = "3/3" | "2/3" | "1/3" | "0/3" | "?/3" | "all";

function tri(v: unknown): string {
  if (v === true) return "true";
  if (v === false) return "false";
  return "unknown";
}

export function VavHealthSection({
  buildingId,
  refreshToken,
}: {
  buildingId: string;
  refreshToken: number;
}) {
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [score, setScore] = useState<Score>("all");
  const [ahu, setAhu] = useState("all");
  const [conf, setConf] = useState("all");
  const [metaOpen, setMetaOpen] = useState(false);

  useEffect(() => {
    if (!buildingId) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    void postVavHealth({ building_id: buildingId })
      .then((e) => {
        if (!cancelled) setEnv(e);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setEnv(null);
          setErr(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [buildingId, refreshToken]);

  const rows = env?.rows ?? [];
  const ahus = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) {
      const p = String(r.parent_ahu ?? "").trim();
      if (p) s.add(p);
    }
    return [...s].sort(naturalCompare);
  }, [rows]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (score !== "all" && String(r.score_label) !== score) return false;
      if (ahu !== "all" && String(r.parent_ahu ?? "") !== ahu) return false;
      if (conf !== "all" && String(r.confidence ?? "") !== conf) return false;
      return true;
    });
  }, [rows, score, ahu, conf]);

  const groups = (env?.coverage as { groups?: Record<string, number> } | null)
    ?.groups;

  const stale = !loading && !err && rows.length === 0;

  return (
    <section
      className="overview-vav-health"
      data-testid="overview-vav-health"
      aria-labelledby="overview-vav-health-heading"
    >
      <h3 id="overview-vav-health-heading">
        VAV health — broken boxes, comfort, and rogue zones.
      </h3>
      <p className="oracle-sidebar__caption">
        Three independent dimensions. Missing evidence is unknown, not PASS.
        One building-scoped request. Full-open prevalence is not an actuator
        fail flag.
      </p>
      {loading ? (
        <InlineAlert id="vav-health-loading" variant="info" testId="vav-health-loading">
          Loading VAV health…
        </InlineAlert>
      ) : null}
      {err ? (
        <InlineAlert id="vav-health-err" variant="danger" testId="vav-health-err">
          {err}
        </InlineAlert>
      ) : null}
      {stale ? (
        <InlineAlert id="vav-health-stale" variant="warning" testId="vav-health-stale">
          No VAV health rows. Use <strong>Update analytics</strong> /{" "}
          <strong>Run all rules</strong> — zeros are not fabricated.
        </InlineAlert>
      ) : null}
      <div className="overview-metrics" data-testid="vav-health-cards">
        {(["3/3", "2/3", "1/3", "0/3", "?/3"] as const).map((g) => (
          <Metric
            key={g}
            id={`vav-health-card-${g.replace("/", "-").replace("?", "q")}`}
            label={g === "?/3" ? "insufficient" : g}
            value={String(groups?.[g] ?? rows.filter((r) => r.score_label === g).length)}
            testId={`vav-health-card-${g.replace("/", "-").replace("?", "q")}`}
          />
        ))}
      </div>
      <div className="overview-toolbar">
        <Select
          id="vav-health-score"
          label="Score"
          value={score}
          onChange={(v) => setScore(v as Score)}
          options={["all", "3/3", "2/3", "1/3", "0/3", "?/3"].map((x) => ({
            value: x,
            label: x,
          }))}
          testId="vav-health-filter-score"
        />
        <Select
          id="vav-health-ahu"
          label="AHU"
          value={ahu}
          onChange={setAhu}
          options={[{ value: "all", label: "all" }, ...ahus.map((a) => ({ value: a, label: a }))]}
          testId="vav-health-filter-ahu"
        />
        <Select
          id="vav-health-conf"
          label="Confidence"
          value={conf}
          onChange={setConf}
          options={["all", "high", "medium", "low", "insufficient"].map((x) => ({
            value: x,
            label: x,
          }))}
          testId="vav-health-filter-confidence"
        />
        <Button
          id="vav-health-csv"
          label="Download CSV"
          onClick={() =>
            downloadRowsCsv(
              "vav_health_matrix.csv",
              rows as Array<Record<string, unknown>>,
            )
          }
          testId="vav-health-download"
        />
      </div>
      {filtered.length ? (
        <DataTable
          id="vav-health-table"
          label="VAV health matrix"
          columns={[
            { key: "score_label", header: "Score" },
            { key: "equipment_id", header: "Equipment" },
            { key: "broken_box", header: "Broken" },
            { key: "poor_zone_performance", header: "Comfort" },
            { key: "rogue_damper", header: "Rogue" },
            { key: "confidence", header: "Confidence" },
          ]}
          rows={filtered.slice(0, 400).map((r) => ({
            score_label: String(r.score_label ?? ""),
            equipment_id: String(r.equipment_id ?? ""),
            broken_box: tri(r.broken_box),
            poor_zone_performance: tri(r.poor_zone_performance),
            rogue_damper: tri(r.rogue_damper),
            confidence: String(r.confidence ?? ""),
          }))}
          testId="vav-health-table"
        />
      ) : null}
      <Expander
        id="vav-health-meta"
        label="Thresholds, engine, schema"
        expanded={metaOpen}
        onChange={setMetaOpen}
        testId="vav-health-expander"
      >
        <p className="oracle-sidebar__caption">
          engine={env?.engine ?? "—"} schema={String(
            (env?.coverage as { schema_version?: string } | null)?.schema_version ??
              "vav_health_matrix_v1",
          )}{" "}
          query={env?.query_version ?? "vav-health-v1"}
        </p>
        <p className="oracle-sidebar__caption" role="note">
          Drill via FDD Plots / RCx with <code>building_id</code> and{" "}
          <code>equipment_id</code> query params. Preset{" "}
          <code>vav_health_matrix</code> is additive; frozen RCx ids unchanged.
        </p>
      </Expander>
    </section>
  );
}
