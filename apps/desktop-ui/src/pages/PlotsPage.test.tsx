import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SiteProvider } from "../contexts/site-context";
import { PlotsPage } from "./PlotsPage";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    desktopFetch: vi.fn(),
  };
});

import { desktopFetch } from "../lib/api";

const desktopFetchMock = vi.mocked(desktopFetch);

function renderPlots(search = "?site_id=s1&runSource=csv") {
  return render(
    <MemoryRouter initialEntries={[`/plots${search}`]}>
      <SiteProvider>
        <Routes>
          <Route path="/plots" element={<PlotsPage />} />
        </Routes>
      </SiteProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  desktopFetchMock.mockReset();
  desktopFetchMock.mockImplementation(async (path: string) => {
    if (path === "/sites") {
      return [{ id: "s1", name: "Site One" }];
    }
    if (path === "/model/export") {
      return { points: [], equipment: [] };
    }
    if (path === "/rules") {
      return { files: [], rules_dir: "/tmp" };
    }
    if (path === "/timeseries/bounds") {
      return { start: "2020-01-01", end: "2020-01-02" };
    }
    throw new Error(`unexpected desktopFetch path: ${path}`);
  });
});

describe("PlotsPage", () => {
  it("preview string-metric fix posts clean-metrics with site and source", async () => {
    desktopFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/sites") {
        return [{ id: "s1", name: "Site One" }];
      }
      if (path === "/model/export") {
        return { points: [], equipment: [] };
      }
      if (path === "/rules") {
        return { files: [], rules_dir: "/tmp" };
      }
      if (path === "/timeseries/bounds") {
        return { start: "2020-01-01", end: "2020-01-02" };
      }
      if (path === "/timeseries/clean-metrics") {
        expect(init?.method).toBe("POST");
        const body = JSON.parse(String(init?.body ?? "{}"));
        expect(body.commit).toBe(false);
        expect(body.site_id).toBe("s1");
        expect(body.source).toBe("csv");
        return { ok: true, committed: false, applied_columns: ["ColA"], row_count: 10 };
      }
      throw new Error(`unexpected path ${path}`);
    });

    renderPlots();
    await waitFor(() => {
      expect(screen.getByTestId("plots-clean-metrics-panel")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Preview string-metric fix/i }));
    expect(await screen.findByText(/Preview OK/i)).toBeInTheDocument();
    expect(screen.getByText(/ColA/)).toBeInTheDocument();
  });
});
