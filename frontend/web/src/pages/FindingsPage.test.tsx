import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { MappingPage } from "./MappingPage";

vi.mock("../api/jobsApi", () => ({
  listJobs: vi.fn(async () => [
    {
      schema_version: 1,
      job_id: "job-1",
      job_name: "Alpha",
      status: "active",
      archived: false,
      created_at: "",
      updated_at: "",
      tags: [],
      meta_revision: "rev-1",
      revisions: {},
    },
  ]),
}));

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["BUILDING_100"]),
  getPackageMapping: vi.fn(async () => ({
    building_id: "BUILDING_100",
    equipment: [],
    equipment_ids: [],
  })),
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: { schema_version: "openfdd_session_v1", params: {} },
  })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
  listCookbookRoles: vi.fn(async () => []),
  buildMappingManifest: vi.fn(() => "{}"),
  invertRolesToSessionMap: vi.fn(() => ({})),
}));

vi.mock("../api/dataModelTurtle", () => ({
  buildDataModelTurtle: vi.fn(() => ""),
}));

vi.mock("../api/fddApi", () => ({
  getFddResults: vi.fn(async () => []),
  getFddResultsDocument: vi.fn(async () => ({
    ok: true,
    count: 2,
    run_id: "run-active",
    run_status: "complete",
    results: [
      {
        rule_id: "AHU-SATDEV",
        equipment_id: "AHU_1",
        status: "FAULT",
        output_kind: "diagnostic",
        fault_hours: 12,
        fault_pct: 5,
      },
      {
        rule_id: "AVG-ZONE-TEMP",
        equipment_id: "AHU_1",
        status: "METRIC",
        output_kind: "metric",
        fault_hours: null,
        fault_pct: null,
        metric: {
          name: "avg_zone_temp",
          value: 72.4,
          unit: "degF",
          window: { start: "2026-06-01T00:00:00Z", end: "2026-06-02T00:00:00Z" },
          coverage: { sample_rows: 4 },
        },
      },
    ],
  })),
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

vi.mock("../api/findingsApi", async () => {
  const actual = await vi.importActual<typeof import("../api/findingsApi")>(
    "../api/findingsApi",
  );
  return {
    ...actual,
    getJobFindings: vi.fn(async () => ({
      schema_version: "1",
      findings: [
        {
          finding_id: "f1",
          correlation_key: "rule:VAV-1:equip:AHU-1",
          run_id: "run-1",
        },
      ],
    })),
    getJobDispositions: vi.fn(async () => ({
      schema_version: "1",
      dispositions: [
        { correlation_key: "rule:VAV-1:equip:AHU-1", status: "open" },
      ],
    })),
    putJobDispositions: vi.fn(async () => undefined),
  };
});

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

function renderPage(
  entry = "/mapping?view=results&site=BUILDING_100&job=job-1",
) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <MappingPage />
    </MemoryRouter>,
  );
}

describe("Data Model Results by Category", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows FDD results grouped by category under Data Model", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("data-model-subnav")).toBeTruthy();
      expect(screen.getByTestId("results-table")).toBeTruthy();
      expect(screen.getByText("AHU-SATDEV")).toBeTruthy();
      expect(screen.getByText("72.4 degF")).toBeTruthy();
      expect(screen.getByTestId("results-run-caption").textContent).toMatch(
        /run-active/,
      );
      expect(screen.queryByText("PASS")).toBeNull();
      const hitlTrigger = screen.getByRole("button", {
        name: "Engineering findings HITL (job dispositions)",
      });
      expect(hitlTrigger.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(hitlTrigger);
      expect(
        screen.getByRole("button", { name: "Mark first finding open" }),
      ).toBeTruthy();
    });
    expect(screen.queryByText(/demo/i)).toBeNull();
  });
});
