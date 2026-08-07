import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { MeteringPage } from "./MeteringPage";

vi.mock("../api/fuelApi", () => ({
  importFuelCampus: vi.fn(async () => ({
    ok: true,
    campus_id: "campus-100-50",
  })),
}));

vi.mock("../components/FuelDashboard", () => ({
  FuelDashboard: ({ reloadToken }: { reloadToken?: number }) => (
    <div data-testid="fuel-dashboard" data-reload-token={String(reloadToken ?? 0)}>
      FuelDashboard stub
    </div>
  ),
}));

import { importFuelCampus } from "../api/fuelApi";

function renderPage(entry = "/metering") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <MeteringPage />
    </MemoryRouter>,
  );
}

describe("MeteringPage", () => {
  beforeEach(() => {
    vi.mocked(importFuelCampus).mockClear();
  });

  it("renders Fuel dashboard shell and import control", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-page"));
    expect(screen.getByTestId("metering-fuel-upload")).toBeTruthy();
    expect(screen.getByTestId("fuel-dashboard")).toBeTruthy();
    expect(screen.queryByTestId("metering-preset-run")).toBeNull();
    expect(screen.queryByTestId("metering-series")).toBeNull();
  });

  it("imports fuel campus zip and shows campus_id", async () => {
    renderPage();
    await waitFor(() => screen.getByTestId("metering-fuel-zip-input"));

    const file = new File(["zip-bytes"], "Buidling_100_50_fuel_use.zip", {
      type: "application/zip",
    });
    fireEvent.change(screen.getByTestId("metering-fuel-zip-input"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(importFuelCampus).toHaveBeenCalledWith(file);
      expect(screen.getByTestId("metering-fuel-campus-id").textContent).toContain(
        "campus-100-50",
      );
      expect(screen.getByTestId("fuel-dashboard").getAttribute("data-reload-token")).toBe(
        "1",
      );
    });
  });

  it("shows import errors", async () => {
    vi.mocked(importFuelCampus).mockRejectedValueOnce(
      new Error("Fuel campus import failed"),
    );
    renderPage();
    await waitFor(() => screen.getByTestId("metering-fuel-zip-input"));

    const file = new File(["bad"], "bad.zip", { type: "application/zip" });
    fireEvent.change(screen.getByTestId("metering-fuel-zip-input"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByTestId("metering-error").textContent).toContain(
        "Fuel campus import failed",
      );
      expect(screen.queryByTestId("metering-fuel-campus-id")).toBeNull();
    });
  });
});
