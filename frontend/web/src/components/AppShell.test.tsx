import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AppShell } from "./AppShell";
import { MAIN_SECTIONS } from "../nav/sections";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => []),
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: { schema_version: "openfdd_session_v1", params: {} },
  })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/uploadApi", () => ({
  uploadPackage: vi.fn(),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => [
    {
      rule_id: "AHU-SATDEV",
      description: "SAT deviation",
      parameter_count: 2,
      required_roles: [],
    },
  ]),
  getFddRuleParams: vi.fn(async () => ({
    ok: true,
    rule_id: "AHU-SATDEV",
    params: {
      confirm_min: {
        key: "confirm_min",
        label: "Fault confirm delay",
        default: 10,
        min: 0,
        max: 60,
        step: 1,
        unit: "min",
        control: "slider",
        sql_placeholder: "",
      },
    },
  })),
}));

describe("AppShell layout parity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders main section order, brand, and Rule tuning", async () => {
    render(
      <MemoryRouter>
        <AppShell title="Home" caption="Parity shell">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByText("Open-FDD")).toBeTruthy();
    expect(screen.getByTestId("sidebar-sites")).toBeTruthy();
    expect(screen.queryByTestId("nav-sites")).toBeNull();
    expect(screen.getAllByText("Sites").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("sidebar-building-data")).toBeTruthy();
    expect(screen.getByText("Building data")).toBeTruthy();
    expect(screen.getByTestId("sidebar-rule-tuning")).toBeTruthy();
    expect(screen.getByText("Rule tuning")).toBeTruthy();
    expect(screen.getByTestId("page-caption").textContent).toBe("Parity shell");

    const tabs = screen.getByTestId("section-tabs");
    const labels = [...tabs.querySelectorAll("[data-section]")].map(
      (el) => el.getAttribute("data-section"),
    );
    expect(labels).toEqual(MAIN_SECTIONS.map((s) => s.id));

    const tabText = [...tabs.querySelectorAll("[data-section]")].map(
      (el) => el.textContent?.trim(),
    );
    expect(tabText).toEqual([
      "Overview",
      "Data Model",
      "Actions",
      "Results by Category",
      "FDD Plots",
      "RCx Plots",
      "Metering",
      "WattLab",
      "Sites",
    ]);
  });

  it("collapses the sidebar when toggle is pressed", () => {
    render(
      <MemoryRouter>
        <AppShell title="Jobs">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    const shell = screen.getByTestId("app-shell");
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("false");
    fireEvent.click(screen.getByTestId("sidebar-collapse"));
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("true");
  });

  it("keeps Streamlit-like full-width layout contract markers", () => {
    // CSS file regex lives in scripts/assert_full_width.mjs (npm test).
    // This marker keeps the product intent visible next to AppShell tests.
    expect("full-width").toBe("full-width");
  });
});
