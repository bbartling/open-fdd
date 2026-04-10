import { describe, expect, it } from "vitest";
import { isHotReloadBenchArtifact } from "./rule-files";

describe("isHotReloadBenchArtifact", () => {
  it("returns false for normal rule files", () => {
    expect(isHotReloadBenchArtifact("sensor_bounds.yaml")).toBe(false);
    expect(isHotReloadBenchArtifact("sensor_flatline.yaml")).toBe(false);
    expect(isHotReloadBenchArtifact("my_rule.yaml")).toBe(false);
  });

  it("returns true for 4_hot_reload_test.py timestamp copies", () => {
    expect(isHotReloadBenchArtifact("test_sensor_bounds_1774812747.yaml")).toBe(true);
    expect(isHotReloadBenchArtifact("test_sensor_flatline_1774979285.yaml")).toBe(true);
  });

  it("returns false when suffix is not a long numeric run (avoid false positives)", () => {
    expect(isHotReloadBenchArtifact("test_rule.yaml")).toBe(false);
    expect(isHotReloadBenchArtifact("test_foo_123.yaml")).toBe(false);
    expect(isHotReloadBenchArtifact("hot_reload_test.yaml")).toBe(false);
  });
});
