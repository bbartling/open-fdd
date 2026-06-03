from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.zone_temp_analytics import (  # noqa: E402
    _summary_sentence,
    compute_zone_metrics,
    discover_topology,
    get_zone_temp_snapshot,
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
    assert "slow zones" in text.lower()
