import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  displayScalar,
  displayUnitLabel,
  resolveQuantityKind,
  storeScalar,
} from "./role-units.js";

describe("role-units tuner scalars", () => {
  it("resolves temperature delta from param key", () => {
    assert.equal(resolveQuantityKind("degF", "eps_mat"), "temperature_delta");
  });

  it("displayScalar and storeScalar invert for SI storage", () => {
    const stored = 5;
    const shown = displayScalar(stored, "degF", "metric", undefined, "eps_mat");
    const back = storeScalar(shown, "degF", "metric", undefined, "eps_mat");
    assert.ok(Math.abs(back - stored) < 1e-6);
  });

  it("displayUnitLabel prefers metric delta label", () => {
    assert.equal(displayUnitLabel("degF", "metric", undefined, "eps_mat"), "Δ°C");
  });
});
