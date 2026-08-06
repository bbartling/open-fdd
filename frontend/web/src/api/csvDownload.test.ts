import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { downloadRowsCsv, escapeCsvCell } from "./csvDownload";

describe("escapeCsvCell", () => {
  it("prefixes formula-like cells to avoid spreadsheet injection", () => {
    expect(escapeCsvCell("=1+2")).toBe("'=1+2");
    expect(escapeCsvCell("@cmd")).toBe("'@cmd");
    expect(escapeCsvCell("+1")).toBe("'+1");
    expect(escapeCsvCell("-1")).toBe("'-1");
  });

  it("quotes commas and preserves normal values", () => {
    expect(escapeCsvCell("x,y")).toBe('"x,y"');
    expect(escapeCsvCell(1)).toBe("1");
  });
});

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
