import { describe, expect, it } from "vitest";
import {
  canMutateSources,
  healthTone,
  SOURCES_PANEL_TITLE,
} from "./sources";

describe("sources UI helpers", () => {
  it("uses Data Connectors panel title", () => {
    expect(SOURCES_PANEL_TITLE).toBe("Data Connectors");
  });

  it("maps health status to UI tone", () => {
    expect(healthTone("online")).toBe("ok");
    expect(healthTone("degraded")).toBe("warn");
    expect(healthTone("offline")).toBe("bad");
  });

  it("allows integrator and agent to mutate sources", () => {
    expect(canMutateSources("integrator")).toBe(true);
    expect(canMutateSources("operator")).toBe(false);
  });
});
