import { describe, expect, it, beforeEach } from "vitest";
import {
  OVERVIEW_HISTORIAN_QUERY_IDS,
  noteOverviewRuleCompletion,
  overviewQueryIdsForRule,
  overviewQueryRequestsRefresh,
  peekOverviewHistorianRefresh,
  releaseOverviewHistorianRefresh,
  requestExplicitOverviewRefresh,
  resetOverviewQueryPolicyForTests,
} from "./overviewQueryPolicy";

describe("overview query refresh policy", () => {
  beforeEach(() => {
    resetOverviewQueryPolicyForTests();
  });

  it("matches a rule to its queries by exact id", () => {
    expect(overviewQueryIdsForRule("FC2")).toEqual(["ahu-temperature-health"]);
    expect(overviewQueryIdsForRule("AHU-SATDEV").sort()).toEqual(
      ["ahu-temperature-health", "hp-health"].sort(),
    );
    expect(overviewQueryIdsForRule("AHU-SAT")).toEqual([]);
    expect(overviewQueryIdsForRule("SV-FLAT")).toEqual([]);
    for (const queryId of OVERVIEW_HISTORIAN_QUERY_IDS) {
      expect(overviewQueryIdsForRule("FC2")).not.toContain(queryId);
    }
  });

  it("lets one rule completion refresh only that rule's queries", () => {
    noteOverviewRuleCompletion("site-a", { mode: "single", rule_id: "FC2" });
    expect(overviewQueryRequestsRefresh("site-a", "ahu-temperature-health")).toBe(true);
    expect(overviewQueryRequestsRefresh("site-a", "ahu-pressure-health")).toBe(false);
    expect(overviewQueryRequestsRefresh("site-a", "sql-anomaly")).toBe(false);
    expect(overviewQueryRequestsRefresh("site-b", "ahu-temperature-health")).toBe(false);
    expect(peekOverviewHistorianRefresh("site-a")).toBe(false);
  });

  it("refreshes every rule-scoped query after a full run, not the historian charts", () => {
    noteOverviewRuleCompletion("site-a", { mode: "all" });
    expect(overviewQueryRequestsRefresh("site-a", "vav-health")).toBe(true);
    expect(overviewQueryRequestsRefresh("site-a", "weather-health")).toBe(true);
    expect(overviewQueryRequestsRefresh("site-a", "sql-anomaly")).toBe(false);
    expect(peekOverviewHistorianRefresh("site-a")).toBe(false);
  });

  it("marks one explicit refresh for historian charts and rule queries", () => {
    requestExplicitOverviewRefresh("site-a");
    expect(peekOverviewHistorianRefresh("site-a")).toBe(true);
    expect(peekOverviewHistorianRefresh("site-a")).toBe(true);
    releaseOverviewHistorianRefresh("site-a");
    expect(peekOverviewHistorianRefresh("site-a")).toBe(false);
    expect(overviewQueryRequestsRefresh("site-a", "sensor-faults")).toBe(true);
    expect(overviewQueryRequestsRefresh("site-a", "sql-anomaly")).toBe(true);
    expect(overviewQueryRequestsRefresh("site-b", "sensor-faults")).toBe(false);
  });

  it("ignores a completion for a different site", () => {
    noteOverviewRuleCompletion("site-a", {
      mode: "single",
      rule_id: "FC2",
      building_id: "site-b",
    });
    expect(overviewQueryRequestsRefresh("site-a", "ahu-temperature-health")).toBe(false);
    expect(overviewQueryRequestsRefresh("site-b", "ahu-temperature-health")).toBe(false);
  });
});
