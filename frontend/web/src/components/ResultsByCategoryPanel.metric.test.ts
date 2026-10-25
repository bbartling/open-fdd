import { describe, expect, it } from "vitest";
import type { FddResultRow } from "../api/fddApi";
import { metricProvenance, metricWindow } from "./ResultsByCategoryPanel";

function metricRow(partial: FddResultRow["metric"]): FddResultRow {
  return {
    rule_id: "AVG-ZONE-TEMP",
    equipment_id: "AHU_1",
    status: "METRIC",
    output_kind: "metric",
    metric: partial,
  };
}

describe("metricWindow / metricProvenance", () => {
  it("shows the effective observed window and sample coverage", () => {
    const row = metricRow({
      name: "avg_zone_temp",
      value: 72,
      unit: "degF",
      window: {
        start: "2026-06-01T00:00:00Z",
        end: "2026-06-08T00:00:00Z",
        observed_start: "2026-06-01T00:00:00Z",
        observed_end: "2026-06-08T00:00:00Z",
        unknown: false,
      },
      coverage: { sample_rows: 1900 },
      provenance: {
        source: "timescale",
        config_fingerprint: "abc123def456",
        watermark: "2026-06-08T00:00:00Z",
      },
    });
    expect(metricWindow(row)).toBe(
      "2026-06-01T00:00:00Z → 2026-06-08T00:00:00Z · 1900 samples",
    );
    expect(metricProvenance(row)).toContain("timescale");
    expect(metricProvenance(row)).toContain("watermark");
    expect(metricProvenance(row)).toContain("config abc123def456");
  });

  it("prints unknown when the historian did not supply a window", () => {
    const row = metricRow({
      name: "avg_zone_temp",
      value: 72,
      unit: "degF",
      window: {
        start: null,
        end: null,
        unknown: true,
      },
      coverage: { sample_rows: 4 },
    });
    expect(metricWindow(row)).toBe("unknown · 4 samples");
    expect(metricWindow(row)).not.toMatch(/—\s*→\s*—/);
  });

  it("treats a missing window object as unknown, not an invented span", () => {
    expect(metricWindow(metricRow(null))).toBe("unknown");
    expect(metricWindow(metricRow(undefined))).toBe("unknown");
  });
});
