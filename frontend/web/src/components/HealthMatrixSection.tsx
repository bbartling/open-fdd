import { useEffect, useMemo, useState } from "react";
import { Button, DataTable, Expander, InlineAlert, Metric, Select } from "./widgets";
import type { AnalyticsEnvelope } from "../api/analyticsApi";
import { downloadRowsCsv } from "../api/csvDownload";
import { naturalCompare } from "../lib/naturalSort";

export type HealthScore = "3/3" | "2/3" | "1/3" | "0/3" | "?/3" | "all";

export function tri(v: unknown): string {
  if (v === true) return "true";
  if (v === false) return "false";
  return "unknown";
}

export function healthRowClass(score: unknown): string | undefined {
  switch (String(score ?? "")) {
    case "1/3":
      return "health-row--broken-1";
    case "2/3":
      return "health-row--broken-2";
    case "3/3":
      return "health-row--broken-3";
    default:
      return undefined;
  }
}

export interface HealthFlagColumn {
  key: string;
  header: string;
}

export interface HealthMatrixSectionProps {
  family: string;
  title: string;
  caption: string;
  buildingId: string;
  refreshToken: number;
  fetchHealth: (buildingId: string) => Promise<AnalyticsEnvelope>;
  flagColumns: HealthFlagColumn[];
  extraFilterKey?: string;
  extraFilterLabel?: string;
  schemaFallback: string;
  queryFallback: string;
  csvName: string;
}

export function HealthMatrixSection({
  family,
  title,
  caption,
  buildingId,
  refreshToken,
  fetchHealth,
  flagColumns,
  extraFilterKey,
  extraFilterLabel,
  schemaFallback,
  queryFallback,
  csvName,
}: HealthMatrixSectionProps) {
  const [env, setEnv] = useState<AnalyticsEnvelope | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [score, setScore] = useState<HealthScore>("all");
  const [extra, setExtra] = useState("all");
  const [conf, setConf] = useState("all");
  const [metaOpen, setMetaOpen] = useState(false);

  const test = (suffix: string) => `${family}-health-${suffix}`;
  const sectionId = `overview-${family}-health`;

  useEffect(() => {
    if (!buildingId) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    void fetchHealth(buildingId)
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
  }, [buildingId, refreshToken, fetchHealth]);

  const rows = env?.rows ?? [];
  const extras = useMemo(() => {
    if (!extraFilterKey) return [] as string[];
    const s = new Set<string>();
    for (const r of rows) {
      const p = String(r[extraFilterKey] ?? "").trim();
      if (p) s.add(p);
    }
    return [...s].sort(naturalCompare);
  }, [rows, extraFilterKey]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (score !== "all" && String(r.score_label) !== score) return false;
      if (
        extraFilterKey &&
        extra !== "all" &&
        String(r[extraFilterKey] ?? "") !== extra
      ) {
        return false;
      }
      if (conf !== "all" && String(r.confidence ?? "") !== conf) return false;
      return true;
    });
  }, [rows, score, extra, conf, extraFilterKey]);

  const groups = (env?.coverage as { groups?: Record<string, number> } | null)
    ?.groups;

  const stale = !loading && !err && rows.length === 0;

  const tableRows = filtered.slice(0, 400).map((r) => {
    const out: Record<string, unknown> = {
      score_label: String(r.score_label ?? ""),
      equipment_id: String(r.equipment_id ?? ""),
      confidence: String(r.confidence ?? ""),
    };
    for (const col of flagColumns) {
      out[col.key] = tri(r[col.key]);
    }
    return out;
  });

  return (
    <section
      className={`overview-${family}-health`}
      data-testid={sectionId}
      aria-labelledby={`${sectionId}-heading`}
    >
      <h3 id={`${sectionId}-heading`}>{title}</h3>
      <p className="oracle-sidebar__caption">{caption}</p>
      {loading ? (
        <InlineAlert id={`${family}-health-loading`} variant="info" testId={test("loading")}>
          Loading {family.toUpperCase()} health…
        </InlineAlert>
      ) : null}
      {err ? (
        <InlineAlert id={`${family}-health-err`} variant="danger" testId={test("err")}>
          {err}
        </InlineAlert>
      ) : null}
      {stale ? (
        <InlineAlert id={`${family}-health-stale`} variant="warning" testId={test("stale")}>
          No {family.toUpperCase()} health rows. Use <strong>Update analytics</strong> /{" "}
          <strong>Run all rules</strong> — zeros are not fabricated. Missing evidence is
          unknown, not PASS.
        </InlineAlert>
      ) : null}
      <div className="overview-metrics" data-testid={test("cards")}>
        {(["3/3", "2/3", "1/3", "0/3", "?/3"] as const).map((g) => (
          <Metric
            key={g}
            id={`${family}-health-card-${g.replace("/", "-").replace("?", "q")}`}
            label={g === "?/3" ? "insufficient" : g}
            value={String(groups?.[g] ?? rows.filter((r) => r.score_label === g).length)}
            testId={`${family}-health-card-${g.replace("/", "-").replace("?", "q")}`}
          />
        ))}
      </div>
      <div className="overview-toolbar">
        <Select
          id={`${family}-health-score`}
          label="Score"
          value={score}
          onChange={(v) => setScore(v as HealthScore)}
          options={["all", "3/3", "2/3", "1/3", "0/3", "?/3"].map((x) => ({
            value: x,
            label: x,
          }))}
          testId={test("filter-score")}
        />
        {extraFilterKey && extraFilterLabel ? (
          <Select
            id={`${family}-health-extra`}
            label={extraFilterLabel}
            value={extra}
            onChange={setExtra}
            options={[
              { value: "all", label: "all" },
              ...extras.map((a) => ({ value: a, label: a })),
            ]}
            testId={test("filter-extra")}
          />
        ) : null}
        <Select
          id={`${family}-health-conf`}
          label="Confidence"
          value={conf}
          onChange={setConf}
          options={["all", "high", "medium", "low", "insufficient"].map((x) => ({
            value: x,
            label: x,
          }))}
          testId={test("filter-confidence")}
        />
        <Button
          id={`${family}-health-csv`}
          label="Download CSV"
          onClick={() =>
            downloadRowsCsv(csvName, rows as Array<Record<string, unknown>>)
          }
          testId={test("download")}
        />
      </div>
      {filtered.length ? (
        <DataTable
          id={`${family}-health-table`}
          label={`${family.toUpperCase()} health matrix`}
          columns={[
            { key: "score_label", header: "Score" },
            { key: "equipment_id", header: "Equipment" },
            ...flagColumns.map((c) => ({ key: c.key, header: c.header })),
            { key: "confidence", header: "Confidence" },
          ]}
          rows={tableRows}
          rowClassName={(row) => healthRowClass(row.score_label)}
          testId={test("table")}
        />
      ) : null}
      <Expander
        id={`${family}-health-meta`}
        label="Thresholds, engine, schema"
        expanded={metaOpen}
        onChange={setMetaOpen}
        testId={test("expander")}
      >
        <p className="oracle-sidebar__caption">
          engine={env?.engine ?? "—"} schema={String(
            (env?.coverage as { schema_version?: string } | null)?.schema_version ??
              schemaFallback,
          )}{" "}
          query={env?.query_version ?? queryFallback}
        </p>
        <p className="oracle-sidebar__caption" role="note">
          Red tint is flags true / 3. <code>?/3</code> is unknown (no red). Empty
          charts or empty matrices mean missing roles or no FDD run — not a broken
          engine.
        </p>
      </Expander>
    </section>
  );
}
