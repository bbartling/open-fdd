import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { FddRuleSummary } from "../api/fddApi";
import { getFddRuleParams, listFddRules, runFdd } from "../api/fddApi";
import { getSessionConfig, putSessionConfig } from "../api/mappingApi";
import { OPERATIONAL_GATE_KEY, ruleNeedsRun } from "../lib/ruleParams";
import {
  RULES_UPDATED_EVENT,
  RuleTuningPanel,
  defaultLabFamily,
  visibleRulesForLab,
} from "./RuleTuningPanel";

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(),
  getFddRuleParams: vi.fn(),
  runFdd: vi.fn(),
}));

vi.mock("../api/mappingApi", () => ({
  getSessionConfig: vi.fn(),
  putSessionConfig: vi.fn(),
}));

function rule(rule_id: string): FddRuleSummary {
  return {
    rule_id,
    description: rule_id,
    equipment_kinds: ["ahu"],
    required_roles: [],
    optional_roles: [],
  };
}

describe("visibleRulesForLab", () => {
  it("sorts rule_id A–Z for Lab UX (not registry YAML order)", () => {
    const rules = [rule("VAV-1"), rule("FC1"), rule("PID-HUNT-1"), rule("AHU-FC2")];
    expect(visibleRulesForLab(rules, "(all)").map((r) => r.rule_id)).toEqual([
      "AHU-FC2",
      "FC1",
      "PID-HUNT-1",
      "VAV-1",
    ]);
  });

  it("natural-sorts FC1→FC2→…→FC10 (registry YAML order must not win)", () => {
    const rules = [
      rule("FC10"),
      rule("FC2"),
      rule("FC1"),
      rule("FC9"),
      rule("ECON-1"),
    ];
    expect(visibleRulesForLab(rules, "(all)").map((r) => r.rule_id)).toEqual([
      "ECON-1",
      "FC1",
      "FC2",
      "FC9",
      "FC10",
    ]);
  });

  it("filters by family then natural-sorts", () => {
    const rules = [rule("SV-STALE"), rule("FC1"), rule("SV-FLATLINE"), rule("SV-10")];
    expect(visibleRulesForLab(rules, "SV").map((r) => r.rule_id)).toEqual([
      "SV-10",
      "SV-FLATLINE",
      "SV-STALE",
    ]);
  });
});

describe("defaultLabFamily", () => {
  it("prefers FC over dumping (all) when present", () => {
    expect(
      defaultLabFamily([rule("VAV-1"), rule("FC1"), rule("AHU-FC2")]),
    ).toBe("FC");
  });

  it("falls back along preference then first sorted family", () => {
    expect(defaultLabFamily([rule("VAV-1"), rule("SV-STALE")])).toBe("VAV");
    expect(defaultLabFamily([rule("SV-STALE"), rule("PID-HUNT-1")])).toBe(
      "SV",
    );
    expect(defaultLabFamily([rule("PID-HUNT-1"), rule("UTIL-MONTHLY")])).toBe(
      "PID",
    );
  });

  it("treats a default-valued draft as pending when the last run differed", () => {
    const entries: Array<[string, { default: number }]> = [
      ["confirm_min", { default: 5 }],
      [OPERATIONAL_GATE_KEY, { default: 1 }],
    ];
    expect(ruleNeedsRun(entries, { confirm_min: 5 }, { confirm_min: 20 }, true)).toBe(true);
    expect(ruleNeedsRun(entries, { confirm_min: 5 }, { confirm_min: 5 }, true)).toBe(false);
    expect(ruleNeedsRun(entries, {}, { [OPERATIONAL_GATE_KEY]: 1 }, false)).toBe(true);
    expect(ruleNeedsRun(entries, {}, { [OPERATIONAL_GATE_KEY]: 0 }, false)).toBe(false);
  });

  it("groups FC1/FC10 under family FC for Lab category", () => {
    expect(
      visibleRulesForLab(
        [rule("FC10"), rule("VAV-1"), rule("FC2")],
        "FC",
      ).map((r) => r.rule_id),
    ).toEqual(["FC2", "FC10"]);
  });
});

describe("T1284-5 unsupported tuner honesty", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(listFddRules).mockResolvedValue([
      { rule_id: "SV-RATE", description: "Sensor rate", equipment_kinds: ["ahu"] },
    ]);
    vi.mocked(getFddRuleParams).mockResolvedValue({
      ok: true,
      rule_id: "SV-RATE",
      params: {
        sensor_span: {
          key: "sensor_span",
          label: "Sensor span",
          default: 100,
          min: 1,
          max: 500,
          step: 1,
          unit: "unit",
          control: "slider",
          sql_placeholder: "SENSOR_SPAN",
          effect: "unsupported",
          effect_reason: "This control is not supported for this rule yet.",
        },
      },
    });
    vi.mocked(getSessionConfig).mockResolvedValue({
      ok: true,
      config: { schema_version: "openfdd_session_v1", params: {} },
    });
  });

  it("disables unsupported tuners with a reason", async () => {
    render(
      <MemoryRouter initialEntries={["/?site=lab-fixture"]}>
        <RuleTuningPanel />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("rule-tune-SV-RATE")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("rule-tune-SV-RATE").querySelector("summary")!);
    const slider = await screen.findByTestId("tune-slider-sensor_span");
    expect((slider as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByTestId("tune-disabled-sensor_span").textContent).toMatch(
      /not supported/i,
    );
  });
});

