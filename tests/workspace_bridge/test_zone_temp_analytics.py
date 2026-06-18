from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.timeseries_api import historian_column_candidates, resolve_historian_column  # noqa: E402
from openfdd_bridge.zone_temp_analytics import (  # noqa: E402
    _collapse_zones_by_column,
    _fan_on_minutes_by_period,
    _worst_zones,
    _summary_sentence,
    compute_zone_metrics,
    discover_topology,
    get_zone_temp_snapshot,
    zone_display_label,
)


def _bench_model() -> dict:
    import json

    return json.loads((REPO / "workspace" / "data" / "bench_import_model.json").read_text(encoding="utf-8"))


def test_discover_topology_sensors_only():
    topo = discover_topology(_bench_model(), "demo")
    assert topo["mode"] in {"sensors_only", "mixed", "ahu_systems"}
    zone_cols = {z["column"] for z in topo["zone_points"]}
    assert "stat_zn-t" in zone_cols
    assert "oa-t" not in zone_cols  # OA-T is Outside_Air_Temperature_Sensor, not zone


def test_compute_zone_metrics_day_night():
    model = _bench_model()
    topo = discover_topology(model, "demo")
    n = 96
    # Monday 2025-06-02 — span occupied hours (08–17 UTC) and overnight
    ts = pd.date_range("2025-06-02 08:00:00", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "oa-t": [70.0 + (i % 8) * 0.5 for i in range(n)],
            "stat_zn-t": [68.0 + (i % 6) * 0.3 for i in range(n)],
        }
    )
    metrics = compute_zone_metrics(df, topo, model, "demo")
    assert metrics["zones"]
    assert any(z.get("day_avg_f") is not None for z in metrics["zones"])
    assert "Zone temps:" in metrics["summary_sentence"]


def test_compute_zone_metrics_excludes_offline_and_zero_reads():
    model = _bench_model()
    topo = discover_topology(model, "demo")
    n = 96
    ts = pd.date_range("2025-06-02 08:00:00", periods=n, freq="15min", tz="UTC")
    good = [72.0 + (i % 4) * 0.2 for i in range(n)]
    bad = [0.0 if i > n // 2 else 72.0 for i in range(n)]
    df = pd.DataFrame({"timestamp": ts, "stat_zn-t": bad, "oa-t": good})
    device_snapshot = {
        "equipment": [
            {
                "equipment_id": "bench",
                "status": "offline",
                "points": [{"column": "stat_zn-t", "stale": True, "valid_ratio": 0.05}],
            }
        ]
    }
    metrics = compute_zone_metrics(df, topo, model, "demo", device_snapshot=device_snapshot)
    stat = next(z for z in metrics["zones"] if z["column"] == "stat_zn-t")
    assert stat.get("day_avg_f") is None
    assert stat.get("night_avg_f") is None
    assert stat.get("excluded_offline") is True


def test_recovery_with_fan_startup():
    model = {
        "sites": [{"id": "s1", "name": "Test"}],
        "equipment": [
            {"id": "ahu1", "site_id": "s1", "name": "AHU-1", "equipment_type": "Air_Handling_Unit", "feeds": ["vav1"]},
            {"id": "vav1", "site_id": "s1", "name": "VAV-1", "equipment_type": "Variable_Air_Volume_Box"},
        ],
        "points": [
            {
                "id": "z1",
                "site_id": "s1",
                "equipment_id": "vav1",
                "external_id": "zn-t",
                "brick_type": "Zone_Air_Temperature_Sensor",
            },
            {
                "id": "f1",
                "site_id": "s1",
                "equipment_id": "ahu1",
                "external_id": "fan-cmd",
                "brick_type": "Supply_Fan_Speed_Command",
            },
        ],
    }
    topo = discover_topology(model, "s1")
    assert topo["ahu_systems"]
    ts = pd.date_range("2025-06-03 00:00:00", periods=240, freq="5min", tz="UTC")
    fan = [0.0] * 60 + [1.0] * 180
    temps = [65.0] * 60
    for i in range(180):
        temps.append(65.0 + i * 0.08)
    df = pd.DataFrame({"timestamp": ts, "fan-cmd": fan, "zn-t": temps})
    metrics = compute_zone_metrics(df, topo, model, "s1")
    assert metrics["systems"]
    sys0 = metrics["systems"][0]
    assert sys0.get("fan_column") == "fan-cmd"
    assert sys0.get("median_recovery_f_per_min") is not None


def test_get_zone_temp_snapshot_cached(monkeypatch: pytest.MonkeyPatch):
    import openfdd_bridge.zone_temp_analytics as mod

    monkeypatch.setattr(mod, "_CACHE", {"generated_at": 0.0, "payload": {}})
    model = _bench_model()
    n = 48
    ts = pd.date_range("2025-06-01 12:00:00", periods=n, freq="30min", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "oa-t": [72.0] * n, "stat_zn-t": [71.0] * n})

    class _FakeModelService:
        def load(self) -> dict:
            return model

    monkeypatch.setattr(mod, "ensure_default_site", lambda *_a, **_k: "demo")
    monkeypatch.setattr(mod, "ModelService", _FakeModelService)
    monkeypatch.setattr(mod, "load_frame_for_run", lambda *_a, **_k: (df, "test"))

    first = get_zone_temp_snapshot(force=True)
    assert first["ok"] is True
    assert first.get("summary_sentence")
    second = get_zone_temp_snapshot(force=False)
    assert second.get("cached") is True


