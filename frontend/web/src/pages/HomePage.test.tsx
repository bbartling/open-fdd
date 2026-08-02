import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { HomePage } from "./HomePage";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["B1"]),
}));

vi.mock("../api/analyticsApi", () => ({
  listFddEquipment: vi.fn(async () => [
    { equipment_id: "AHU_1", equipment_type: "AHU" },
    { equipment_id: "VAV_1", equipment_type: "VAV" },
  ]),
}));

vi.mock("../api/cutoverApi", () => ({
  getUiGeneration: vi.fn(async () => ({ generation: "react" })),
}));

import { apiFetch } from "../api/client";
import { listPackageBuildings } from "../api/mappingApi";
import { listFddEquipment } from "../api/analyticsApi";

describe("HomePage overview", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      contract: { contract_version: "1.0.0-test" },
      capabilities: { react_ui: true },
    });
    vi.mocked(listPackageBuildings).mockClear();
    vi.mocked(listFddEquipment).mockClear();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it("shows equipment inventory metrics when authenticated", async () => {
    sessionStorage.setItem("openfdd.auth.token", "test-token");
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("overview-eq-count").textContent).toContain("2");
      expect(screen.getByTestId("overview-equipment")).toBeTruthy();
      expect(screen.getByTestId("contract-version").textContent).toContain(
        "1.0.0-test",
      );
    });
    expect(listPackageBuildings).toHaveBeenCalled();
    expect(listFddEquipment).toHaveBeenCalled();
  });

  it("skips JWT-gated inventory fetches when anonymous", async () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("contract-version").textContent).toContain(
        "1.0.0-test",
      );
    });
    expect(listPackageBuildings).not.toHaveBeenCalled();
    expect(listFddEquipment).not.toHaveBeenCalled();
    expect(screen.getByTestId("overview-eq-count").textContent).toContain("0");
  });
});
