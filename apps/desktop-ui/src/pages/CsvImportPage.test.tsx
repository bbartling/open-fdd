import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { CsvImportPage } from "./CsvImportPage";

describe("CsvImportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    render(<CsvImportPage />);
    await waitFor(() => {
      expect(screen.getByText("Choose CSV file")).toBeTruthy();
      expect(screen.getByText(/Picker-only mode/)).toBeTruthy();
    });
  });

  it("shows selected file count when picking files", async () => {
    render(<CsvImportPage />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["a,b\n1,2"], "sample.csv", { type: "text/csv" });
    fireEvent.change(fileInput, {
      target: { files: [file] },
    });
    await waitFor(() => {
      expect(screen.getByText("Selected: 1 file(s)")).toBeTruthy();
    });
  });
});