def test_summary_sentence_struggling():
    text = _summary_sentence(
        [{"label": "Z1", "day_avg_f": 72.0, "night_avg_f": 68.0}],
        [],
        [
            {
                "label": "Z2",
                "ahu_name": "AHU-1",
                "reason": "slow_recovery_after_fan_start",
            }
        ],
        "ahu_systems",
    )
    assert "slow recovery" in text.lower()


def test_acme_style_historian_columns_prefer_full_point_id():
    pt_a = {"id": "12035-analog-input-1", "name": "Space Temperature Local"}
    pt_b = {"id": "12023-analog-input-1", "name": "Space Temperature Local"}
    avail = {"12035-analog-input-1", "12023-analog-input-1", "analog-input-1"}
    assert resolve_historian_column(pt_a, avail) == "12035-analog-input-1"
    assert resolve_historian_column(pt_b, avail) == "12023-analog-input-1"
    assert historian_column_candidates(pt_a) == ["12035-analog-input-1", "analog-input-1"]


def test_zone_display_label_uses_equipment_name():
    pt = {"name": "Space Temperature Local", "brick_tag": "ZN-T"}
    eq = {"name": "Trane Vav 12023"}
    assert zone_display_label(pt, eq) == "Trane Vav 12023 (ZN-T)"


def test_collapse_zones_by_column_dedupes_shared_historian():
    zones = [
        {"column": "analog-input-1", "label": "Space Temperature Local", "equipment_name": "Trane Vav 12023", "day_avg_f": 70.0},
        {"column": "analog-input-1", "label": "Space Temperature Local", "equipment_name": "Trane Vav 12035", "day_avg_f": 70.0},
        {"column": "12033-analog-input-1", "label": "Trane Vav 12033 (ZN-T)", "equipment_name": "Trane Vav 12033", "day_avg_f": 68.0},
    ]
    out = _collapse_zones_by_column(zones)
    assert len(out) == 2
    shared = next(z for z in out if z["column"] == "analog-input-1")
    assert shared.get("shared_column_zone_count") == 2
    assert "Trane Vav 12023" in shared["label"]


def test_worst_zones_returns_distinct_columns_with_names():
    zones = [
        {
            "column": "z-hot",
            "label": "Trane Vav 12023 (ZN-T)",
            "equipment_name": "Trane Vav 12023",
            "day_avg_f": 74.0,
            "night_avg_f": 73.8,
            "setback_delta_f": 0.2,
            "recovery_f_per_min": 0.01,
        },
        {
            "column": "z-cool",
            "label": "Jci Vav 39 (ZN-T)",
            "equipment_name": "Jci Vav 39",
            "day_avg_f": 70.0,
            "night_avg_f": 65.0,
            "setback_delta_f": 5.0,
            "recovery_f_per_min": 0.12,
        },
    ]
    worst = _worst_zones(zones, [], [])
    assert len(worst) >= 1
    labels = {w.get("equipment_name") or w.get("label") for w in worst}
    assert "Trane Vav 12023" in labels


