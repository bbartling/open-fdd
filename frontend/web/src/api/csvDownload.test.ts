import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { downloadRowsCsv } from "./csvDownload";

describe("downloadRowsCsv", () => {
  const origCreate = URL.createObjectURL;
  const origRevoke = URL.revokeObjectURL;

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:test") as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
    vi.restoreAllMocks();
  });

  it("writes a CSV blob and triggers download", () => {
    const click = vi.fn();
    const createEl = vi
      .spyOn(document, "createElement")
      .mockImplementation((tag: string) => {
        if (tag === "a") {
          return { click, href: "", download: "" } as unknown as HTMLAnchorElement;
        }
        return document.createElement(tag);
      });
    downloadRowsCsv("x.csv", [{ a: 1, b: "x,y" }]);
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    createEl.mockRestore();
  });
});
