from __future__ import annotations

import pandas as pd

from open_fdd.rules import run_rule


def frame(**columns):
    n = len(next(iter(columns.values())))
    df = pd.DataFrame(columns, index=pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC"))
    df.attrs["equipment_id"] = "FCU_1"
    df.attrs["equipment_type"] = "UNKNOWN"
    return df


def result(rule_id, df, params=None):
    return run_rule(rule_id, df, params=params or {}, poll_seconds=300, require_operational_gates=False)


def test_all_nine_fcu_predicates():
    assert result("FCU-SENSOR-NULL", frame(**{"zone-air-temp": [None, None], "zone-air-temp-sp": [21, 21]})).status == "FAULT"
    assert result("FCU-HTG-COIL", frame(**{"discharge-air-temp": [75], "zone-air-temp": [72], "heating-valve": [100], "fan-status": [1]}), {"confirm_min": 0}).status == "FAULT"
    assert result("FCU-CLG-COIL", frame(**{"discharge-air-temp": [90], "zone-air-temp": [72], "cooling-valve": [100], "heating-valve": [0], "fan-status": [1]}), {"confirm_min": 0}).status == "FAULT"
    common = {"discharge-air-temp": [80], "zone-air-temp": [72], "cooling-valve": [0], "heating-valve": [0], "fan-status": [1]}
    assert result("FCU-VALVE-PASS-HTG", frame(**common), {"confirm_min": 0}).status == "FAULT"
    common["discharge-air-temp"] = [60]
    assert result("FCU-VALVE-PASS-CLG", frame(**common), {"confirm_min": 0}).status == "FAULT"
    assert result("FCU-DAMPER-POS", frame(**{"damper-cmd": [25], "damper": [7], "fan-status": [1]}), {"confirm_min": 0}).status == "FAULT"
    assert result("FCU-CO2-DAMPER", frame(**{"zone-co2": [1200], "damper-cmd": [5], "fan-status": [1]}), {"confirm_min": 0}).status == "FAULT"
    assert result("FCU-DEADBAND", frame(**{"cooling-sp": [21.5], "heating-sp": [21.0]})).status == "FAULT"
    modes = frame(**{"heating-valve": [100, 0, 100, 0, 100], "cooling-valve": [0, 100, 0, 100, 0]})
    assert result("FCU-MODE-CYCLE", modes).status == "FAULT"


def test_boundaries_do_not_fault():
    assert result("FCU-SENSOR-NULL", frame(**{"zone-air-temp": [72, None], "zone-air-temp-sp": [21, 21]})).status == "PASS"
    assert result("FCU-CLG-COIL", frame(**{"discharge-air-temp": [55], "zone-air-temp": [72], "cooling-valve": [100], "heating-valve": [0], "fan-status": [1]}), {"confirm_min": 0}).status == "PASS"
    assert result("FCU-DAMPER-POS", frame(**{"damper-cmd": [25], "damper": [10], "fan-status": [1]}), {"confirm_min": 0}).status == "PASS"
    assert result("FCU-CO2-DAMPER", frame(**{"zone-co2": [250], "damper-cmd": [0], "fan-status": [1]}), {"confirm_min": 0}).status == "PASS"
    assert result("FCU-DEADBAND", frame(**{"cooling-sp": [22], "heating-sp": [21]})).status == "PASS"

