import { describe, expect, it, vi, beforeEach } from "vitest";
import { desktopFetch } from "./api";

describe("desktopFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns parsed JSON for successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok" }),
      }),
    );
    const out = await desktopFetch<{ status: string }>("/health");
    expect(out.status).toBe("ok");
  });

  it("throws meaningful error for offline bridge", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    await expect(desktopFetch("/health")).rejects.toThrow(/Bridge may be offline/i);
  });

  it("throws backend error details for non-200 responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: async () => "CSV file not found",
      }),
    );
    await expect(desktopFetch("/ingest/csv", { method: "POST" })).rejects.toThrow(
      /Bridge error 400: CSV file not found/,
    );
  });
});
