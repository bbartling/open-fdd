import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  monthlySumClient,
  postMetering,
  SAMPLE_METER_ROWS,
  listFddEquipment,
} from "./analyticsApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./client";

describe("monthlySumClient", () => {
  it("matches Rust metering monthly_sum fixture totals", () => {
    const sums = monthlySumClient(SAMPLE_METER_ROWS);
    expect(sums).toEqual([
      { period: "2024-01", kwh: 150.5, meter_id: undefined, n_rows: 2 },
      { period: "2024-02", kwh: 200, meter_id: undefined, n_rows: 1 },
      { period: "2024-03", kwh: 175.25, meter_id: undefined, n_rows: 1 },
    ]);
  });
});

describe("postMetering", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("POSTs /api/analytics/metering with series rows", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      analytics: {
        schema_version: "analytics-envelope-v1",
        query_version: "metering-v1",
        generated_at: "2024-01-01T00:00:00Z",
        engine: "central-analytics-v1",
        warnings: [],
        rows: [{ period: "2024-01", kwh: 150.5, n_rows: 2 }],
        equipment: [],
        points: [],
        skipped: [],
        coverage: { total_kwh: 150.5 },
      },
    });
    const env = await postMetering({
      building_id: "B1",
      series: { rows: SAMPLE_METER_ROWS.slice(0, 2) },
    });
    expect(apiFetch).toHaveBeenCalledWith("/api/analytics/metering", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: expect.stringContaining("2024-01"),
    });
    expect(env.query_version).toBe("metering-v1");
    expect(env.rows[0]?.kwh).toBe(150.5);
  });

  it("also accepts a flat envelope (tests / older mocks)", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      schema_version: "analytics-envelope-v1",
      query_version: "metering-v1",
      generated_at: "2024-01-01T00:00:00Z",
      engine: "central-analytics-v1",
      warnings: [],
      rows: [{ period: "2024-01", kwh: 42 }],
      equipment: [],
      points: [],
      skipped: [],
    });
    const env = await postMetering({ building_id: "B1" });
    expect(env.rows[0]?.kwh).toBe(42);
  });
});

describe("unwrapAnalyticsEnvelope", () => {
  it("pulls nested analytics from central {ok, analytics}", async () => {
    const { unwrapAnalyticsEnvelope } = await import("./analyticsApi");
    const env = unwrapAnalyticsEnvelope({
      ok: true,
      analytics: {
        schema_version: "v1",
        query_version: "runtime-v1",
        generated_at: "",
        engine: "datafusion",
        warnings: ["w"],
        rows: [{ equipment_id: "AHU_1", run_hours: 10 }],
        equipment: [],
        points: [],
        skipped: [],
      },
    });
    expect(env.rows).toHaveLength(1);
    expect(env.engine).toBe("datafusion");
  });
});

describe("listFddEquipment", () => {
  it("reads equipment array from /api/fdd/equipment", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      equipment: [{ equipment_id: "AHU_1", equipment_type: "AHU" }],
    });
    const items = await listFddEquipment("B1");
    expect(apiFetch).toHaveBeenCalledWith("/api/fdd/equipment?building_id=B1");
    expect(items).toHaveLength(1);
  });
});
