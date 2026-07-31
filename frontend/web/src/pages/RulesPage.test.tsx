import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { RulesPage } from "./RulesPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: {
      schema_version: "openfdd_session_v1",
      unit_system: "imperial",
      role_map: {},
      params: {},
    },
  })),
  putSessionConfig: vi.fn(async (config: unknown) => ({
    ok: true,
    config,
    warnings: [],
  })),
}));

vi.mock("../api/fddApi", async () => {
  const actual = await vi.importActual<typeof import("../api/fddApi")>(
    "../api/fddApi",
  );
  return {
    ...actual,
    getFddStatus: vi.fn(),
    listFddRules: vi.fn(),
    getFddRuleParams: vi.fn(),
    runFdd: vi.fn(),
  };
});

import { getFddStatus, listFddRules, getFddRuleParams, runFdd } from "../api/fddApi";
import { putSessionConfig } from "../api/mappingApi";

function renderRules(entry = "/rules?site=B1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <RulesPage />
    </MemoryRouter>,
  );
}

describe("RulesPage", () => {
  beforeEach(() => {
    vi.mocked(getFddStatus).mockResolvedValue({
      ok: true,
      rules_dir: "sql_rules",
      rules_dir_exists: true,
      rule_count: 1,
      hint: "POST /api/fdd/run",
    });
    vi.mocked(listFddRules).mockResolvedValue([
      {
        rule_id: "FC1",
        description: "Fan speed",
        parity_status: "proven_building_100",
        parameter_count: 1,
        required_roles: ["fan_cmd"],
      },
    ]);
    vi.mocked(getFddRuleParams).mockResolvedValue({
      ok: true,
      rule_id: "FC1",
      params: {
        eps_vfd_spd: {
          key: "eps_vfd_spd",
          label: "VFD eps",
          default: 0.05,
          min: 0,
          max: 0.5,
          step: 0.01,
          unit: "frac",
          control: "slider",
          sql_placeholder: "EPS_VFD_SPD",
        },
      },
    });
    vi.mocked(runFdd).mockResolvedValue({
      ok: true,
      engine: "fdd_rules+DataFusion",
      rules_succeeded: 1,
      rules_failed: 0,
      rules_skipped: 0,
      total_ms: 12,
      timings: [{ rule_id: "FC1", status: "SUCCEEDED", ms: 12 }],
      results: [
        {
          rule_id: "FC1",
          equipment_id: "AHU_1",
          status: "PASS",
          fault_hours: 0,
        },
      ],
    });
  });

  it("shows registry status and runs FDD for ?site=", async () => {
    renderRules();
    await waitFor(() => {
      expect(screen.getByTestId("fdd-status").textContent).toMatch(/1 rules/);
    });
    const runBtn = screen.getByTestId("fdd-run").querySelector("button");
    fireEvent.click(runBtn!);
    await waitFor(() => {
      expect(runFdd).toHaveBeenCalled();
      expect(screen.getByTestId("fdd-run-summary").textContent).toMatch(
        /succeeded 1/,
      );
    });
    expect(vi.mocked(runFdd).mock.calls[0][0]).toMatchObject({
      building_id: "B1",
      mode: "registry",
    });
  });

  it("requires building before run", async () => {
    renderRules("/rules");
    await waitFor(() => screen.getByTestId("fdd-run"));
    const runBtn = screen.getByTestId("fdd-run").querySelector("button");
    expect(runBtn?.disabled).toBe(true);
  });

  it("loads param sliders and saves to session-config", async () => {
    renderRules();
    await waitFor(() => screen.getByTestId("fdd-param-eps_vfd_spd"));
    fireEvent.change(screen.getByTestId("fdd-param-num-eps_vfd_spd"), {
      target: { value: "0.12" },
    });
    const saveBtn = screen.getByTestId("fdd-save-params").querySelector("button");
    fireEvent.click(saveBtn!);
    await waitFor(() => {
      expect(putSessionConfig).toHaveBeenCalled();
      expect(screen.getByTestId("rules-notice").textContent).toMatch(/Saved params/);
    });
  });
});
