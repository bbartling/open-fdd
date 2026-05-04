import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { SiteProvider } from "../contexts/site-context";
import { CsvImportPage } from "./CsvImportPage";
import { desktopFetch } from "../lib/api";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    desktopFetch: vi.fn(),
  };
});

const desktopFetchMock = vi.mocked(desktopFetch);

describe("CsvImportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktopFetchMock.mockImplementation(async (path: string) => {
      if (path === "/sites") {
        return [{ id: "s1", name: "Site One" }];
      }
      throw new Error(`unexpected desktopFetch path: ${path}`);
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ rows: 1, dropped_rows: 0, metrics: ["a"] }),
        text: async () => "",
      })) as unknown as typeof fetch,
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders picker-only CSV import controls", async () => {
    render(
      <SiteProvider>
        <CsvImportPage />
      </SiteProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("Choose CSV file(s)")).toBeTruthy();
      expect(screen.getByText(/Picker-only mode/)).toBeTruthy();
      expect(screen.getByTestId("csv-import-drop-zone")).toBeTruthy();
    });
  });

  it("shows selected file count when picking files", async () => {
    render(
      <SiteProvider>
        <CsvImportPage />
      </SiteProvider>,
    );
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["a,b\n1,2"], "sample.csv", { type: "text/csv" });
    fireEvent.change(fileInput, {
      target: { files: [file] },
    });
    await waitFor(() => {
      expect(screen.getByText("Selected: 1 file(s)")).toBeTruthy();
    });
  });

  it("accepts multiple files from the picker and uploads each", async () => {
    const fetchMock = vi.mocked(fetch);
    render(
      <SiteProvider>
        <CsvImportPage />
      </SiteProvider>,
    );
    await waitFor(() => expect(desktopFetchMock).toHaveBeenCalledWith("/sites"));
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const a = new File(["t,m\n1,2"], "a.csv", { type: "text/csv" });
    const b = new File(["t,m\n3,4"], "b.csv", { type: "text/csv" });
    fireEvent.change(fileInput, {
      target: { files: [a, b] },
    });
    await waitFor(() => {
      expect(screen.getByText("Selected: 2 file(s)")).toBeTruthy();
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
  });

  it("accepts multiple CSV files via drop zone", async () => {
    const fetchMock = vi.mocked(fetch);
    render(
      <SiteProvider>
        <CsvImportPage />
      </SiteProvider>,
    );
    await waitFor(() => expect(desktopFetchMock).toHaveBeenCalledWith("/sites"));
    const zone = screen.getByTestId("csv-import-drop-zone");
    const one = new File(["x\n1"], "one.csv", { type: "text/csv" });
    const two = new File(["y\n2"], "two.csv", { type: "text/csv" });
    // jsdom may not define DataTransfer; pass a minimal dataTransfer.files shape the handler reads.
    fireEvent.drop(zone, { dataTransfer: { files: [one, two] } } as never);
    await waitFor(() => {
      expect(screen.getByText("Selected: 2 file(s)")).toBeTruthy();
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
  });
});
