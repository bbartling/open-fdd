"""Tests for data-model-driven fault insight enrichment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyarrow as pa
import pytest

from openfdd_bridge.fault_insight_analytics import (
    motor_points_for_equipment,
)


def test_motor_points_from_parent_feeds() -> None:
    model = {
        "sites": [{"id": "demo"}],
        "equipment": [
            {"id": "ahu-1", "site_id": "demo", "name": "RTU", "feeds": ["vav-1"]},
            {"id": "vav-1", "site_id": "demo", "name": "VAV-1"},
        ],
        "points": [
            {
                "id": "fan-1",
                "site_id": "demo",
                "equipment_id": "ahu-1",
                "brick_type": "Fan_Status",
                "external_id": "fan-status",
            },
            {
                "id": "zn-1",
                "site_id": "demo",
                "equipment_id": "vav-1",
                "brick_type": "Zone_Air_Temperature_Sensor",
                "external_id": "zn-t",
            },
        ],
    }
    motors = motor_points_for_equipment(model, "demo", "vav-1")
    assert len(motors) == 1
    assert motors[0]["column"] == "fan-status"
    assert motors[0]["equipment_id"] == "ahu-1"


def test_enrich_fault_insight_with_historian(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    ts = [now - timedelta(minutes=i) for i in range(5, 0, -1)]
    table = pa.table(
        {
            "timestamp": ts,
            "oa-t": [70.0, 71.0, 90.0, 92.0, 68.0],
            "fan-status": [1.0, 1.0, 1.0, 0.0, 0.0],
        }
    )

    def fake_read(site_id: str, columns: list[str]):
        return table, "bacnet"

    import openfdd_bridge.fault_insight_analytics as fia
    from openfdd_bridge.fault_insight_analytics import enrich_fault_insight

    monkeypatch.setattr(fia, "_read_site_table", fake_read)

    model = {
        "sites": [{"id": "demo"}],
        "equipment": [{"id": "dev-5007", "site_id": "demo", "name": "5007"}],
        "points": [
            {
                "id": "oa",
                "site_id": "demo",
                "equipment_id": "dev-5007",
                "brick_type": "Outside_Air_Temperature_Sensor",
                "external_id": "oa-t",
            },
            {
                "id": "fan",
                "site_id": "demo",
                "equipment_id": "dev-5007",
                "brick_type": "Fan_Status",
                "external_id": "fan-status",
            },
        ],
    }
    insight = enrich_fault_insight(
        model=model,
        site_id="demo",
        equipment_id="dev-5007",
        sensor_column="oa-t",
        analytics={"avg_value_fault": 91.0, "fault_samples": 2, "total_samples": 5, "value_unit": "°F"},
        rule_config={"bounds_low": 50, "bounds_high": 85},
        lookback_hours=1,
    )
    assert insight["avg_while_fault"] == 91.0
    assert insight["rule_bounds_low"] == 50
    assert insight["rule_bounds_high"] == 85
    assert insight["avg_overall"] is not None
    assert insight.get("motor_runtime_hours", 0) >= 0
