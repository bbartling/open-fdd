import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { SitesPanel } from "../components/SitesPanel";

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => ["ZIP_BUILDING_1", "BUILDING_50"]),
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: { schema_version: "openfdd_session_v1", params: {} },
  })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/datasetsApi", () => ({
  deleteDataset: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async () => ({ ok: true, edges: [] })),
}));

vi.mock("../api/providersApi", async () => {
  const actual = await vi.importActual<typeof import("../api/providersApi")>(
    "../api/providersApi",
  );
  return {
    ...actual,
    fetchProviderSites: vi.fn(async () => ({ ok: true, sites: [] })),
  };
});

import { listPackageBuildings } from "../api/mappingApi";
import { deleteDataset } from "../api/datasetsApi";
import { fetchProviderSites } from "../api/providersApi";

function renderSites(entry = "/operations?view=sites&site=ZIP_BUILDING_1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <SitesPanel />
    </MemoryRouter>,
  );
}

describe("Operations Sites panel", () => {
  beforeEach(() => {
    vi.mocked(listPackageBuildings).mockClear();
    vi.mocked(deleteDataset).mockClear();
    vi.mocked(listPackageBuildings).mockResolvedValue([
      "ZIP_BUILDING_1",
      "BUILDING_50",
    ]);
    vi.mocked(deleteDataset).mockResolvedValue({ ok: true });
    vi.mocked(fetchProviderSites).mockResolvedValue({ ok: true, sites: [] });
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
    renderSites("/operations?view=sites&site=ZIP_BUILDING_1");
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
    await waitFor(() => {
      expect(screen.getByTestId("sites-active-BUILDING_50").textContent).toMatch(
        /yes/,
      );
      expect(screen.getByTestId("sites-active-ZIP_BUILDING_1").textContent).toMatch(
        /—/,
      );
    });
  });

  it("deletes a site via confirm modal", async () => {
    vi.mocked(deleteDataset).mockImplementation(async (id) => {
      expect(id).toBe("ZIP_BUILDING_1");
      vi.mocked(listPackageBuildings).mockResolvedValue(["BUILDING_50"]);
      return { ok: true };
    });
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
    await waitFor(() => {
      expect(screen.queryByTestId("sites-row-ZIP_BUILDING_1")).toBeNull();
      expect(screen.getByTestId("sites-row-BUILDING_50")).toBeTruthy();
      expect(screen.getByTestId("sites-active-BUILDING_50").textContent).toMatch(
        /yes/,
      );
    });
  });

  it("auto-selects the sole visible site when none is active", async () => {
    vi.mocked(listPackageBuildings).mockResolvedValue(["BUILDING_50"]);
    renderSites("/operations?view=sites");
    await waitFor(() => {
      expect(screen.getByTestId("sites-active-hint").textContent).toMatch(
        /Active site:\s*BUILDING_50/,
      );
    });
    expect(screen.getByTestId("sites-active-BUILDING_50").textContent).toMatch(
      /yes/,
    );
  });

  it("shows a calm empty notice instead of building_id required", async () => {
    vi.mocked(listPackageBuildings).mockRejectedValue(
      new Error('{"error":"building_id required"}'),
    );
    renderSites("/operations?view=sites");
    await waitFor(() => {
      expect(screen.getByTestId("sites-notice").textContent).toMatch(
        /No sites loaded yet/,
      );
    });
    expect(screen.queryByTestId("sites-error")).toBeNull();
    expect(screen.queryByText(/building_id required/i)).toBeNull();
  });

  it("discovers a portal site with no CSV package and no ingest control", async () => {
    vi.mocked(listPackageBuildings).mockResolvedValue([]);
    vi.mocked(fetchProviderSites).mockResolvedValue({
      ok: true,
      sites: [
        {
          building_id: "NF_EDGE",
          provider: "nf",
          endpoint: "https://user:secret@portal.example/api?token=abc",
          mapped_points: 5,
          client_id_configured: true,
        },
      ],
    });
    renderSites("/operations?view=sites");
    await waitFor(() => {
      expect(screen.getByTestId("sites-row-NF_EDGE")).toBeTruthy();
    });
    expect(screen.getByTestId("sites-sources-NF_EDGE").textContent).toMatch(/NF/);
    expect(screen.getByTestId("sites-sources-NF_EDGE").textContent).not.toMatch(/secret/);
    expect(screen.queryByLabelText(/Ingest mode/i)).toBeNull();
    expect(screen.getByTestId("sites-active-hint").textContent).toMatch(/NF_EDGE/);
    const del = screen.getByTestId("sites-delete-NF_EDGE").querySelector("button");
    expect(del?.hasAttribute("disabled") || del?.getAttribute("aria-disabled") === "true").toBe(
      true,
    );
  });
});
