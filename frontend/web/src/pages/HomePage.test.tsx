import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { HomePage } from "./HomePage";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
  getPackageMapping: vi.fn(async () => ({
    ok: true,
    equipment: [
      {
        equipment_id: "AHU_1",
        equipment_type: "AHU",
        ok: true,
        sampling: {
          row_count: 100,
          first_timestamp: "2026-01-01T00:00:00Z",
          last_timestamp: "2026-02-01T00:00:00Z",
        },
        columns: [{ column: "sat", role: "sat", status: "mapped" }],
      },
    ],
  })),
  getSessionConfig: vi.fn(async () => ({ ok: true, config: {} })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/analyticsApi", () => ({
  listFddEquipment: vi.fn(async () => [
    { equipment_id: "AHU_1", equipment_type: "AHU" },
    { equipment_id: "VAV_1", equipment_type: "VAV" },
  ]),
  postRuntime: vi.fn(async () => ({
    schema_version: "1",
    query_version: "runtime-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [{ equipment_id: "AHU_1", run_hours: 10, coverage_pct: 50 }],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postMechanicalCooling: vi.fn(async () => ({
    schema_version: "1",
    query_version: "mechanical-cooling-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [{ equipment_id: "AHU_1", history_rows: 100 }],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postEconomizer: vi.fn(async () => ({
    schema_version: "1",
    query_version: "economizer-diagnostics-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [
      {
        equipment_id: "AHU_1",
        n_fan_on_samples: 10,
        n_identifiable: 5,
      },
    ],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postSchedule: vi.fn(async () => ({
    schema_version: "1",
    query_version: "schedule-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [
      {
        equipment_id: "AHU_1",
        occupied_hours: 40,
        unoccupied_hours: 10,
      },
    ],
    equipment: [],
    points: [],
    skipped: [],
  })),
}));

vi.mock("../api/csvDownload", () => ({
  downloadRowsCsv: vi.fn(),
}));

vi.mock("../api/fddApi", () => ({
  getFddStatus: vi.fn(async () => ({ rule_count: 59, rules_dir: "x", rules_dir_exists: true })),
  listFddRules: vi.fn(async () => []),
  getFddResults: vi.fn(async () => []),
  getFddSeries: vi.fn(async () => ({
    ok: true,
    roles: ["sat"],
    rows: [{ timestamp_utc: "t", sat: 1 }],
  })),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
  runFdd: vi.fn(async () => ({
    ok: true,
    results: [],
    total_ms: 12,
    rules_run: 0,
  })),
}));

vi.mock("../api/cutoverApi", () => ({
  getUiGeneration: vi.fn(async () => ({ generation: "react" })),
}));

vi.mock("../api/uploadApi", () => ({
  uploadPackage: vi.fn(),
}));

import { apiFetch } from "../api/client";
import { listPackageBuildings } from "../api/mappingApi";
import { listFddEquipment } from "../api/analyticsApi";

describe("HomePage overview", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      contract: { contract_version: "1.0.0-test" },
      capabilities: { react_ui: true },
    });
    vi.mocked(listPackageBuildings).mockClear();
    vi.mocked(listFddEquipment).mockClear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it("shows populated Overview analytics when authenticated with equipment", async () => {
    sessionStorage.setItem("openfdd.auth.token", "test-token");
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("overview-populated")).toBeTruthy();
      expect(screen.getByTestId("overview-eq-count").textContent).toContain("2");
      expect(screen.getByTestId("overview-motor-runtime")).toBeTruthy();
      expect(screen.getByTestId("overview-schedule")).toBeTruthy();
    });
    expect(listPackageBuildings).toHaveBeenCalled();
    expect(listFddEquipment).toHaveBeenCalled();
  });

  it("loads site inventory without a browser token (open mode)", async () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("overview-populated")).toBeTruthy();
      expect(screen.getByTestId("overview-eq-count").textContent).toContain("2");
    });
    expect(listPackageBuildings).toHaveBeenCalled();
    expect(listFddEquipment).toHaveBeenCalled();
  });
});
