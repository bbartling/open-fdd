import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { SitesPage } from "./SitesPage";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["ZIP_BUILDING_1", "BUILDING_50"]),
}));

vi.mock("../api/datasetsApi", () => ({
  deleteDataset: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

import { listPackageBuildings } from "../api/mappingApi";
import { deleteDataset } from "../api/datasetsApi";

function renderSites(entry = "/sites?site=ZIP_BUILDING_1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <SitesPage />
    </MemoryRouter>,
  );
}

describe("SitesPage", () => {
  beforeEach(() => {
    vi.mocked(listPackageBuildings).mockClear();
    vi.mocked(deleteDataset).mockClear();
    vi.mocked(listPackageBuildings).mockResolvedValue([
      "ZIP_BUILDING_1",
      "BUILDING_50",
    ]);
    vi.mocked(deleteDataset).mockResolvedValue({ ok: true });
  });

  it("lists loaded sites and marks active", async () => {
    renderSites();
    await waitFor(() => {
      expect(screen.getByTestId("sites-table")).toBeTruthy();
    });
    expect(screen.getByTestId("sites-active-ZIP_BUILDING_1").textContent).toMatch(
      /yes/,
    );
    expect(screen.getByTestId("sites-active-BUILDING_50").textContent).toMatch(/—/);
  });

  it("sets active site", async () => {
    renderSites("/sites?site=ZIP_BUILDING_1");
    await waitFor(() => {
      expect(screen.getByTestId("sites-set-active-BUILDING_50")).toBeTruthy();
    });
    const btn = screen
      .getByTestId("sites-set-active-BUILDING_50")
      .querySelector("button");
    expect(btn).toBeTruthy();
    fireEvent.click(btn!);
    await waitFor(() => {
      expect(screen.getByTestId("sites-notice").textContent).toMatch(
        /BUILDING_50/,
      );
    });
  });

  it("deletes a site via confirm modal", async () => {
    renderSites();
    await waitFor(() => {
      expect(screen.getByTestId("sites-delete-ZIP_BUILDING_1")).toBeTruthy();
    });
    const del = screen
      .getByTestId("sites-delete-ZIP_BUILDING_1")
      .querySelector("button");
    fireEvent.click(del!);
    await waitFor(() => {
      expect(screen.getByTestId("sites-delete-modal")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("sites-delete-modal-confirm"));
    await waitFor(() => {
      expect(deleteDataset).toHaveBeenCalledWith("ZIP_BUILDING_1");
    });
    await waitFor(() => {
      expect(screen.getByTestId("sites-notice").textContent).toMatch(
        /Deleted site/,
      );
    });
  });
});
