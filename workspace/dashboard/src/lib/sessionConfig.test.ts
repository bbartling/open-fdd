import { describe, expect, it } from "vitest";
import {
  buildSessionConfig,
  parseSessionConfigFile,
  sessionConfigToParamOverrides,
} from "./sessionConfig";

describe("sessionConfigToParamOverrides", () => {
  it("keeps only finite numeric params", () => {
    const out = sessionConfigToParamOverrides({
      schema_version: "openfdd_session_v1",
      unit_system: "imperial",
      params: {
        FC1: { eps_dsp: 0.2, bad: NaN },
        EMPTY: {},
      },
    });
    expect(out).toEqual({ FC1: { eps_dsp: 0.2 } });
  });

  it("handles missing config", () => {
    expect(sessionConfigToParamOverrides(null)).toEqual({});
  });
});

describe("buildSessionConfig", () => {
  it("exports slider state with unit system, dropping empty rules", () => {
    const cfg = buildSessionConfig({ FC1: { eps_dsp: 0.15 }, FC2: {} }, "metric");
    expect(cfg.schema_version).toBe("openfdd_session_v1");
    expect(cfg.unit_system).toBe("metric");
    expect(cfg.params).toEqual({ FC1: { eps_dsp: 0.15 } });
  });

  it("preserves base fields like role_map", () => {
    const cfg = buildSessionConfig({}, "imperial", {
      schema_version: "openfdd_session_v1",
      unit_system: "imperial",
      role_map: { AHU_1: { fan_status: "sf_status" } },
    });
    expect(cfg.role_map).toEqual({ AHU_1: { fan_status: "sf_status" } });
  });
});

describe("parseSessionConfigFile", () => {
  it("accepts valid config and fills defaults", () => {
    const cfg = parseSessionConfigFile(
      JSON.stringify({ unit_system: "metric", params: { FC1: { eps_dsp: 0.1 } } }),
    );
    expect(cfg.schema_version).toBe("openfdd_session_v1");
    expect(cfg.unit_system).toBe("metric");
  });

  it("rejects wrong schema_version", () => {
    expect(() =>
      parseSessionConfigFile(JSON.stringify({ schema_version: "v2" })),
    ).toThrow(/schema_version/);
  });

  it("rejects non-objects", () => {
    expect(() => parseSessionConfigFile("42")).toThrow(/object/);
  });
});
