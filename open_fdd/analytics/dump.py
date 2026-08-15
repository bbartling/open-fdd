"""Write named analytics CSVs (same filenames as vibe19 / WattLab dump-vs-dump)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from open_fdd.analytics.core import (
    mech_cooling_oat_bins,
    motor_run_hours_table,
    motor_run_hours_weekly,
)
from open_fdd.analytics.vav_health import vav_health_matrix

DUMP_FILENAMES = (
    "vav_health_matrix.csv",
    "mech_cooling_oat_bins.csv",
    "motor_hours.csv",
    "motor_weekly.csv",
)


def dump_tables(
    out_dir: str | Path,
    *,
    frames: Mapping[str, pd.DataFrame],
    role_map: Mapping[str, Any] | None = None,
    rule_results: pd.DataFrame | None = None,
    weather: pd.DataFrame | None = None,
    building_id: str = "BUILDING",
    unit_system: str = "imperial",
) -> dict[str, Path]:
    """Write pandas-oracle analytics tables for dump-vs-dump contract files."""
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    role_map = dict(role_map or {})
    frames_d = dict(frames)
    written: dict[str, Path] = {}

    vav = vav_health_matrix(
        frames_d,
        building_id=building_id,
        rule_results=rule_results,
    )
    p = dest / "vav_health_matrix.csv"
    vav.to_csv(p, index=False)
    written[p.name] = p

    bins = mech_cooling_oat_bins(
        frames_d,
        role_map,
        weather=weather,
        unit_system=unit_system,
    )
    p = dest / "mech_cooling_oat_bins.csv"
    bins.to_csv(p, index=False)
    written[p.name] = p

    motors = motor_run_hours_table(frames_d, role_map)
    p = dest / "motor_hours.csv"
    motors.to_csv(p, index=False)
    written[p.name] = p

    weekly = motor_run_hours_weekly(frames_d, role_map, weather=weather)
    p = dest / "motor_weekly.csv"
    weekly.to_csv(p, index=False)
    written[p.name] = p

    return written
