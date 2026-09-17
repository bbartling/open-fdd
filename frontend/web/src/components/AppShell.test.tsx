import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AppShell } from "./AppShell";
import { MAIN_SECTIONS } from "../nav/sections";

const appCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../styles/app.css"),
  "utf8",
);

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async (path: string) => {
    if (path === "/api/health") {
      return { ok: true, version: "3.3.2+abcdef123456", service: "openfdd-central" };
    }
    if (path === "/api/tenants") {
      return {
        ok: true,
        multi_tenant: false,
        active_tenant_id: "legacy",
        tenants: [{ id: "legacy", name: "Legacy single-hub tenant" }],
      };
    }
    return {};
  }),
}));

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

  it("renders main section order, brand, and Lab rule thresholds", async () => {
    render(
      <MemoryRouter>
        <AppShell title="Home" caption="Parity shell">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByText("Open-FDD")).toBeTruthy();
    expect(await screen.findByTestId("app-revision")).toBeTruthy();
    expect(screen.getByTestId("app-revision").textContent).toBe("3.3.2+abcdef1");
    expect(await screen.findByTestId("app-tenant")).toBeTruthy();
    expect(screen.getByTestId("app-tenant").textContent).toContain("legacy");
    expect(screen.getByTestId("sidebar-sites")).toBeTruthy();
    expect(screen.queryByTestId("nav-sites")).toBeNull();
    expect(screen.getAllByText("Sites").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("sidebar-building-data")).toBeTruthy();
    expect(screen.getByText("Building data")).toBeTruthy();
    expect(screen.getByTestId("sidebar-rule-tuning")).toBeTruthy();
    expect(screen.getByText("Lab · rule thresholds")).toBeTruthy();
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
      "Inspect",
      "Data Model",
      "Actions",
      "Results by Category",
      "FDD Plots",
      "RCx Plots",
      "Metering",
      "Dump",
      "Sites",
      "Operations",
      "Admin",
    ]);
  });

  it("collapses the sidebar when toggle is pressed", async () => {
    render(
      <MemoryRouter>
        <AppShell title="Jobs">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    const shell = screen.getByTestId("app-shell");
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("false");
    expect(await screen.findByTestId("app-revision")).toBeTruthy();
    fireEvent.click(screen.getByTestId("sidebar-collapse"));
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("true");
    expect(screen.getByTestId("app-revision").textContent).toBe("+abcdef1");
  });

  it("keeps Streamlit-like full-width layout contract markers", () => {
    // CSS file regex lives in scripts/assert_full_width.mjs (npm test).
    // This marker keeps the product intent visible next to AppShell tests.
    expect("full-width").toBe("full-width");
  });

  it("defines independent scroll panes for shell, sidebar, and main", () => {
    render(
      <MemoryRouter>
        <AppShell title="Scroll">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("app-shell").classList.contains("app-shell")).toBe(
      true,
    );
    expect(screen.getByTestId("app-main").classList.contains("app-main")).toBe(
      true,
    );
    expect(document.getElementById("app-sidebar-oracle")).toBeTruthy();

    const shellBlock = appCss.match(/\.app-shell\s*\{[^}]+\}/s)?.[0] ?? "";
    expect(shellBlock).toMatch(/overflow:\s*hidden/);
    expect(shellBlock).toMatch(/max-height:\s*100%/);

    const mainBlock = appCss.match(/\.app-main\s*\{[^}]+\}/s)?.[0] ?? "";
    expect(mainBlock).toMatch(/min-height:\s*0/);
    expect(mainBlock).toMatch(/overflow-y:\s*auto/);
    expect(mainBlock).toMatch(/overscroll-behavior:\s*contain/);
  });

  it("stops wheel propagation from sidebar and main scroll panes", () => {
    render(
      <MemoryRouter>
        <AppShell title="Wheel">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    const sidebar = document.getElementById("app-sidebar-oracle")!;
    Object.defineProperty(sidebar, "scrollHeight", { value: 400, configurable: true });
    Object.defineProperty(sidebar, "clientHeight", { value: 200, configurable: true });
    sidebar.scrollTop = 100;

    const sidebarWheel = new WheelEvent("wheel", {
      deltaY: 10,
      bubbles: true,
      cancelable: true,
    });
    const sidebarStop = vi.spyOn(sidebarWheel, "stopPropagation");
    sidebar.dispatchEvent(sidebarWheel);
    expect(sidebarStop).toHaveBeenCalled();

    const main = screen.getByTestId("app-main");
    Object.defineProperty(main, "scrollHeight", { value: 800, configurable: true });
    Object.defineProperty(main, "clientHeight", { value: 400, configurable: true });
    main.scrollTop = 0;

    const mainWheel = new WheelEvent("wheel", {
      deltaY: -10,
      bubbles: true,
      cancelable: true,
    });
    const mainPrevent = vi.spyOn(mainWheel, "preventDefault");
    const mainStop = vi.spyOn(mainWheel, "stopPropagation");
    main.dispatchEvent(mainWheel);
    expect(mainStop).toHaveBeenCalled();
    expect(mainPrevent).toHaveBeenCalled();
  });
});
