import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { MeteringPage } from "./MeteringPage";

const sessionState = vi.hoisted(() => ({
  siteId: "LAKESIDE_ES" as string | undefined,
}));

vi.mock("../session", () => ({
  useSessionQuery: () => ({
    query: { siteId: sessionState.siteId },
    setQuery: vi.fn(),
  }),
}));

vi.mock("../components/FuelDashboard", () => ({
  FuelDashboard: ({ preferredCampusId }: { preferredCampusId?: string }) => (
    <div
      data-testid="fuel-dashboard"
      data-preferred-campus={preferredCampusId ?? ""}
    >
      FuelDashboard stub
    </div>
  ),
}));

vi.mock("../components/MvChangePointPanel", () => ({
  MvChangePointPanel: () => (
    <div data-testid="mv-change-point-panel">MvChangePointPanel stub</div>
  ),
}));

function renderPage(entry = "/metering") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <MeteringPage />
    </MemoryRouter>,
  );
}

describe("MeteringPage", () => {
  beforeEach(() => {
    sessionState.siteId = "LAKESIDE_ES";
  });

  it("renders package-utilities guidance without fuel ZIP upload", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-page"));
    expect(screen.queryByTestId("metering-fuel-upload")).toBeNull();
    expect(screen.queryByTestId("metering-fuel-zip-input")).toBeNull();
    expect(screen.getByTestId("fuel-dashboard")).toBeTruthy();
    expect(screen.getByTestId("metering-active-site").textContent).toBe(
      "LAKESIDE_ES",
    );
    expect(screen.getByTestId("metering-scope").textContent).toMatch(
      /utilities_v1/,
    );
    expect(
      screen.getByTestId("fuel-dashboard").getAttribute("data-preferred-campus"),
    ).toBe("LAKESIDE_ES");
    expect(screen.getByTestId("metering-section")).toBeTruthy();
  });

  it("still shows Fuel dashboard when no site is locked", async () => {
    sessionState.siteId = undefined;
    renderPage();
    await waitFor(() => screen.getByTestId("metering-page"));
    expect(screen.getByTestId("metering-scope").textContent).toMatch(
      /lock a site first/,
    );
    expect(screen.queryByTestId("metering-active-site")).toBeNull();
  });

  it("switches to M&V radio and hides utilities dashboard", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-page"));
    const mvRadio = screen.getByLabelText("M&V");
    fireEvent.click(mvRadio);
    await waitFor(() => screen.getByTestId("mv-change-point-panel"));
    expect(screen.queryByTestId("fuel-dashboard")).toBeNull();
    expect(screen.queryByTestId("metering-scope")).toBeNull();
  });
});
