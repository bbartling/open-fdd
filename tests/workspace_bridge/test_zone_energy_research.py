from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.zone_energy_research import build_zone_energy_research  # noqa: E402
from openfdd_bridge.zone_temp_analytics import _occupied_mask  # noqa: E402


def test_near_zero_recovery_and_minimal_setback_flags():
    zone_snapshot = {
        "lookback_days": 14,
        "zones": [
            {"column": "z1", "label": "Zone 1", "day_avg_f": 69.0, "night_avg_f": 68.8, "recovery_f_per_min": 0.01},
            {"column": "z2", "label": "Zone 2", "day_avg_f": 70.0, "night_avg_f": 69.5, "recovery_f_per_min": 0.0},
        ],
        "systems": [{"ahu_name": "AHU-1", "median_recovery_f_per_min": 0.005}],
    }
    research = build_zone_energy_research(zone_snapshot, None)
    assert "site_near_zero_recovery" in research["site_flags"]
    assert research["minimal_setback_zone_count"] >= 2
    assert any(o["topic"] == "energy_setback" for o in research["opportunities"])
    assert research["llm_research_tasks"]


def test_sensor_health_cross_check():
    zone_snapshot = {
        "zones": [{"column": "z1", "label": "Zone 1", "day_avg_f": 72.0, "night_avg_f": 68.0}],
        "systems": [],
    }
    device_snapshot = {
        "equipment": [
            {
                "equipment_name": "VAV-1",
                "points": [
                    {"column": "z1", "stale": True, "has_fdd": True, "valid_ratio": 0.2, "flips_per_day": 0},
                ],
            }
        ]
    }
    research = build_zone_energy_research(zone_snapshot, device_snapshot)
    assert "Zone 1" in research["suspicious_sensors"]
    assert any(o["topic"] == "sensor_integrity" for o in research["opportunities"])


def test_unoccupied_heat_gain_slope():
    ts = pd.date_range("2025-06-02 18:00:00", periods=48, freq="30min", tz="UTC")
    zone_df = pd.DataFrame({"timestamp": ts, "z1": [65.0 + i * 0.15 for i in range(48)]})
    occupied = _occupied_mask(zone_df["timestamp"], "UTC")
    zone_snapshot = {
        "zones": [{"column": "z1", "label": "Zone 1", "day_avg_f": 72.0, "night_avg_f": 71.0}],
        "systems": [],
    }
    research = build_zone_energy_research(
        zone_snapshot,
        None,
        zone_df=zone_df,
        occupied_mask=occupied,
    )
    z1 = research["zones"][0]
    assert "unoccupied_heat_gain" in z1["flags"] or z1.get("unoccupied_slope_f_per_h", 0) > 0
