import { describe, expect, it } from "vitest";
import fixture from "../fixtures/sqlAnomalyEventV1.json";
import { unwrapAnalyticsEnvelope } from "../api/analyticsApi";
import {
  SQL_ANOMALY_QUERY_VERSION,
  SQL_ANOMALY_ROW_KEYS,
  anomalyEmptyNote,
  formatAnomalyNumber,
  formatAnomalyTimestamp,
  parseAnomalyEnvelope,
  type AnomalyEnvelopeInput,
} from "./sqlAnomaly";

interface FixtureCase extends AnomalyEnvelopeInput {
  query_version: string;
  warnings: string[];
  rows: Record<string, unknown>[];
  coverage: {
    n_flagged: number;
    n_returned: number;
    n_scored: number;
    series: Array<{ equipment_id: string; role: string; reason: string; n: number; n_null: number }>;
  };
}

const cases = fixture.cases as Record<string, FixtureCase>;

function parsed(name: string) {
  const item = cases[name];
  const env = unwrapAnalyticsEnvelope({
    schema_version: "",
    query_version: item.query_version,
    generated_at: "",
    engine: "timescale-sql",
    warnings: item.warnings,
    rows: item.rows,
    equipment: [],
    points: [],
    skipped: [],
    coverage: item.coverage,
  });
  return parseAnomalyEnvelope(env);
}

