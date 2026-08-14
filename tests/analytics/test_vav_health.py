"""vav_health_matrix_v1 — unknown is not PASS; not a 60th diagnostic."""

from __future__ import annotations

import pandas as pd

from open_fdd.analytics.vav_health import VavHealthConfig, vav_health_matrix, vav_health_summary


def _week(eq: str, damper: float, zone: float, flow: float, n: int = 480) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 07:00", periods=n, freq="5min", tz="UTC")  # Mon week
    return pd.DataFrame(
        {
            "timestamp_utc": idx,
            "damper_pct": damper,
            "zone_t": zone,
            "zone_flow": flow,
            "fan_status": 1.0,
        },
        index=idx,
    )


def test_missing_occ_is_unknown_not_pass():
    df = _week("VAV_1", 0.5, 72.0, 200, n=2)
    out = vav_health_matrix({"VAV_1": df}, building_id="B1")
    assert out.iloc[0]["poor_zone_performance"] is None or pd.isna(out.iloc[0]["poor_zone_performance"])
    assert "?/3" in str(out.iloc[0]["score_label"]) or out.iloc[0]["dimensions_evaluable"] < 3


def test_rogue_full_open_operating_denominator():
    n = 480  # 40h at 5 min
    df = _week("VAV_2", 0.99, 72.0, 400, n=n)
    cfg = VavHealthConfig(min_operating_hours=20.0, min_occupied_hours=0.0)
    out = vav_health_matrix({"VAV_2": df}, building_id="B1", config=cfg)
    row = out.iloc[0]
    assert bool(row["rogue_damper"]) is True
    assert float(row["operating_hours"]) >= 20


def test_zero_operating_hours_unknown_rogue():
    df = _week("VAV_3", 0.99, 72.0, 0.0, n=12)
    df["fan_status"] = 0.0
    df["zone_flow"] = 0.0
    out = vav_health_matrix({"VAV_3": df}, building_id="B1")
    assert out.iloc[0]["rogue_damper"] is None or pd.isna(out.iloc[0]["rogue_damper"])


def test_natural_sort_and_summary():
    frames = {
        "VAV_10": _week("VAV_10", 0.4, 72, 200, n=480),
        "VAV_2": _week("VAV_2", 0.4, 72, 200, n=480),
    }
    out = vav_health_matrix(frames, building_id="B1")
    sm = vav_health_summary(out)
    assert sm["schema_version"] == "vav_health_matrix_v1"
    assert "groups" in sm


def test_broken_from_rule_results():
    df = _week("VAV_4", 0.4, 72, 200, n=480)
    rr = pd.DataFrame(
        {
            "equipment_id": ["VAV_4"],
            "rule_id": ["VAV-7"],
            "status": ["FAULT"],
            "fault_hours": [2.0],
        }
    )
    out = vav_health_matrix({"VAV_4": df}, building_id="B1", rule_results=rr)
    assert bool(out.iloc[0]["broken_box"]) is True
