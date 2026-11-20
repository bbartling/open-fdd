"""#1641: generic COIL-PERF covers the rules it replaces. On a VAV box (VAV roles only) it reproduces VAV-REHEAT (the
VAV pair keeps valve_open_vav 0.3 and min_dt_vav 1.667 delta degC); on a fan coil (SAT / zone temp) it reproduces
FCU-HTG-COIL's heating faults, and its cooling mode now needs a real minimum drop (FCU-CLG-COIL only caught SAT >= zone).
The three rules are retired; their definitions are frozen below as the reference.
The run-proof gate is switched off here so the thresholds are compared, not the gates (COIL-PERF is gated, as #1641
asks; the old FCU rules were exempt)."""
import numpy as np
import pandas as pd
import pytest

from open_fdd.rules.cookbook_catalog import (RULES_BY_ID, _f, _fcu_fan_on, _param_si_delta_temp_to_series,
                                           _vav_air_on, norm_cmd)

# ---- the retired rules, frozen here as the reference COIL-PERF must keep matching (#1641) ---------------------
def ref_vav_reheat(d, p, poll):
    """Reheat valve commanded open but the box's discharge air never warms above inlet.

    Inlet temp = duct air arriving from the AHU (≈ AHU discharge). Discharge temp = air
    leaving the box after the reheat coil. Reheat open + air flowing + no rise → stuck /
    failed reheat valve or coil. Fully computed from VAV-local sensors.
    """
    cmd_thr = _f(p, "reheat_cmd", 0.30)
    min_rise = _param_si_delta_temp_to_series(
        d, "vav-discharge-air-temp", _f(p, "min_rise", 1.666667)
    )
    flow_min = _f(p, "flow_on_min", 11.798689)
    reheat = norm_cmd(d["reheat-valve"]).fillna(0)
    rise = d["vav-discharge-air-temp"] - d["vav-inlet-air-temp"]
    return (
        _vav_air_on(d, flow_min)
        & d["vav-discharge-air-temp"].notna() & d["vav-inlet-air-temp"].notna()
        & (reheat > cmd_thr) & (rise < min_rise)
    )


def ref_fcu_htg_coil(d, p, poll):
    heat = norm_cmd(d["heating-valve"])
    rise = pd.to_numeric(d["discharge-air-temp"], errors="coerce") - pd.to_numeric(
        d["zone-air-temp"], errors="coerce"
    )
    coil_delta = _param_si_delta_temp_to_series(
        d, "discharge-air-temp", _f(p, "coil_delta", 3.0)
    )
    return _fcu_fan_on(d) & heat.notna() & (heat >= _f(p, "valve_open", 0.80)) & (rise < coil_delta)


def ref_fcu_clg_coil(d, p, poll):
    cool = norm_cmd(d["cooling-valve"])
    heat = norm_cmd(d["heating-valve"])
    rise = pd.to_numeric(d["discharge-air-temp"], errors="coerce") - pd.to_numeric(
        d["zone-air-temp"], errors="coerce"
    )
    return _fcu_fan_on(d) & cool.notna() & heat.notna() & (cool >= _f(p, "valve_open", 0.80)) & (heat <= 0.05) & (rise >= 0)


REFERENCE = {"VAV-REHEAT": ref_vav_reheat, "FCU-HTG-COIL": ref_fcu_htg_coil, "FCU-CLG-COIL": ref_fcu_clg_coil}

IDX = pd.date_range("2026-01-05", periods=12 * 24, freq="5min", tz="UTC")
UNGATED = {"require_run_proof": 0, "confirm_min": 15}


def _mask(rule_id, df, **params):
    p = {**UNGATED, **params}
    if rule_id in REFERENCE:
        return REFERENCE[rule_id](df.copy(), p, 300.0).fillna(False).astype(bool)
    return RULES_BY_ID[rule_id].compute(df.copy(), p, 300.0).astype(bool)


def test_the_three_rules_are_retired():
    assert not set(REFERENCE) & set(RULES_BY_ID)
    assert set(RULES_BY_ID["COIL-PERF"].equipment_kinds) >= {"ahu", "vav", "zone_other", "general"}


def _vav():
    rng = np.random.default_rng(1641)
    hour = np.asarray(IDX.hour)
    reheat = np.where(hour < 8, 0.6, np.where(hour < 12, 0.2, 0.9))       # open, below 0.3, wide open
    inlet = 13 + rng.normal(0, 0.1, len(IDX))
    rise = np.where(hour % 3 == 0, 0.5, 6.0)                                # weak rise every third hour
    return pd.DataFrame({"zone-airflow": 120.0, "reheat-valve": reheat, "vav-inlet-air-temp": inlet,
                         "vav-discharge-air-temp": inlet + rise}, index=IDX)


def _fcu():
    rng = np.random.default_rng(16412)
    hour = np.asarray(IDX.hour)
    htg = np.where(hour < 12, 0.95, 0.0)
    clg = np.where(hour >= 12, 0.95, 0.0)
    zone = 21 + rng.normal(0, 0.1, len(IDX))
    sat = np.where(hour < 12, zone + np.where(hour % 4 == 0, 1.0, 8.0),       # heating: weak rise every 4th hour
                   zone - np.where(hour % 4 == 0, 1.0, 6.0))                   # cooling: weak drop every 4th hour
    return pd.DataFrame({"fan-status": 1.0, "heating-valve": htg, "cooling-valve": clg, "zone-air-temp": zone,
                         "discharge-air-temp": sat}, index=IDX)


def test_vav_box_matches_vav_reheat():
    df = _vav()
    generic, old = _mask("COIL-PERF", df), _mask("VAV-REHEAT", df)
    assert old.sum() > 0
    assert (generic == old).all(), f"{int((generic != old).sum())} samples differ"


def test_fan_coil_heating_matches_fcu_htg_coil_and_cooling_needs_a_real_drop():
    df = _fcu()
    generic, htg_old, clg_old = _mask("COIL-PERF", df), _mask("FCU-HTG-COIL", df), _mask("FCU-CLG-COIL", df)
    heating = df["heating-valve"] > 0.5
    assert htg_old.sum() > 0
    assert (generic[heating] == htg_old[heating]).all()
    cooling = df["cooling-valve"] > 0.5
    # the weak 1 degC drop is a COIL-PERF fault (below min_dt 3.0) that FCU-CLG-COIL missed (it needed SAT >= zone)
    weak = cooling & (df["zone-air-temp"] - df["discharge-air-temp"] < 3.0)
    assert weak.sum() > 0 and generic[weak].all() and not clg_old[weak].any()
    assert not generic[cooling & ~weak].any()


@pytest.mark.parametrize("value", [0.29, 0.30])
def test_vav_open_threshold_edge(value):
    """VAV-REHEAT faulted at reheat > 0.3; COIL-PERF's VAV pair uses >= valve_open_vav (0.3), one tick more inclusive."""
    df = _vav().assign(**{"reheat-valve": value, "vav-discharge-air-temp": lambda x: x["vav-inlet-air-temp"] + 0.5})
    assert _mask("COIL-PERF", df).any() == (value >= 0.3)
