import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { RulesPage } from "./RulesPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
}));

vi.mock("../api/fddApi", async () => {
  const actual = await vi.importActual<typeof import("../api/fddApi")>(
    "../api/fddApi",
  );
  return {
    ...actual,
    getFddStatus: vi.fn(),
    listFddRules: vi.fn(),
    runFdd: vi.fn(),
  };
});

import { getFddStatus, listFddRules, runFdd } from "../api/fddApi";

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
        equipment_kinds: ["AHU"],
      },
    ]);
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
});
