import { describe, expect, it } from "vitest";
import { parsePlotSearch } from "./plot-url";

describe("plot-url", () => {
  it("parses site, device, and fdd overlay flag", () => {
    expect(parsePlotSearch("?site=demo&device=bench-1&fdd=1")).toEqual({
      siteId: "demo",
      deviceId: "bench-1",
      autoFddOverlay: true,
    });
  });

  it("accepts overlay alias", () => {
    expect(parsePlotSearch("?overlay=true")).toEqual({ autoFddOverlay: true });
  });
});