const FC1_PARAMS = {
  confirm_min: {
    key: "confirm_min",
    label: "Fault confirm delay",
    default: 5,
    min: 0,
    max: 60,
    step: 1,
    unit: "min",
    quantity: "minutes",
    control: "slider",
    sql_placeholder: "CONFIRM_SECONDS",
  },
  eps_dsp: {
    key: "eps_dsp",
    label: "Duct-static error",
    default: 0.12,
    min: 0,
    max: 0.5,
    step: 0.01,
    unit: "inwc",
    quantity: "pressure",
    control: "slider",
    sql_placeholder: "EPS_DSP",
  },
  eps_vfd_spd: {
    key: "eps_vfd_spd",
    label: "VFD speed error",
    default: 0.13,
    min: 0,
    max: 0.5,
    step: 0.01,
    unit: "frac",
    quantity: "fraction",
    control: "slider",
    sql_placeholder: "EPS_VFD_SPD",
  },
  zone_t_lo: {
    key: "zone_t_lo",
    label: "Zone low",
    default: 70,
    min: 55,
    max: 85,
    step: 0.5,
    unit: "degF",
    quantity: "temperature",
    control: "slider",
    sql_placeholder: "ZONE_T_LO",
  },
  eps_mat: {
    key: "eps_mat",
    label: "MAT sensor eps",
    default: 1.15,
    min: 0,
    max: 10,
    step: 0.25,
    unit: "degF",
    quantity: "temperature_delta",
    control: "slider",
    sql_placeholder: "EPS_MAT",
  },
  require_operational_gate: {
    key: "require_operational_gate",
    label: "Require operational gate",
    default: 1,
    min: 0,
    max: 1,
    step: 1,
    unit: "bool",
    quantity: "boolean",
    control: "slider",
    sql_placeholder: "REQUIRE_OPERATIONAL_GATE",
  },
};

function renderTuner() {
  return render(
    <MemoryRouter initialEntries={["/?site=lab-fixture"]}>
      <RuleTuningPanel />
    </MemoryRouter>,
  );
}

async function openFc1() {
  const summary = await screen.findByText(/FC1 —/);
  fireEvent.click(summary);
  await waitFor(() => {
    expect(screen.getByTestId("tune-slider-confirm_min")).toBeTruthy();
  });
}

