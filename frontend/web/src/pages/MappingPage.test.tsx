import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { MappingPage } from "./MappingPage";

vi.mock("../api/mappingApi", async () => {
  const actual = await vi.importActual<typeof import("../api/mappingApi")>(
    "../api/mappingApi",
  );
  return {
    ...actual,
    listPackageBuildings: vi.fn(),
    getPackageMapping: vi.fn(),
    getSessionConfig: vi.fn(),
    updatePackageRoles: vi.fn(),
    putSessionConfig: vi.fn(),
  };
});

import {
  getPackageMapping,
  getSessionConfig,
  listPackageBuildings,
  putSessionConfig,
  updatePackageRoles,
} from "../api/mappingApi";

function renderMapping(entry = "/mapping?site=B1&eq=AHU_1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <MappingPage />
    </MemoryRouter>,
  );
}

describe("MappingPage", () => {
  beforeEach(() => {
    vi.mocked(listPackageBuildings).mockResolvedValue(["B1"]);
    vi.mocked(getSessionConfig).mockResolvedValue({
      ok: true,
      config: {
        schema_version: "openfdd_session_v1",
        unit_system: "imperial",
        role_map: {},
        params: {},
      },
    });
    vi.mocked(getPackageMapping).mockResolvedValue({
      ok: true,
      building_id: "B1",
      unit_system: "imperial",
      equipment_ids: ["AHU_1"],
      equipment: [
        {
          equipment_id: "AHU_1",
          equipment_type: "AHU",
          ok: true,
          parent_ahu: null,
          roles: { SF_SPD: "fan_cmd" },
          columns: [
            { column: "SF_SPD", role: "fan_cmd", status: "mapped" },
            { column: "DA_P", role: "", status: "unmapped" },
          ],
          unmapped_columns: ["DA_P"],
          blockers: [],
          warnings: ["1 unmapped column(s)"],
          sampling: {
            ok: true,
            row_count: 6,
            first_timestamp: "2024-01-01T00:00:00Z",
            last_timestamp: "2024-01-01T00:25:00Z",
          },
        },
      ],
      validation: { blocker_count: 0, warning_count: 1, equipment_count: 1 },
    });
    vi.mocked(updatePackageRoles).mockResolvedValue({
      ok: true,
      building_id: "B1",
      equipment_id: "AHU_1",
      roles: { SF_SPD: "fan_status" },
    });
    vi.mocked(putSessionConfig).mockResolvedValue({
      ok: true,
      config: {
        schema_version: "openfdd_session_v1",
        unit_system: "imperial",
        role_map: { AHU_1: { fan_status: "SF_SPD" } },
      },
      warnings: [],
    });
  });

  it("loads inventory for ?site= and shows sampling + warning", async () => {
    renderMapping();
    await waitFor(() => {
      expect(screen.getByTestId("mapping-equipment-detail")).toBeTruthy();
    });
    expect(screen.getByTestId("mapping-sampling").textContent).toMatch(/6 rows/);
    expect(screen.getByTestId("mapping-warning").textContent).toMatch(/unmapped/);
    expect(screen.getByTestId("mapping-validation-summary").textContent).toMatch(
      /1 warning/,
    );
  });

  it("saves role edits via package roles + session-config", async () => {
    renderMapping();
    await waitFor(() => screen.getByTestId("map-role-input-SF_SPD"));
    fireEvent.change(screen.getByTestId("map-role-input-SF_SPD"), {
      target: { value: "fan_status" },
    });
    expect(screen.getByTestId("map-dirty-banner")).toBeTruthy();
    const saveBtn = screen.getByTestId("map-save").querySelector("button");
    fireEvent.click(saveBtn!);
    await waitFor(() => {
      expect(updatePackageRoles).toHaveBeenCalledWith("B1", "AHU_1", {
        SF_SPD: "fan_status",
      });
      expect(putSessionConfig).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByTestId("mapping-notice").textContent).toMatch(/Saved mapping/);
    });
  });

  it("prompts to select a building when site is empty", async () => {
    renderMapping("/mapping");
    await waitFor(() => {
      expect(screen.getByTestId("mapping-empty-building")).toBeTruthy();
    });
  });
});
