import { describe, expect, it } from "vitest";
import { MAIN_SECTIONS } from "./sections";

/** Product main sections — H9 adds Operations after Sites; Run Rules remains on Overview + left rail. */
const ORACLE_MAIN_SECTIONS = [
  "Overview",
  "Inspect",
  "Data Model",
  "Actions",
  "Results by Category",
  "FDD Plots",
  "RCx Plots",
  "Metering",
  "WattLab",
  "Sites",
  "Operations",
] as const;

describe("MAIN_SECTIONS navigation contract", () => {
  it("matches REQUIRED_MAIN_SECTIONS labels and order", () => {
    expect(MAIN_SECTIONS.map((s) => s.label)).toEqual([...ORACLE_MAIN_SECTIONS]);
  });

  it("has unique ids and paths", () => {
    const ids = MAIN_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(MAIN_SECTIONS.every((s) => s.path.length > 0)).toBe(true);
  });
});
