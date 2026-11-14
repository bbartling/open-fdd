"""Motor-status gate in all three legs: pandas oracle == SQL pack == SPARQL client (#1618).

One AHU, one day, fan proof ON 00-08, OFF 08-16, ON 16-24 (UTC from the first sample). The supply air temperature
sits on its setpoint except where a fault is injected (+8 K for two hours):

* ``off_only``: the fault is inside the OFF window only, so it must not count anywhere;
* ``on_and_off``: the same OFF-window fault plus one inside the second ON window, which must count;
* ``cmd_only``: as ``on_and_off`` but without a fan status point, so the gate falls back to the fan command;
* ``always_off``: the fan is off all day, with the fault injected, so nothing is assessed and nothing counts.

The rule is AHU-SATDEV (``fan_running`` gate with a 10 min startup delay). Fault hours must be equal across the three
legs. The two pandas legs must also agree on how many samples survived the gate, and SQL ``covered_hours`` stays the
data coverage of the day.
"""
from __future__ import annotations

import shutil

import pytest

pytest.importorskip("pandas")
if shutil.which("node") is None:  # pragma: no cover
    pytest.skip("node is required for the hook runner", allow_module_level=True)

from adapters import ADAPTERS  # noqa: E402
from open_fdd.parity import generate, reference  # noqa: E402

import sparql_leg as leg  # noqa: E402

RULE = "AHU-SATDEV"
SP, FAULT = 12.8, 20.8


def motor_dataset(variant: str):
    ds = generate(0, 1, 1, "basic")
    t0 = min(r["ts"] for r in ds.history)
    for r in ds.history:
        h = (r["ts"] - t0) / 3.6e6
        on = variant != "always_off" and not (8 <= h < 16)
        r["fan_status"] = None if variant == "cmd_only" else (1.0 if on else 0.0)
        r["fan_cmd"] = 1.0 if on else 0.0
        r["sat_sp"], r["sat"] = SP, SP
        if 10 <= h < 12:                                   # inside the OFF window
            r["sat"] = FAULT
        if variant in ("on_and_off", "cmd_only", "always_off") and 18 <= h < 20:   # inside the 2nd ON window
            r["sat"] = FAULT
    return ds


@pytest.fixture(scope="module", params=["off_only", "on_and_off", "cmd_only", "always_off"])
def legs(request):
    ds = motor_dataset(request.param)
    rows = {}
    for engine in ("pglite", "sqlite"):
        ad = ADAPTERS[engine]()
        ad.load(ds)
        try:
            rows[engine] = [r for r in ad.run([RULE])[RULE] if r["equipment_id"] == "AHU-1"][0]
        finally:
            ad.close()
    a, b = rows["pglite"], rows["sqlite"]
    assert float(a["fault_hours"]) == pytest.approx(float(b["fault_hours"]), abs=1e-9), rows
    row = a
    oracle = reference(ds, [RULE])[RULE]["AHU-1"]
    sparql = leg.sparql_reference(ds, [RULE])[0][RULE]["AHU-1"]
    return request.param, row, oracle, sparql


def test_three_legs_agree_on_status_hours_and_gated_samples(legs):
    variant, sql, oracle, sparql = legs
    assert sparql["status"] == oracle["status"], variant
    assert sparql["active_samples"] == oracle["active_samples"], variant
    for got in (float(sql["fault_hours"]), sparql["pandas"] or 0.0):
        assert got == pytest.approx(oracle["pandas"] or 0.0, abs=1e-9), (variant, sql, oracle, sparql)
    assert float(sql["covered_hours"]) == pytest.approx(23 + 11 / 12), "SQL coverage is the day's data coverage"


def test_off_window_faults_never_count_on_window_faults_do(legs):
    variant, sql, oracle, sparql = legs
    hours = oracle["pandas"] or 0.0
    if variant in ("off_only", "always_off"):
        assert hours == 0.0 and float(sql["fault_hours"]) == 0 and oracle["status"] != "FAULT", variant
    else:  # 2 h injected while ON; the rule's confirmation delay trims the first samples
        assert oracle["status"] == "FAULT" and 1.5 <= hours <= 2.0, (variant, hours)
    if variant == "always_off":
        assert oracle["active_samples"] == 0
    else:  # 16 h ON less the startup delay after each start: only ON samples are assessed
        assert 0 < oracle["active_samples"] <= 16 * 12, oracle["active_samples"]