import { describe, expect, it } from "vitest";
import { MAIN_SECTIONS } from "./sections";

/** Product main sections — Streamlit oracle set plus Actions (backend run log). */
const ORACLE_MAIN_SECTIONS = [
  "Overview",
  "Data Model",
  "Run Rules",
  "Actions",
  "Results by Category",
  "FDD Plots",
  "RCx Plots",
  "Metering",
  "WattLab",
] as const;

describe("MAIN_SECTIONS Streamlit contract", () => {
  it("matches REQUIRED_MAIN_SECTIONS labels and order", () => {
    expect(MAIN_SECTIONS.map((s) => s.label)).toEqual([...ORACLE_MAIN_SECTIONS]);
  });

  it("has unique ids and paths", () => {
    const ids = MAIN_SECTIONS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(MAIN_SECTIONS.every((s) => s.path.length > 0)).toBe(true);
  });
});
