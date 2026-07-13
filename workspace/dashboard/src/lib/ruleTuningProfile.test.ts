import { describe, expect, it } from "vitest";
import {
  clearSessionRule,
  clampParam,
  resolveDisplayValue,
  ruleParamsPath,
  setSessionParam,
  type RuleParameterDef,
} from "./ruleTuningProfile";

const baseParam: RuleParameterDef = {
  key: "change_deadband_pct",
  label: "Ignore changes below",
  default: 1.0,
  min: 0,
  max: 10,
  step: 0.5,
  unit: "% output",
  control: "slider",
};

describe("ruleTuningProfile", () => {
  it("preserves canonical rule_id in params path (no slugify)", () => {
    expect(ruleParamsPath("PID-HUNT-1")).toBe("/api/fdd/rules/PID-HUNT-1/params");
    expect(ruleParamsPath("FAN-RUNTIME-HOURS")).toBe("/api/fdd/rules/FAN-RUNTIME-HOURS/params");
  });

  it("does not invent effective when tuning_ok is false", () => {
    const display = resolveDisplayValue(baseParam, undefined, false);
    expect(display.source).toBe("default");
    expect(display.value).toBe(1.0);
  });

  it("uses server effective only when tuning_ok", () => {
    const withEffective: RuleParameterDef = { ...baseParam, effective: 3.5 };
    expect(resolveDisplayValue(withEffective, undefined, true)).toEqual({
      value: 3.5,
      source: "effective",
    });
    // effective present on object but tuning failed — do not treat as effective
    expect(resolveDisplayValue(withEffective, undefined, false).source).toBe("default");
  });

  it("session override wins over effective", () => {
    const withEffective: RuleParameterDef = { ...baseParam, effective: 3.5 };
    expect(resolveDisplayValue(withEffective, 7, true)).toEqual({
      value: 7,
      source: "session",
    });
  });

  it("clamps to min/max", () => {
    expect(clampParam(-1, 0, 10)).toBe(0);
    expect(clampParam(99, 0, 10)).toBe(10);
  });

  it("set/clear session params without mutating other rules", () => {
    let store = setSessionParam({}, "PID-HUNT-1", "change_deadband_pct", 2);
    store = setSessionParam(store, "VAV-1", "zone_t_lo", 68);
    expect(store["PID-HUNT-1"].change_deadband_pct).toBe(2);
    store = clearSessionRule(store, "PID-HUNT-1");
    expect(store["PID-HUNT-1"]).toBeUndefined();
    expect(store["VAV-1"].zone_t_lo).toBe(68);
  });
});
