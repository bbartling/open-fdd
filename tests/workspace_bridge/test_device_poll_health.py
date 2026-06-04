from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.device_poll_health import (  # noqa: E402
    compute_device_poll_health,
    poll_health_alerts,
)


def _model_two_vavs() -> dict:
    return {
        "sites": [{"id": "s1"}],
        "equipment": [
            {"id": "vav1", "site_id": "s1", "name": "VAV-1", "equipment_type": "Variable_Air_Volume_Box"},
            {"id": "vav2", "site_id": "s1", "name": "VAV-2", "equipment_type": "Variable_Air_Volume_Box"},
        ],
        "points": [
            {
                "id": "p1",
                "site_id": "s1",
                "equipment_id": "vav1",
                "external_id": "zn-t-1",
                "brick_type": "Zone_Air_Temperature_Sensor",
            },
            {
                "id": "p2",
                "site_id": "s1",
                "equipment_id": "vav2",
                "external_id": "zn-t-2",
                "brick_type": "Zone_Air_Temperature_Sensor",
            },
        ],
    }


def test_offline_when_all_points_stale():
    model = _model_two_vavs()
    ts = pd.date_range("2020-01-01", periods=5, freq="1h", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "zn-t-1": [72.0] * 5, "zn-t-2": [71.0] * 5})
    snap = compute_device_poll_health(model, "s1", df)
    vav1 = next(e for e in snap["equipment"] if e["equipment_id"] == "vav1")
    assert vav1["status"] == "offline"
    assert snap["offline_equipment"]


def test_degraded_when_one_point_stale():
    model = _model_two_vavs()
    end = pd.Timestamp.now(tz="UTC")
    ts = pd.date_range(end=end, periods=120, freq="5min")
    fresh = [72.0 + (i % 3) * 0.1 for i in range(120)]
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "zn-t-1": fresh,
            "zn-t-2": [None] * 120,
        }
    )
    snap = compute_device_poll_health(model, "s1", df)
    vav2 = next(e for e in snap["equipment"] if e["equipment_id"] == "vav2")
    assert vav2["status"] in {"degraded", "offline"}
    vav1 = next(e for e in snap["equipment"] if e["equipment_id"] == "vav1")
    assert vav1["status"] != "offline"


def test_poll_health_alerts_offline():
    snap = {
        "lookback_days": 14,
        "offline_equipment": [
            {
                "equipment_id": "vav1",
                "equipment_name": "VAV-1",
                "equipment_family": "VARIABLE",
                "points_polled": 2,
                "points_stale": 2,
            }
        ],
        "flaky_equipment": [],
    }
    alerts = poll_health_alerts(snap)
    assert alerts
    assert alerts[0]["code"] == "BLD-D"
    assert alerts[0]["source"] == "poll_health"
