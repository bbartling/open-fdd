import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { HomePage } from "./HomePage";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(),
}));

const { emptyHealth } = vi.hoisted(() => {
  const emptyHealth = async () => ({
    schema_version: "1",
    query_version: "health-test",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  });
  return { emptyHealth };
});

vi.mock("../api/overviewHealthApi", () => ({
  postAhuTemperatureHealth: vi.fn(emptyHealth),
  postAhuPressureHealth: vi.fn(emptyHealth),
  postAhuEconomizerHealth: vi.fn(emptyHealth),
  postCoolingTowerHealth: vi.fn(emptyHealth),
  postPidHunting: vi.fn(emptyHealth),
  postSensorFaults: vi.fn(emptyHealth),
  postZoneOtherHealth: vi.fn(emptyHealth),
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
    { equipment_id: "weather", equipment_type: "weather" },
    { equipment_id: "AHU_1", equipment_type: "AHU" },
    { equipment_id: "VAV_1", equipment_type: "VAV" },
  ]),
  postInspect: vi.fn(async () => ({
    coverage: {
      plottable_columns: ["sat"],
      columns_plotted: ["sat"],
      row_count: 100,
    },
    points: [],
    warnings: [],
  })),
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
  postBasVsWebOat: vi.fn(async () => ({
    schema_version: "1",
    query_version: "bas-vs-web-oat-v2",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
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
  postVavHealth: vi.fn(async () => ({
    schema_version: "1",
    query_version: "vav-health-v1",
    generated_at: "",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  })),
  postAhuHealth: vi.fn(emptyHealth),
  postChillerHealth: vi.fn(emptyHealth),
  postBoilerHealth: vi.fn(emptyHealth),
  postHpHealth: vi.fn(emptyHealth),
  postSqlAnomaly: vi.fn(emptyHealth),
  postPlantHealth: vi.fn(emptyHealth),
  postAnalytics: vi.fn(emptyHealth),
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

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="loc">{location.search}</span>;
}

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
      expect(screen.getByTestId("overview-devices-by-type")).toBeTruthy();
      expect(screen.getByTestId("overview-schedule")).toBeTruthy();
    });
    expect(screen.getByTestId("oracle-hero-logo")).toBeTruthy();
    expect(screen.queryByTestId("oracle-hero-how")).toBeNull();
    expect(screen.queryByText(/WattLab energy twin/)).toBeNull();
    expect(screen.queryByText(/How it works/)).toBeNull();
    expect(listPackageBuildings).toHaveBeenCalled();
    expect(listFddEquipment).toHaveBeenCalled();
    const hero = screen.getByTestId("oracle-hero");
    expect(hero.querySelector('[data-testid="section-tabs"]')).toBeNull();
    expect(screen.queryByTestId("overview-equipment-select")).toBeNull();
    expect(screen.getByTestId("section-tabs")).toBeTruthy();
    expect(screen.getByTestId("overview-idle-hint")).toBeTruthy();
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

  it("commits only the latest site when a previous inventory response arrives late", async () => {
    const lists = new Map<
      string,
      ReturnType<typeof deferred<Awaited<ReturnType<typeof listFddEquipment>>>>
    >();
    vi.mocked(listPackageBuildings).mockResolvedValue(["SITE_A", "SITE_B"]);
    vi.mocked(listFddEquipment).mockImplementation(async (site?: string) => {
      const slot = deferred<Awaited<ReturnType<typeof listFddEquipment>>>();
      lists.set(String(site), slot);
      return slot.promise;
    });

    render(
      <MemoryRouter initialEntries={["/?site=SITE_A&eq=EQ_A"]}>
        <LocationProbe />
        <HomePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(lists.has("SITE_A")).toBe(true);
    });
    await waitFor(() => {
      expect(screen.getByTestId("sidebar-active-site")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("sidebar-active-site"), {
      target: { value: "SITE_B" },
    });
    await waitFor(() => {
      expect(screen.getByTestId("loc").textContent).toContain("site=SITE_B");
    });
    expect(screen.getByTestId("loc").textContent ?? "").not.toContain("EQ_A");
    await waitFor(() => {
      expect(lists.has("SITE_B")).toBe(true);
    });
    lists.get("SITE_B")!.resolve([
      { equipment_id: "EQ_B", equipment_type: "VAV" },
    ]);
    await waitFor(() => {
      expect(deviceTypeCount("VAV")).toBe("1");
    });
    lists.get("SITE_A")!.resolve([
      { equipment_id: "EQ_A", equipment_type: "AHU" },
    ]);
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(deviceTypeCount("VAV")).toBe("1");
    expect(deviceTypeCount("AHU")).toBe("0");
    expect(screen.getByTestId("loc").textContent ?? "").not.toContain("EQ_A");
    expect(screen.getByTestId("loc").textContent).toContain("EQ_B");
  });
});

function deviceTypeCount(type: string): string {
  const table = screen.getByTestId("overview-devices-table");
  const rows = [...table.querySelectorAll("tbody tr")];
  const row = rows.find((tr) => tr.querySelector("td")?.textContent === type);
  return row?.querySelectorAll("td")[1]?.textContent ?? "";
}
