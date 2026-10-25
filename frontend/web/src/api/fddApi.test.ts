import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  buildFddResultsPath,
  buildFddSeriesPath,
  buildFddRuleParamsPath,
  buildRuleParamPayload,
  clampRuleParam,
  FDD_PLOTS_BY_RULE_PATH,
  leanPlotDefaultPoints,
  listFddPlotsByRule,
  resultsToCsvArtifact,
  resultsToJsonArtifact,
  runFdd,
  getFddResults,
  listFddRules,
  getFddRuleParams,
} from "./fddApi";

describe("fddApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const u = String(url);
        if (u.includes("/api/fdd/rules") && u.includes("/params")) {
          return new Response(
            JSON.stringify({
              ok: true,
              rule_id: "FC1",
              params: {
                eps: {
                  key: "eps",
                  label: "Eps",
                  default: 0.1,
                  min: 0,
                  max: 1,
                  step: 0.1,
                  unit: "",
                  control: "slider",
                  sql_placeholder: "EPS",
                },
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (u.includes("/api/fdd/rules") && !u.includes("/params")) {
          return new Response(
            JSON.stringify({
              ok: true,
              count: 1,
              rules: [{ rule_id: "FC1", description: "Fan" }],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (u.includes("/api/fdd/run") && init?.method === "POST") {
          return new Response(
            JSON.stringify({
              ok: true,
              engine: "fdd_rules+DataFusion",
              rules_succeeded: 1,
              rules_failed: 0,
              rules_skipped: 0,
              results: [
                {
                  rule_id: "FC1",
                  equipment_id: "AHU_1",
                  status: "PASS",
                  fault_hours: 0,
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (u.includes("/api/fdd/results")) {
          return new Response(
            JSON.stringify({
              ok: true,
              count: 1,
              results: [
                {
                  rule_id: "FC1",
                  equipment_id: "AHU_1",
                  status: "FAULT",
                  fault_hours: 1.5,
                  missing_roles: [],
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (u.includes("/api/fdd/plots-by-rule")) {
          return new Response(
            JSON.stringify({
              ok: true,
              lean_budget: { default_points: 1200, max_roles: 6 },
              rules: [{ rule_id: "FC1", roles: ["fan_status"] }],
              soft_open_neq_fq: true,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response("{}", { status: 404 });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds results and series paths", () => {
    expect(buildFddResultsPath("B1")).toBe(
      "/api/fdd/results?building_id=B1",
    );
    expect(buildFddSeriesPath("AHU_1", "FC1")).toBe(
      "/api/fdd/plot?equipment_id=AHU_1&rule_id=FC1&max_points=1500",
    );
    expect(buildFddSeriesPath("AHU_1", "FC1", "B1")).toBe(
      "/api/fdd/plot?equipment_id=AHU_1&rule_id=FC1&building_id=B1&max_points=1500",
    );
  });

  it("Soft-OPEN lean plot catalog path and default points", async () => {
    expect(FDD_PLOTS_BY_RULE_PATH).toBe("/api/fdd/plots-by-rule");
    expect(leanPlotDefaultPoints(null)).toBe(1500);
    expect(leanPlotDefaultPoints({ default_points: 1200 })).toBe(1200);
    const cat = await listFddPlotsByRule();
    expect(cat.ok).toBe(true);
    expect(leanPlotDefaultPoints(cat.lean_budget)).toBe(1200);
  });

  it("lists rules and runs registry FDD", async () => {
    await expect(listFddRules()).resolves.toEqual([
      { rule_id: "FC1", description: "Fan" },
    ]);
    const out = await runFdd({ building_id: "B1", rule_ids: ["FC1"] });
    expect(out.ok).toBe(true);
    expect(out.rules_succeeded).toBe(1);
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls.find((c) =>
      String(c[0]).includes("/api/fdd/run"),
    )!;
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.mode).toBe("registry");
    expect(body.building_id).toBe("B1");
  });

  it("loads results and builds download artifacts", async () => {
    const rows = await getFddResults("B1");
    expect(rows[0].status).toBe("FAULT");
    const json = JSON.parse(resultsToJsonArtifact(rows, { building_id: "B1" }));
    expect(json.schema).toBe("openfdd_fdd_results_v1");
    expect(resultsToCsvArtifact(rows)).toMatch(/^rule_id,/);
    expect(resultsToCsvArtifact(rows)).toMatch(/FC1,AHU_1/);
    const metricCsv = resultsToCsvArtifact([
      {
        rule_id: "AVG-ZONE-TEMP",
        equipment_id: "AHU_1",
        status: "METRIC",
        output_kind: "metric",
        fault_hours: null,
        metric: {
          name: "avg_zone_temp",
          value: 72.4,
          unit: "degF",
          window: {
            start: "2026-06-01T00:00:00Z",
            end: "2026-06-01T01:00:00Z",
            observed_start: "2026-06-01T00:00:00Z",
            observed_end: "2026-06-01T01:00:00Z",
            watermark: "2026-06-01T01:00:00Z",
            unknown: false,
          },
          coverage: { sample_rows: 2 },
          provenance: { source: "timescale", config_fingerprint: "cfghash" },
        },
      },
    ]);
    expect(metricCsv.startsWith("rule_id,equipment_id")).toBe(true);
    expect(metricCsv).toContain("avg_zone_temp");
    expect(metricCsv).toContain("72.4");
    expect(metricCsv).toContain("degF");
    expect(metricCsv).toContain("metric_window_unknown");
    expect(metricCsv).toContain("false");
    expect(metricCsv).toContain("timescale");
    expect(metricCsv).toContain("cfghash");
    const unknownCsv = resultsToCsvArtifact([
      {
        rule_id: "AVG-ZONE-TEMP",
        equipment_id: "AHU_1",
        status: "METRIC",
        output_kind: "metric",
        metric: {
          name: "avg_zone_temp",
          value: 72.4,
          unit: "degF",
          window: { start: null, end: null, unknown: true },
          coverage: { sample_rows: 2 },
        },
      },
    ]);
    const unknownLine = unknownCsv.split("\n")[1] ?? "";
    const unknownCols = unknownLine.split(",");
    const headers = unknownCsv.split("\n")[0]?.split(",") ?? [];
    const unknownIdx = headers.indexOf("metric_window_unknown");
    expect(unknownIdx).toBeGreaterThan(0);
    expect(unknownCols[unknownIdx]).toBe("true");
    expect(unknownCols[headers.indexOf("metric_window_start")]).toBe("");
    expect(unknownCols[headers.indexOf("metric_window_end")]).toBe("");
  });

  it("loads rule params and clamps payloads", async () => {
    expect(buildFddRuleParamsPath("FC1")).toBe("/api/fdd/rules/FC1/params");
    const body = await getFddRuleParams("FC1");
    expect(body.params?.eps?.default).toBe(0.1);
    expect(clampRuleParam(2, { min: 0, max: 1 })).toBe(1);
    expect(
      buildRuleParamPayload({ eps: 5 }, body.params!),
    ).toEqual({ eps: 1 });
  });
});