describe("sql anomaly event fixture", () => {
  it("parses every route case through the analytics envelope", () => {
    expect(fixture.query_version).toBe(SQL_ANOMALY_QUERY_VERSION);
    expect(fixture.row_keys).toEqual([...SQL_ANOMALY_ROW_KEYS]);
    for (const name of Object.keys(cases)) {
      const result = parsed(name);
      expect(result.queryVersion).toBe(SQL_ANOMALY_QUERY_VERSION);
      expect(result.rows.every((row) => row.anomaly_flag === "ANOMALY")).toBe(true);
      expect(result.rows.every((row) => row.method === "zscore")).toBe(true);
    }
  });

  it("keeps interior flags unless the caller asks for rising edges", () => {
    const multi = parsed("multi_event");
    const edges = parsed("transition_edges");
    expect(multi.rows.some((row) => row.transition === false)).toBe(true);
    expect(edges.rows.some((row) => row.transition === false)).toBe(false);
    expect(edges.coverage.n_flagged).toBe(multi.coverage.n_flagged);
    expect(edges.coverage.n_returned).toBeLessThan(multi.coverage.n_returned);
    expect(anomalyEmptyNote(multi)).toBeNull();
    expect(anomalyEmptyNote(edges)).toBeNull();
  });

  it("drops the lower z when the threshold rises and scores a miss above it", () => {
    const multi = parsed("multi_event");
    const custom = parsed("custom_threshold");
    const high = parsed("high_threshold");
    const lowZ = multi.rows.filter((row) => row.transition === false).map((row) => row.ts);
    expect(lowZ.length).toBeGreaterThan(0);
    const customTs = custom.rows.map((row) => row.ts);
    for (const ts of lowZ) {
      expect(customTs).not.toContain(ts);
    }
    expect(custom.rows.length).toBeGreaterThan(0);
    expect(high.rows).toEqual([]);
    expect(high.coverage.n_scored).toBeGreaterThan(0);
    expect(high.coverage.series.every((row) => row.reason === "scored")).toBe(true);
    expect(anomalyEmptyNote(high)).toBe("No anomaly events at this threshold.");
  });

  it("classifies short, constant, missing, quiet, and empty history", () => {
    expect(anomalyEmptyNote(parsed("no_event"))).toBe(
      "No anomaly events at this threshold.",
    );
    expect(parsed("no_event").coverage.series.every((row) => row.reason === "scored")).toBe(
      true,
    );
    expect(anomalyEmptyNote(parsed("short_history"))).toBe(
      "History is shorter than the window, so no anomaly events were scored.",
    );
    expect(anomalyEmptyNote(parsed("long_window"))).toBe(
      "History is shorter than the window, so no anomaly events were scored.",
    );
    expect(anomalyEmptyNote(parsed("constant_history"))).toBe(
      "History has no variance, so no anomaly events were scored.",
    );
    expect(anomalyEmptyNote(parsed("missing_values"))).toBe(
      "Screened points have no numeric history in this window.",
    );
    const missing = parsed("missing_values");
    expect(missing.coverage.n_samples).toBe(0);
    expect(missing.coverage.series[0]?.n).toBe(0);
    expect(missing.coverage.series[0]?.n_null).toBeGreaterThan(0);
    expect(anomalyEmptyNote(parsed("no_history"))).toBe(
      "No screened samples in this window.",
    );
    expect(parsed("no_history").coverage.series).toEqual([]);
  });

  it("keeps an exact equipment id and ignores an unscreened role", () => {
    const multi = parsed("multi_event");
    const exact = parsed("exact_equipment");
    const ids = new Set(multi.rows.map((row) => row.equipment_id));
    const exactIds = new Set(exact.rows.map((row) => row.equipment_id));
    expect(ids.size).toBe(2);
    expect(exactIds.size).toBe(1);
    const kept = [...exactIds][0];
    expect(kept).toBeTruthy();
    expect(ids.has(kept ?? "")).toBe(true);
    for (const row of exact.rows) {
      expect(row.equipment_id).toBe(kept);
    }
    expect(multi.rows.every((row) => row.role !== "zone_rh")).toBe(true);
    expect(new Set(multi.rows.map((row) => row.row_key)).size).toBe(multi.rows.length);
  });

  it("preserves offset timestamps as UTC microseconds and the 80.125 value", () => {
    const zone = parsed("timezone_precision");
    expect(zone.rows).toHaveLength(1);
    const event = zone.rows[0];
    expect(event.ts).toBe("2026-06-16T00:15:00.000000Z");
    expect(event.val).toBe(80.125);
    expect(formatAnomalyNumber(event.val)).toBe("80.125");
    expect(formatAnomalyTimestamp(event.ts)).toBe("2026-06-16 00:15:00Z");
    expect(event.ts.includes("-04")).toBe(false);
    expect(event.ts.includes("+00")).toBe(false);
    expect(zone.coverage.window_start).toBe("2026-06-15T20:15:00Z");
    expect(zone.coverage.window_end).toBe("2026-06-16T00:15:01Z");
  });

  it("answers an old version and an unsupported method without a summary row", () => {
    const legacy = parsed("legacy_version");
    const multi = parsed("multi_event");
    expect(legacy.queryVersion).toBe(SQL_ANOMALY_QUERY_VERSION);
    expect(legacy.rows.map((row) => row.row_key)).toEqual(multi.rows.map((row) => row.row_key));
    expect(legacy.warnings.some((warning) => warning.includes("sql-anomaly-v1"))).toBe(true);
    const unsupported = parsed("unsupported_method");
    expect(unsupported.rows).toEqual([]);
    expect(anomalyEmptyNote(unsupported)).toMatch(/not supported/);
    const disabled = parsed("disabled");
    expect(disabled.rows).toEqual([]);
    expect(anomalyEmptyNote(disabled)).toMatch(/disabled/);
  });

  it("rejects a summary payload and a wrong query version", () => {
    expect(() =>
      parseAnomalyEnvelope({
        query_version: "sql-anomaly-v1",
        warnings: [],
        rows: [
          {
            equipment_id: "X",
            role: "sat",
            score: 4,
            anomaly_hours: 2,
            anomaly_events: 1,
            last_at: "2026-06-01T00:00:00Z",
          },
        ],
      }),
    ).toThrow(/event contract/);
    expect(() =>
      parseAnomalyEnvelope({
        query_version: SQL_ANOMALY_QUERY_VERSION,
        warnings: [],
        rows: [
          {
            score: 4,
            anomaly_hours: 1,
            anomaly_flag: "ANOMALY",
            avg_val: 1,
            equipment_id: "X",
            method: "zscore",
            role: "sat",
            stddev_val: 1,
            threshold: 3,
            transition: true,
            ts: "2026-06-01T00:00:00.000000Z",
            val: 1,
            z_abs: 4,
          },
        ],
      }),
    ).toThrow(/event contract/);
  });
});