describe("tuner apply, default, reset, and failed save", () => {
  let failSave = false;
  const updated: unknown[] = [];
  let onUpdated: ((event: Event) => void) | null = null;

  beforeEach(() => {
    failSave = false;
    updated.length = 0;
    localStorage.clear();
    onUpdated = (event: Event) => {
      updated.push((event as CustomEvent).detail);
    };
    window.addEventListener(RULES_UPDATED_EVENT, onUpdated);
    vi.mocked(listFddRules).mockResolvedValue([
      { rule_id: "FC1", description: "Duct static below SP at full fan", equipment_kinds: ["ahu"] },
    ]);
    vi.mocked(getFddRuleParams).mockResolvedValue({
      ok: true,
      rule_id: "FC1",
      params: FC1_PARAMS,
    });
    vi.mocked(getSessionConfig).mockResolvedValue({
      ok: true,
      config: { schema_version: "openfdd_session_v1", params: {} },
    });
    vi.mocked(putSessionConfig).mockImplementation(async () => {
      if (failSave) throw new Error("session store unavailable");
      return { ok: true, config: { schema_version: "openfdd_session_v1" } };
    });
    vi.mocked(runFdd).mockResolvedValue({
      ok: true,
      results: [{ rule_id: "FC1", equipment_id: "AHU_1", status: "PASS" }],
      total_ms: 12,
    });
  });

  afterEach(() => {
    if (onUpdated) window.removeEventListener(RULES_UPDATED_EVENT, onUpdated);
    updated.length = 0;
  });

  it("labels quantities and runs apply → default → reset → failed save", async () => {
    renderTuner();
    await openFc1();

    expect(screen.getByTestId("tune-label-eps_dsp").textContent).toContain("in. w.c.");
    expect(screen.getByTestId("tune-label-eps_dsp").textContent).not.toContain("Δ°");
    expect(screen.getByTestId("tune-label-eps_vfd_spd").textContent).toContain("(frac)");
    expect(screen.getByTestId("tune-label-eps_vfd_spd").textContent).not.toContain("%");
    expect(screen.getByTestId("tune-label-confirm_min").textContent).toContain("(min)");
    expect(screen.getByTestId("tune-label-zone_t_lo").textContent).toContain("(°F)");
    expect(screen.getByTestId("tune-label-eps_mat").textContent).toContain("(Δ°F)");
    expect(screen.queryByTestId("tune-slider-require_operational_gate")).toBeNull();

    const update = screen.getByTestId("sidebar-update-rule-FC1") as HTMLButtonElement;
    expect(update.disabled).toBe(true);

    fireEvent.click(screen.getByTestId("sidebar-tune-ops-proof"));
    fireEvent.change(screen.getByTestId("tune-slider-confirm_min"), {
      target: { value: "20" },
    });
    expect(update.disabled).toBe(false);
    fireEvent.click(update);

    await waitFor(() => {
      expect(screen.getByTestId("sidebar-tune-run-msg").textContent).toMatch(/Updated FC1/);
    });
    const firstRun = vi.mocked(runFdd).mock.calls[0]?.[0];
    expect(firstRun?.params?.FC1?.confirm_min).toBe(20);
    expect(firstRun?.params?.FC1?.require_operational_gate).toBe(0);
    expect(firstRun?.rule_ids).toEqual(["FC1"]);
    const savedApply = vi.mocked(putSessionConfig).mock.calls.at(-1)?.[0];
    expect(savedApply?.require_operational_proof).toBe(false);
    expect(savedApply?.params?.FC1?.require_operational_gate).toBe(0);
    expect(updated).toHaveLength(1);
    expect(update.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("tune-slider-confirm_min"), {
      target: { value: "5" },
    });
    expect(update.disabled).toBe(false);
    fireEvent.click(update);
    await waitFor(() => {
      expect(vi.mocked(runFdd).mock.calls).toHaveLength(2);
    });
    expect(vi.mocked(runFdd).mock.calls[1]?.[0].params?.FC1?.confirm_min).toBe(5);
    expect(screen.getByTestId("sidebar-tune-run-msg").textContent).toMatch(/Updated FC1/);
    expect(updated).toHaveLength(2);

    fireEvent.change(screen.getByTestId("tune-slider-confirm_min"), {
      target: { value: "20" },
    });
    fireEvent.click(update);
    await waitFor(() => {
      expect(vi.mocked(runFdd).mock.calls).toHaveLength(3);
    });

    const runsBeforeReset = vi.mocked(runFdd).mock.calls.length;
    const eventsBeforeReset = updated.length;
    fireEvent.click(screen.getByTestId("sidebar-tune-reset"));
    await waitFor(() => {
      expect(screen.getByTestId("sidebar-tune-stale").textContent).toMatch(/stale/i);
    });
    expect(vi.mocked(runFdd).mock.calls).toHaveLength(runsBeforeReset);
    expect(updated).toHaveLength(eventsBeforeReset);
    expect(screen.queryByTestId("sidebar-tune-run-msg")).toBeNull();
    expect(update.disabled).toBe(false);
    const resetSave = vi.mocked(putSessionConfig).mock.calls.at(-1)?.[0];
    expect(resetSave?.require_operational_proof).toBe(true);
    expect(resetSave?.params?.FC1).toBeUndefined();

    failSave = true;
    fireEvent.click(update);
    await waitFor(() => {
      expect(screen.getByTestId("sidebar-tune-error").textContent).toMatch(/Session save failed/);
    });
    expect(screen.queryByTestId("sidebar-tune-run-msg")).toBeNull();
    expect(screen.getByTestId("sidebar-tune-error").textContent).not.toMatch(/Updated/);
    expect(vi.mocked(runFdd).mock.calls).toHaveLength(runsBeforeReset);
    expect(updated).toHaveLength(eventsBeforeReset);
  });

  it("converts labels with the unit preference and leaves fraction and minutes alone", async () => {
    renderTuner();
    await openFc1();
    act(() => {
      window.dispatchEvent(
        new CustomEvent("openfdd:unit-system-changed", { detail: "metric" }),
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("tune-label-zone_t_lo").textContent).toContain("(°C)");
    });
    expect(screen.getByTestId("tune-label-eps_mat").textContent).toContain("(Δ°C)");
    expect(screen.getByTestId("tune-label-eps_dsp").textContent).toContain("(Pa)");
    expect(screen.getByTestId("tune-label-eps_vfd_spd").textContent).toContain("(frac)");
    expect(screen.getByTestId("tune-label-confirm_min").textContent).toContain("(min)");
    expect((screen.getByTestId("tune-slider-eps_vfd_spd") as HTMLInputElement).value).toBe("0.13");
    expect((screen.getByTestId("tune-slider-confirm_min") as HTMLInputElement).value).toBe("5");
  });
});
