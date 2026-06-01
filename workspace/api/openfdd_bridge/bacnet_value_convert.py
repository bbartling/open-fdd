"""BACnet present-value unit conversion before feather ingest (device profiles + per-point override)."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Reusable profiles — reference from device_poll_profiles.csv or points.csv convert_profile column.
CONVERT_PROFILES: dict[str, str] = {
    "metric_temp_f": "metric_temp_f",
    "metric_temperature_to_fahrenheit": "metric_temp_f",
    "none": "none",
    "": "none",
}


def _load_device_profiles(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            inst = str(row.get("device_instance") or "").strip()
            profile = str(row.get("convert_profile") or row.get("profile") or "").strip()
            if inst and profile:
                out[inst] = profile
    return out


def _load_point_profiles(points_csv: Path) -> dict[str, str]:
    if not points_csv.is_file():
        return {}
    out: dict[str, str] = {}
    with points_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = str(row.get("point_id") or "").strip()
            profile = str(row.get("convert_profile") or "").strip()
            if pid and profile:
                out[pid] = profile
    return out


def _is_temperature_units(units: str) -> bool:
    u = str(units or "").lower()
    return any(x in u for x in ("celsius", "centigrade", "degc", "degree-c", "degrees-c"))


def convert_poll_value(
    value: Any,
    *,
    units: str,
    profile: str,
) -> tuple[float | Any, str]:
    """Return (numeric value, units label after conversion)."""
    if profile in ("", "none"):
        return value, units
    key = CONVERT_PROFILES.get(profile, profile)
    if key != "metric_temp_f":
        return value, units
    if not _is_temperature_units(units):
        return value, units
    try:
        c = float(value)
    except (TypeError, ValueError):
        return value, units
    f = c * 9.0 / 5.0 + 32.0
    return f, "degrees-fahrenheit"


def profile_for_sample(
    *,
    point_id: str,
    device_instance: str,
    device_profiles: dict[str, str],
    point_profiles: dict[str, str],
) -> str:
    if point_id in point_profiles:
        return point_profiles[point_id]
    return device_profiles.get(str(device_instance or "").strip(), "")


def load_convert_context(commission_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    dev_path = commission_dir / "device_poll_profiles.csv"
    pts_path = commission_dir / "points.csv"
    return _load_device_profiles(dev_path), _load_point_profiles(pts_path)
