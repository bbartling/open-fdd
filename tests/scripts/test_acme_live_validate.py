"""Offline tests for Acme live validator logic (mocked HTTP)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.acme_live_validate import (
    AcmeLiveValidator,
    load_env_file,
    scan_logs_for_fatal,
)


def test_load_env_file_parses_export_and_quotes(tmp_path):
    p = tmp_path / "env"
    p.write_text(
        "export ACME_SSH_HOST=10.0.0.1\nOFDD_INTEGRATOR_USER=integrator\n"
        "OFDD_INTEGRATOR_PASSWORD='p$w&d'\n",
        encoding="utf-8",
    )
    env = load_env_file(p)
    assert env["ACME_SSH_HOST"] == "10.0.0.1"
    assert env["OFDD_INTEGRATOR_PASSWORD"] == "p$w&d"


def test_scan_logs_for_fatal():
    assert "Traceback" in scan_logs_for_fatal("foo Traceback bar")
    assert not scan_logs_for_fatal("normal log line")


def test_no_duplicate_devices_fails_on_dup_bacnet():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={"max_duplicate_bacnet_devices": 0},
        auth_env=Path("/nonexistent"),
        mode="quick",
    )
    validator.token = "tok"
    bundle = {
        "sites": [{"id": "acme"}],
        "equipment": [
            {"id": "e1", "bacnet_device_id": 1100},
            {"id": "e2", "bacnet_device_id": 1100},
        ],
        "points": [],
        "fdd_rules": [],
    }

    def fake_get(path, auth=True):
        if "commissioning-export" in path:
            return 200, bundle, 1.0
        if "inventory" in path:
            return 200, {"devices": []}, 1.0
        return 404, {}, 1.0

    validator.client.get_json = fake_get  # type: ignore[method-assign]
    status, msg, details = validator._check_no_duplicate_devices()
    assert status == "fail"
    assert "Duplicate BACnet" in msg
    assert details["duplicate_bacnet_device_ids"]


def test_empty_model_fails_health_threshold():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={"min_equipment_count": 10, "min_point_count": 50},
        auth_env=Path("/nonexistent"),
    )
    validator.token = "tok"
    validator.client.get_json = lambda path, auth=True: (  # type: ignore[method-assign]
        200,
        {"counts": {"equipment": 2, "points": 5}, "score": 10, "status": "warning"},
        1.0,
    )
    status, msg, _ = validator._check_model_health()
    assert status == "fail"
    assert "counts low" in msg


def test_building_status_missing_context_fails():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        auth_env=Path("/nonexistent"),
    )
    validator.token = "tok"

    def fake_get(path, auth=True):
        if path.startswith("/api/faults/status"):
            return 200, {
                "families": [
                    {
                        "faults": [
                            {
                                "source": "fdd",
                                "title": "Fault only code",
                                "code": "acme-test",
                                "model_context": {"equipment": {"id": "", "name": ""}},
                            }
                        ]
                    }
                ]
            }, 1.0
        return 200, {}, 1.0

    validator.client.get_json = fake_get  # type: ignore[method-assign]
    with patch(
        "http_probes.check_building_dashboard_health",
        return_value={"errors": [], "warnings": []},
    ):
        status, msg, _ = validator._check_building_status()
    assert status == "fail"
    assert "missing" in msg.lower()


def test_building_status_nested_equipment_name_passes():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        auth_env=Path("/nonexistent"),
    )
    validator.token = "tok"

    def fake_get(path, auth=True):
        if path.startswith("/api/faults/status"):
            return 200, {
                "families": [
                    {
                        "faults": [
                            {
                                "source": "fdd",
                                "title": "AHU-C · SAT flatline",
                                "code": "AHU-C",
                                "model_context": {
                                    "equipment": {"id": "ahu-c", "name": "AHU-C", "type": "AHU"},
                                    "point": {"id": "p1", "name": "SAT"},
                                },
                            }
                        ]
                    }
                ]
            }, 1.0
        return 200, {}, 1.0

    validator.client.get_json = fake_get  # type: ignore[method-assign]
    with patch(
        "http_probes.check_building_dashboard_health",
        return_value={"errors": [], "warnings": []},
    ):
        status, msg, _ = validator._check_building_status()
    assert status == "pass"
    assert "missing equipment" not in msg.lower()


def test_trend_empty_fails_via_http_probes_errors():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        auth_env=Path("/nonexistent"),
    )
    validator.token = "tok"
    with patch(
        "http_probes.check_integrator_ui_api",
        return_value={"errors": ["/api/timeseries/readings HTTP 422"], "warnings": []},
    ):
        status, msg, _ = validator._check_trends()
    assert status == "fail"
    assert "422" in msg
