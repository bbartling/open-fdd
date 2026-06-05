"""Arrow table builders for tests and Rule Lab samples."""

from __future__ import annotations

from typing import Any

import pyarrow as pa


def sample_hvac_table(rows: int = 100, *, seed: int = 0) -> pa.Table:
    """Synthetic HVAC columns for Arrow rule tests."""
    import random

    rng = random.Random(seed)
    data: dict[str, list[Any]] = {
        "timestamp": [f"2026-01-01T{h:02d}:00:00Z" for h in range(rows)],
        "site_id": ["site_a"] * rows,
        "equipment_id": ["ahu_1"] * rows,
        "zone_temp": [rng.uniform(68, 78) for _ in range(rows)],
        "outside_air_temp": [rng.uniform(40, 90) for _ in range(rows)],
        "fan_cmd": [rng.choice([0.0, 0.0, 1.0]) for _ in range(rows)],
        "airflow_cfm": [rng.uniform(0, 12000) for _ in range(rows)],
        "cooling_cmd": [rng.uniform(0, 1) for _ in range(rows)],
        "heat_cmd": [rng.uniform(0, 1) for _ in range(rows)],
        "cool_cmd": [rng.uniform(0, 1) for _ in range(rows)],
        "oa_damper_cmd": [rng.uniform(0, 1) for _ in range(rows)],
        "sensor_value": [rng.uniform(-5, 110) for _ in range(rows)],
    }
    return pa.table(data)
