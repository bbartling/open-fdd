import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  buildFddResultsPath,
  buildFddSeriesPath,
  resultsToCsvArtifact,
  resultsToJsonArtifact,
  runFdd,
  getFddResults,
  listFddRules,
} from "./fddApi";

describe("fddApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const u = String(url);
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
      "/api/fdd/series?equipment_id=AHU_1&rule_id=FC1",
    );
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
  });
});