def test_fan_schedule_weekday_vs_weekend():
    ts = pd.date_range("2025-06-02 06:00:00", periods=96 * 3, freq="15min", tz="UTC")
    fan = []
    for t in ts:
        wd = t.weekday()
        hr = t.hour
        if wd < 5 and 8 <= hr < 17:
            fan.append(1.0)
        elif wd >= 5:
            fan.append(0.0)
        else:
            fan.append(0.0)
    df = pd.DataFrame({"timestamp": ts, "fan-cmd": fan})
    sched = _fan_on_minutes_by_period(df, "fan-cmd", site_tz="UTC")
    assert sched.get("weekday", {}).get("fan_on_minutes", 0) > sched.get("weekend", {}).get("fan_on_minutes", 0)


def test_compute_zone_metrics_per_vav_columns():
    model = {
        "sites": [{"id": "acme", "name": "Acme"}],
        "equipment": [
            {"id": "vav23", "site_id": "acme", "name": "Trane Vav 12023", "brick_type": "VAV"},
            {"id": "vav39", "site_id": "acme", "name": "Jci Vav 39", "brick_type": "VAV"},
        ],
        "points": [
            {
                "id": "12023-analog-input-1",
                "equipment_id": "vav23",
                "brick_type": "Zone_Air_Temperature_Sensor",
                "name": "Space Temperature Local",
                "brick_tag": "ZN-T",
            },
            {
                "id": "12039-analog-input-1",
                "equipment_id": "vav39",
                "brick_type": "Zone_Air_Temperature_Sensor",
                "name": "Space Temperature Local",
                "brick_tag": "ZN-T",
            },
        ],
    }
    n = 96
    ts = pd.date_range("2025-06-02 08:00:00", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "12023-analog-input-1": [72.0 + (i % 4) * 0.2 for i in range(n)],
            "12039-analog-input-1": [68.0 + (i % 4) * 0.1 for i in range(n)],
        }
    )
    topo = discover_topology(model, "acme", available_columns=set(df.columns))
    metrics = compute_zone_metrics(df, topo, model, "acme")
    assert len(metrics["zones"]) == 2
    assert metrics["zones"][0]["equipment_name"].startswith(("Trane", "Jci"))
    assert metrics["worst_zones"]
    assert metrics["worst_zones"][0].get("equipment_name")


def test_compact_for_llm_large_snapshot_is_valid_json():
    import json

    from openfdd_bridge.zone_temp_analytics import compact_for_llm, slim_zone_for_llm

    zones = [
        {
            "label": f"VAV-{i} zone temperature sensor",
            "day_avg_f": 72.0 + i * 0.01,
            "night_avg_f": 68.0,
            "recovery_f_per_min": 0.05,
        }
        for i in range(16)
    ]
    systems = [
        {
            "ahu_name": f"AHU-{j}",
            "fan_column": f"fan_{j}",
            "median_recovery_f_per_min": 0.1,
            "zones": [
                {
                    "label": f"z{k}",
                    "recovery_f_per_min": 0.05,
                    "day_avg_f": 72.0,
                    "night_avg_f": 68.0,
                }
                for k in range(12)
            ],
        }
        for j in range(6)
    ]
    snap = {
        "topology_mode": "mixed",
        "zone_sensor_count": 64,
        "summary_sentence": "x" * 200,
        "zones": zones,
        "systems": systems,
        "struggling_zones": zones[:8],
    }
    full_bytes = len(json.dumps(snap).encode("utf-8"))
    max_bytes = max(400, full_bytes // 2)
    text = compact_for_llm(snap, max_bytes=max_bytes)
    parsed = json.loads(text)
    assert len(text.encode("utf-8")) <= max_bytes
    assert parsed["zone_sensor_count"] == 64
    slim = slim_zone_for_llm(snap)
    assert slim["zones"]
