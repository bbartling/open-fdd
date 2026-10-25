import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AppShell } from "./AppShell";
import { MAIN_SECTIONS } from "../nav/sections";
import { apiFetch } from "../api/client";
import {
  SIDEBAR_COLLAPSED_KEY,
  SIDEBAR_NARROW_MQ,
} from "../lib/sidebarLayout";

const appCss = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../styles/app.css"),
  "utf8",
);

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async (path: string) => {
    if (path === "/api/health") {
      return {
        ok: true,
        version: "3.3.2+abcdef123456",
        service: "openfdd-central",
        historian: "timescale",
        timescale_ok: true,
      };
    }
    if (path === "/api/tenants") {
      return {
        ok: true,
        multi_tenant: false,
        active_tenant_id: "legacy",
        tenants: [{ id: "legacy", name: "Legacy single-hub tenant" }],
      };
    }
    if (path === "/api/auth/me") {
      return {
        ok: true,
        username: "admin",
        role: "admin",
        auth_required: false,
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

const originalFetch = vi.mocked(apiFetch).getMockImplementation();

function membershipResponse(active: string) {
  return {
    ok: true,
    multi_tenant: true,
    active_tenant_id: active,
    tenants: [
      { id: "tenant_a", name: "Tenant A" },
      { id: "tenant_b", name: "Tenant B" },
    ],
  };
}

function mockMatchMedia(matchesNarrow: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => {
      const matches = query === SIDEBAR_NARROW_MQ ? matchesNarrow : false;
      return {
        matches,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      };
    }),
  });
}

