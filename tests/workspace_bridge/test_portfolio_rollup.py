"""Tests for edge portfolio rollup snapshot."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from workspace.api.openfdd_bridge.portfolio_rollup import build_portfolio_rollup


@pytest.fixture
def mock_status():
    return {
        "status": "warning",
        "traffic": "yellow",
        "alerts": [
            {"code": "AHU-SF-OFF-HRS", "equipment_family": "AHU", "severity": "warning"},
            {"code": "AHU-SF-OFF-HRS", "equipment_family": "AHU", "severity": "warning"},
        ],
        "fdd_alert_count": 2,
    }


def test_build_portfolio_rollup_aggregates(mock_status, tmp_path, monkeypatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    (tmp_path / "runtime_metrics.json").write_text(
        json.dumps(
            {
                "sites": {
                    "acme": {
                        "ahu-01": {
                            "equipment_id": "ahu-01",
                            "equipment_name": "AHU-01",
                            "fan_run_hours": 12.5,
                            "system_run_hours": 8.0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "fdd_results.json").write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "status": "ok",
                        "flagged": 3,
                        "fault_code": "VAV-DMP-STUCK",
                        "site_id": "acme",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "workspace.api.openfdd_bridge.portfolio_rollup.collect_status",
            return_value=mock_status,
        ),
        patch(
            "workspace.api.openfdd_bridge.portfolio_rollup.compute_poll_throughput",
            return_value={"summary_sentence": "ok", "points_polled": 10},
        ),
        patch(
            "workspace.api.openfdd_bridge.portfolio_rollup.get_checkin_status",
            return_value={"last_checkin": {"ok": True, "finished_at": "2026-05-30T12:00:00Z"}},
        ),
        patch(
            "workspace.api.openfdd_bridge.portfolio_rollup.override_status",
            return_value={"operator_override_points": 1, "total_override_points": 2},
        ),
        patch(
            "workspace.api.openfdd_bridge.portfolio_rollup.load_registry",
            return_value={
                "last_scan_at": "2026-05-30T11:00:00Z",
                "devices": {
                    "1": {
                        "device_instance": 1,
                        "device_address": "192.168.1.10",
                        "points_with_overrides": [
                            {
                                "object_identifier": "analog-value,1",
                                "object_name": "SAT-SP",
                                "overrides": [{"priority_level": 8, "value": 55.0}],
                            }
                        ],
                    }
                },
            },
        ),
        patch(
            "workspace.api.openfdd_bridge.portfolio_rollup.ensure_default_site",
            return_value="acme",
        ),
    ):
        doc = build_portfolio_rollup(site_id="acme")

    assert doc["ok"] is True
    assert doc["site_id"] == "acme"
    assert doc["building"]["traffic"] == "yellow"
    assert doc["faults"]["active_by_code"]["AHU-SF-OFF-HRS"] == 2
    assert doc["fdd_batch"]["flagged_samples_by_code"]["VAV-DMP-STUCK"] == 3
    assert doc["runtime_metrics"]["ahu-01"]["fan_run_hours"] == 12.5
    assert doc["overrides"]["operator_override_points"] == 1
    assert len(doc["overrides"]["points"]) == 1
