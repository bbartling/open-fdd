import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { OracleSidebar } from "./OracleSidebar";
import { getAuthMe } from "../api/authApi";
import { listPackageBuildings } from "../api/mappingApi";
import { TENANT_CHANGED_EVENT } from "../api/tenantApi";

vi.mock("../api/authApi", () => ({
  getAuthMe: vi.fn(),
}));

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["SITE_A"]),
}));

vi.mock("../api/providersApi", () => ({
  listProviderBuildingIds: vi.fn(async () => []),
}));

vi.mock("../api/uploadApi", () => ({
  uploadPackage: vi.fn(),
}));

vi.mock("./RuleTuningPanel", () => ({
  RuleTuningPanel: () => <div data-testid="rule-tuning-stub" />,
}));

function renderSidebar() {
  return render(
    <MemoryRouter>
      <OracleSidebar collapsed={false} />
    </MemoryRouter>,
  );
}

describe("sidebar package load", () => {
  beforeEach(() => {
    vi.mocked(getAuthMe).mockReset();
  });

  it("shows load package for an operator and an admin", async () => {
    for (const role of ["operator", "admin"] as const) {
      vi.mocked(getAuthMe).mockResolvedValue({
        ok: true,
        username: role,
        role,
        auth_required: true,
      });
      const view = renderSidebar();
      await waitFor(() => {
        expect(screen.getByTestId("sidebar-load-zips")).toBeTruthy();
      });
      expect(screen.getByTestId("sidebar-zip-input")).toBeTruthy();
      view.unmount();
    }
  });

  it("hides load package for a viewer", async () => {
    vi.mocked(getAuthMe).mockResolvedValue({
      ok: true,
      username: "viewer-1",
      role: "viewer",
      auth_required: true,
    });
    renderSidebar();
    await waitFor(() => {
      expect(getAuthMe).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("sidebar-load-zips")).toBeNull();
    expect(screen.queryByTestId("sidebar-zip-input")).toBeNull();
    expect(screen.queryByTestId("sidebar-building-data")).toBeNull();
  });

  it("reloads sites when the active tenant changes", async () => {
    vi.mocked(getAuthMe).mockResolvedValue({
      ok: true,
      username: "operator",
      role: "operator",
      auth_required: true,
    });
    renderSidebar();
    await waitFor(() => {
      expect(listPackageBuildings).toHaveBeenCalled();
    });
    const before = vi.mocked(listPackageBuildings).mock.calls.length;
    window.dispatchEvent(new Event(TENANT_CHANGED_EVENT));
    await waitFor(() => {
      expect(vi.mocked(listPackageBuildings).mock.calls.length).toBeGreaterThan(before);
    });
  });
});
