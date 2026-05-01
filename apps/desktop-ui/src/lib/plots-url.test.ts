import { describe, expect, it } from "vitest";
import { buildPlotsSearch, parsePlotsSearch } from "./plots-url";

describe("parsePlotsSearch", () => {
  it("parses fdd overlay and skip-missing defaults", () => {
    const a = parsePlotsSearch("?fdd=1&site_id=abc-123&runSource=csv");
    expect(a.autoFddOverlay).toBe(true);
    expect(a.siteId).toBe("abc-123");
    expect(a.runSource).toBe("csv");
    expect(a.skipMissingRules).toBe(true);
  });

  it("honors skipMissing=0", () => {
    const a = parsePlotsSearch("?skipMissing=0");
    expect(a.skipMissingRules).toBe(false);
  });
});

describe("buildPlotsSearch", () => {
  it("round-trips key flags", () => {
    const q = buildPlotsSearch({
      siteId: "s1",
      autoFddOverlay: true,
      skipMissingRules: true,
      runSource: "csv",
    });
    const p = new URLSearchParams(q.startsWith("?") ? q.slice(1) : q);
    expect(p.get("fdd")).toBe("1");
    expect(p.get("site_id")).toBe("s1");
    expect(p.get("skipMissing")).toBe("1");
    expect(p.get("runSource")).toBe("csv");
  });
});
