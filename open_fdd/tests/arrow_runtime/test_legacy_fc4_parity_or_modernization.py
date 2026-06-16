"""Legacy FC4 (pandas FaultConditionFour) → modern Arrow PID hunting detector.

Legacy gist used hourly resample + rising-edge counts on AHU operating modes.
Open-FDD v1 modernizes to sample-window rolling step / OS-bitmap change counts.
No strict legacy hourly parity mode is implemented or claimed here.
"""

from __future__ import annotations

import pyarrow as pa

from open_fdd.arrow_runtime.cookbook import pid_hunting_ahu_os_mask, pid_hunting_command_mask


def _oscillating_command_table(n: int = 70) -> pa.Table:
    vals = [10.0 if i % 2 == 0 else 70.0 for i in range(n)]
    return pa.table({"timestamp": pa.array(range(n)), "damper_cmd": pa.array(vals)})


def _stable_command_table(n: int = 70) -> pa.Table:
    return pa.table({"timestamp": pa.array(range(n)), "damper_cmd": pa.array([45.0] * n)})


def test_modern_fc4_flags_obvious_command_oscillation():
    table = _oscillating_command_table()
    mask = pid_hunting_command_mask(
        table,
        {
            "column": "damper_cmd",
            "hunting_window_samples": 60,
            "delta_os_max": 8,
            "min_command_delta": 0.05,
            "min_active_command": 0.05,
        },
    )
    assert mask.to_pylist()[-1] is True


def test_modern_fc4_does_not_flag_stable_command():
    table = _stable_command_table()
    mask = pid_hunting_command_mask(
        table,
        {
            "column": "damper_cmd",
            "hunting_window_samples": 60,
            "delta_os_max": 8,
            "min_command_delta": 0.05,
            "min_active_command": 0.05,
        },
    )
    assert True not in mask.to_pylist()


def test_modern_fc4_ahu_os_flags_excessive_mode_changes():
    n = 80
    # Toggle heat/cool/econ pattern → many OS bitmap changes while fan runs
    econ = [80.0 if i % 2 == 0 else 20.0 for i in range(n)]
    heat = [60.0 if i % 3 == 0 else 0.0 for i in range(n)]
    cool = [55.0 if i % 4 == 0 else 0.0 for i in range(n)]
    fan = [75.0] * n
    table = pa.table(
        {
            "timestamp": pa.array(range(n)),
            "outside-air-damper-command": pa.array(econ),
            "heating-valve-command": pa.array(heat),
            "cooling-valve-command": pa.array(cool),
            "supply-fan-speed-command": pa.array(fan),
        }
    )
    mask = pid_hunting_ahu_os_mask(
        table,
        {
            "hunting_window_samples": 60,
            "delta_os_max": 8,
            "ahu_min_oa_dpr": 0.1,
            "fan_on_threshold": 0.01,
        },
    )
    assert mask.to_pylist()[-1] is True


def test_modern_fc4_ahu_os_stable_modes_not_flagged():
    n = 80
    table = pa.table(
        {
            "timestamp": pa.array(range(n)),
            "outside-air-damper-command": pa.array([50.0] * n),
            "heating-valve-command": pa.array([0.0] * n),
            "cooling-valve-command": pa.array([30.0] * n),
            "supply-fan-speed-command": pa.array([70.0] * n),
        }
    )
    mask = pid_hunting_ahu_os_mask(
        table,
        {
            "hunting_window_samples": 60,
            "delta_os_max": 20,
            "ahu_min_oa_dpr": 0.1,
        },
    )
    assert True not in mask.to_pylist()
