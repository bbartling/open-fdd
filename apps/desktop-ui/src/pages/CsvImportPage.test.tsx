import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { CsvImportPage } from "./CsvImportPage";

vi.mock("../lib/api", () => ({
  desktopFetch: vi.fn(),
}));

import { desktopFetch } from "../lib/api";

describe("CsvImportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    cleanup();
  });

  it("shows ingest results after successful import", async () => {
    vi.mocked(desktopFetch).mockResolvedValue({
      rows: 10,
      dropped_rows: 2,
      metrics: ["sa_temp", "oa_temp"],
    });
    render(<CsvImportPage />);
    fireEvent.change(screen.getByPlaceholderText("Path to CSV file"), {
      target: { value: "C:/data/office.csv" },
    });
    fireEvent.click(screen.getByText("Import CSV"));
    await waitFor(() => {
      expect(screen.getByDisplayValue(/Rows: 10/)).toBeTruthy();
      expect(screen.getByDisplayValue(/Dropped: 2/)).toBeTruthy();
      expect(screen.getByDisplayValue(/sa_temp/)).toBeTruthy();
    });
  });

  it("shows backend errors in output area", async () => {
    vi.mocked(desktopFetch).mockRejectedValue(new Error("Bridge error 400: CSV file not found"));
    render(<CsvImportPage />);
    fireEvent.change(screen.getByPlaceholderText("Path to CSV file"), {
      target: { value: "C:/bad/path.csv" },
    });
    fireEvent.click(screen.getByText("Import CSV"));
    await waitFor(() => {
      expect(screen.getByDisplayValue(/CSV file not found/)).toBeTruthy();
    });
  });
});