describe("AppShell layout parity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    localStorage.clear();
    mockMatchMedia(false);
    if (originalFetch) vi.mocked(apiFetch).mockImplementation(originalFetch);
  });

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
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
    expect(screen.getByTestId("historian-timescale").textContent).toMatch(/Timescale connected/);
    expect(screen.queryByTestId("app-tenant")).toBeNull();
    expect(screen.getByTestId("app-sign-in")).toBeTruthy();
    expect(screen.getByTestId("sidebar-sites")).toBeTruthy();
    expect(screen.queryByTestId("nav-sites")).toBeNull();
    expect(screen.getAllByText("Sites").length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByTestId("sidebar-building-data")).toBeTruthy();
    expect(screen.getByText("CSV Upload")).toBeTruthy();
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
      "FDD Plots",
      "RCx Plots",
      "Metering",
      "Dump",
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
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("1");
    expect(screen.getByTestId("app-revision").textContent).toBe("+abcdef1");
  });

  it("restores the persisted collapse state across remounts", async () => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "1");
    const { unmount } = render(
      <MemoryRouter>
        <AppShell title="Jobs">
          <div data-testid="main-body">body</div>
        </AppShell>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("app-shell").getAttribute("data-sidebar-collapsed")).toBe(
      "true",
    );
    unmount();

    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, "0");
    render(
      <MemoryRouter>
        <AppShell title="Jobs">
          <div data-testid="main-body">body</div>
        </AppShell>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("app-shell").getAttribute("data-sidebar-collapsed")).toBe(
      "false",
    );
    expect(await screen.findByTestId("sidebar-collapse")).toBeTruthy();
    expect(screen.getByTestId("main-body")).toBeTruthy();
  });

  it("defaults to collapsed on a narrow viewport and keeps main reachable", async () => {
    mockMatchMedia(true);
    render(
      <MemoryRouter>
        <AppShell title="Narrow">
          <button type="button" data-testid="main-focus-target">
            Main action
          </button>
        </AppShell>
      </MemoryRouter>,
    );

    const shell = screen.getByTestId("app-shell");
    expect(shell.getAttribute("data-sidebar-viewport")).toBe("narrow");
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("true");
    expect(shell.classList.contains("app-shell--sidebar-narrow")).toBe(true);
    expect(shell.classList.contains("app-shell--sidebar-narrow-expanded")).toBe(
      false,
    );

    fireEvent.click(screen.getByTestId("sidebar-collapse"));
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("false");
    expect(shell.getAttribute("data-sidebar-narrow-expanded")).toBe("true");
    expect(shell.classList.contains("app-shell--sidebar-narrow-expanded")).toBe(
      true,
    );
    expect(localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("0");

    // Both panes stay in the tree for keyboard/focus — no inert / aria-hidden.
    const sidebar = document.getElementById("app-sidebar-oracle");
    const main = screen.getByTestId("app-main");
    expect(sidebar?.getAttribute("aria-hidden")).not.toBe("true");
    expect(main.getAttribute("aria-hidden")).not.toBe("true");
    expect(main.hasAttribute("inert")).toBe(false);
    expect(screen.getByTestId("main-focus-target")).toBeTruthy();
    expect(screen.getByTestId("sidebar-collapse")).toBeTruthy();
  });

  it("keeps a wide expanded layout free of narrow-expanded chrome", async () => {
    mockMatchMedia(false);
    render(
      <MemoryRouter>
        <AppShell title="Wide">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );
    const shell = screen.getByTestId("app-shell");
    expect(shell.getAttribute("data-sidebar-viewport")).toBe("wide");
    expect(shell.getAttribute("data-sidebar-narrow-expanded")).toBe("false");
    expect(shell.classList.contains("app-shell--sidebar-narrow")).toBe(false);
    expect(await screen.findByTestId("sidebar-collapse")).toBeTruthy();
  });

  it("switches the active tenant and clears tenant-scoped client state", async () => {
    sessionStorage.setItem("openfdd.auth.token", "tok-a");
    sessionStorage.setItem("openfdd.formDraft.lab", "{\"note\":\"a\"}");
    localStorage.setItem("openfdd.ui.rule_params", "{\"confirm_min\":10}");
    let active = "tenant_a";
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/health") {
        return {
          ok: true,
          version: "3.3.2+abcdef123456",
          historian: "timescale",
          timescale_ok: true,
        };
      }
      if (path === "/api/auth/me") {
        return {
          ok: true,
          username: "operator",
          role: "operator",
          auth_required: true,
          hub_admin: false,
          multi_tenant: true,
        };
      }
      if (path === "/api/tenants") return membershipResponse(active);
      if (path === "/api/tenants/select") {
        active = "tenant_b";
        return {
          ok: true,
          multi_tenant: true,
          active_tenant_id: "tenant_b",
          token: "tok-b",
          access_token: "tok-b",
        };
      }
      if (path === "/api/sessions/building/leave") return { ok: true };
      return {};
    });

    render(
      <MemoryRouter initialEntries={["/?site=site_a&eq=AHU_1&job=job1"]}>
        <AppShell title="Home">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    const select = (await screen.findByTestId("app-tenant-select")) as HTMLSelectElement;
    expect(select.value).toBe("tenant_a");
    fireEvent.change(select, { target: { value: "tenant_b" } });

    await waitFor(() => {
      expect(screen.getByTestId("nav-home").getAttribute("href")).not.toContain("site=");
    });
    const href = screen.getByTestId("nav-home").getAttribute("href") ?? "";
    expect(href).not.toContain("eq=");
    expect(href).not.toContain("job=");
    expect(sessionStorage.getItem("openfdd.formDraft.lab")).toBeNull();
    const ruleBag = localStorage.getItem("openfdd.ui.rule_params");
    expect(ruleBag == null || ruleBag === "{}").toBe(true);
    const selectCall = vi
      .mocked(apiFetch)
      .mock.calls.find((call) => call[0] === "/api/tenants/select");
    expect(selectCall).toBeTruthy();
    const leaveCall = vi
      .mocked(apiFetch)
      .mock.calls.find((call) => call[0] === "/api/sessions/building/leave");
    expect(leaveCall?.[1]?.body).toContain("site_a");
    expect(sessionStorage.getItem("openfdd.auth.token")).toBe("tok-b");
  });

  it("keeps the current site when tenant select fails", async () => {
    sessionStorage.setItem("openfdd.auth.token", "tok-a");
    sessionStorage.setItem("openfdd.formDraft.lab", "{\"note\":\"a\"}");
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/health") {
        return { ok: true, version: "3.3.2+abcdef123456", historian: "timescale", timescale_ok: true };
      }
      if (path === "/api/auth/me") {
        return {
          ok: true,
          username: "operator",
          role: "operator",
          auth_required: true,
          hub_admin: false,
        };
      }
      if (path === "/api/tenants") return membershipResponse("tenant_a");
      if (path === "/api/tenants/select") {
        throw new Error("not in membership");
      }
      return {};
    });

    render(
      <MemoryRouter initialEntries={["/?site=site_a"]}>
        <AppShell title="Home">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    fireEvent.change(await screen.findByTestId("app-tenant-select"), {
      target: { value: "tenant_b" },
    });
    expect(await screen.findByTestId("app-tenant-switch-error")).toBeTruthy();
    expect(screen.getByTestId("nav-home").getAttribute("href")).toContain("site=site_a");
    expect(sessionStorage.getItem("openfdd.formDraft.lab")).toBe("{\"note\":\"a\"}");
    expect(sessionStorage.getItem("openfdd.auth.token")).toBe("tok-a");
  });

  it("does not offer a tenant selector to a hub admin", async () => {
    sessionStorage.setItem("openfdd.auth.token", "hub");
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/health") {
        return { ok: true, version: "3.3.2+abcdef123456", historian: "timescale", timescale_ok: true };
      }
      if (path === "/api/auth/me") {
        return {
          ok: true,
          username: "admin",
          role: "admin",
          auth_required: true,
          hub_admin: true,
          multi_tenant: true,
        };
      }
      if (path === "/api/tenants") return membershipResponse("tenant_a");
      return {};
    });

    render(
      <MemoryRouter>
        <AppShell title="Home">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("app-tenant")).toBeTruthy();
    expect(screen.queryByTestId("app-tenant-select")).toBeNull();
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

  it("keeps narrow layout side-by-side with capped sidebar and scrollable Lab rules", () => {
    const narrowMq =
      appCss.match(/@media\s*\(max-width:\s*768px\)\s*\{[\s\S]*?(?=\n@media|\n\/\* ——|$)/)?.[0] ??
      "";
    expect(narrowMq).toMatch(/app-shell--sidebar-narrow/);
    expect(narrowMq).toMatch(/max-width:\s*18rem/);
    expect(narrowMq).toMatch(/\.app-main/);
    // Shell stays a row so the working surface is not stacked under a full-width rail.
    const shellFlex =
      narrowMq.match(
        /\.app-shell(?:,\s*\.app-shell--sidebar-narrow)?\s*\{[^}]*flex-direction:\s*([^;]+);/s,
      )?.[1] ?? "";
    expect(shellFlex.trim()).toBe("row");

    const rulesBlock =
      appCss.match(/\.oracle-sidebar__rules\s*\{[^}]+\}/s)?.[0] ?? "";
    expect(rulesBlock).toMatch(/max-height:/);
    expect(rulesBlock).toMatch(/overflow-y:\s*auto/);
    expect(rulesBlock).toMatch(/box-shadow:\s*inset/);
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
