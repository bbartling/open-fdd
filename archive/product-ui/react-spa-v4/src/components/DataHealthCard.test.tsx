import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { DataHealthCard } from "./DataHealthCard";

vi.mock("../api/historianApi", () => ({
  getHistorianOrphans: vi.fn(),
}));

import { getHistorianOrphans } from "../api/historianApi";

function renderCard() {
  return render(
    <MemoryRouter>
      <DataHealthCard buildingId="SITE A" />
    </MemoryRouter>,
  );
}

describe("DataHealthCard", () => {
  beforeEach(() => {
    vi.mocked(getHistorianOrphans).mockReset();
  });

  it("warns with the orphan count and equipment and links to Jobs", async () => {
    vi.mocked(getHistorianOrphans).mockResolvedValue({
      ok: true,
      building_id: "SITE A",
      historian: "timescale",
      orphaned_points: 3,
      equipment: ["VAV_1", "VAV_2"],
      points: [],
    });
    renderCard();

    const card = await screen.findByTestId("overview-data-health");
    expect(card.className).toContain("widget-inline-alert--warning");
    const summary = screen.getByTestId("overview-data-health-summary").textContent ?? "";
    expect(summary).toContain("3 historian series are no longer in the building model");
    expect(summary).toContain("VAV_1, VAV_2");
    expect(screen.getByTestId("overview-data-health-jobs-link").getAttribute("href")).toBe(
      "/jobs?site=SITE%20A",
    );
    expect(getHistorianOrphans).toHaveBeenCalledWith("SITE A", expect.anything());
  });

  it("renders nothing when no series are orphaned", async () => {
    vi.mocked(getHistorianOrphans).mockResolvedValue({
      ok: true,
      building_id: "SITE A",
      orphaned_points: 0,
      equipment: [],
      points: [],
    });
    renderCard();

    await waitFor(() => expect(getHistorianOrphans).toHaveBeenCalled());
    expect(screen.queryByTestId("overview-data-health")).toBeNull();
  });

  it("renders nothing when the orphan query fails", async () => {
    vi.mocked(getHistorianOrphans).mockRejectedValue(new Error("down"));
    renderCard();

    await waitFor(() => expect(getHistorianOrphans).toHaveBeenCalled());
    expect(screen.queryByTestId("overview-data-health")).toBeNull();
  });
});
