"""Offline tests for Acme live validator logic (mocked HTTP)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import io
import zipfile

from scripts.acme_live_validate import (
    AcmeLiveValidator,
    load_env_file,
    normalize_image_tag,
    parse_container_image_tag,
    pick_equipment_for_rule_kit,
    scan_logs_for_fatal,
    validate_equipment_kit_zip,
    validate_trend_payload,
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


def test_stale_ui_bundle_fails(tmp_path):
    local_idx = tmp_path / "index.html"
    local_idx.write_text('<html><script src="/assets/index-NEWHASH.js"></script></html>', encoding="utf-8")
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        auth_env=Path("/nonexistent"),
        local_ui_index=local_idx,
    )

    def fake_request(method, path, body=None, auth=True):
        if path == "/":
            return 200, '<html><script src="/assets/index-OLDHASH.js"></script></html>', 1.0
        if "index-OLDHASH" in path:
            return 200, "ok", 1.0
        return 404, "", 1.0

    validator.client.request = fake_request  # type: ignore[method-assign]
    status, msg, _ = validator._check_ui_bundle()
    assert status == "fail"
    assert "Stale UI bundle" in msg


def test_missing_js_asset_fails():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        auth_env=Path("/nonexistent"),
    )

    def fake_request(method, path, body=None, auth=True):
        if path == "/":
            return 200, '<html><script src="/assets/index-ABC.js"></script></html>', 1.0
        return 404, "missing", 1.0

    validator.client.request = fake_request  # type: ignore[method-assign]
    status, msg, _ = validator._check_ui_bundle()
    assert status == "fail"
    assert "HTTP 404" in msg


def test_wrong_bridge_image_tag_fails():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        expected_image_tag="3.0.33",
        auth_env=Path("/nonexistent"),
    )
    validator.token = "tok"
    with patch(
        "http_probes.check_stack_revision",
        return_value={"image_tag": "3.0.32", "errors": [], "warnings": []},
    ):
        status, msg, _ = validator._check_docker_image_tag()
    assert status == "fail"
    assert "3.0.32" in msg


def test_wrong_commission_image_tag_fails_remote_host():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={"required_services": ["bridge", "commission"], "optional_services": []},
        expected_image_tag="3.0.33",
        auth_env=Path("/nonexistent"),
        remote_host_json={
            "services": [
                {"service": "bridge", "image": "ghcr.io/bbartling/openfdd-bridge:3.0.33"},
                {"service": "commission", "image": "ghcr.io/bbartling/openfdd-commission:3.0.32"},
            ]
        },
    )
    status, msg, _ = validator._check_remote_host()
    assert status == "fail"
    assert "commission" in msg


def test_optional_service_absent_passes():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={
            "required_services": ["bridge", "commission"],
            "optional_services": ["mcp-rag"],
        },
        expected_image_tag="3.0.32",
        auth_env=Path("/nonexistent"),
        remote_host_json={
            "services": [
                {"service": "bridge", "image": "ghcr.io/bbartling/openfdd-bridge:3.0.32"},
                {"service": "commission", "image": "ghcr.io/bbartling/openfdd-commission:3.0.32"},
            ]
        },
    )
    status, _, _ = validator._check_remote_host()
    assert status == "pass"


def test_bad_fdd_rule_refs_fail_commissioning_export():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        auth_env=Path("/nonexistent"),
    )
    validator.token = "tok"
    bundle = {
        "sites": [{"id": "acme"}],
        "equipment": [],
        "points": [{"id": "p1", "fdd_rule_ids": ["missing-rule"]}],
        "fdd_rules": [{"id": "real-rule"}],
    }
    validator.client.get_json = lambda path, auth=True: (  # type: ignore[method-assign]
        200,
        bundle,
        1.0,
    )
    status, msg, _ = validator._check_commissioning_export()
    assert status == "fail"
    assert "fdd_rule_ids" in msg


def test_pick_equipment_prefers_ahu_with_bindings():
    bundle = {
        "equipment": [
            {"id": "vav-1", "equipment_type": "VAV"},
            {"id": "ahu-1", "equipment_type": "AHU"},
        ],
        "points": [
            {"id": "p1", "equipment_id": "vav-1", "fdd_rule_ids": ["r1"]},
            {"id": "p2", "equipment_id": "ahu-1", "fdd_rule_ids": ["r1", "r2"]},
        ],
        "fdd_rules": [{"id": "r1"}, {"id": "r2"}],
    }
    eq_id, reason = pick_equipment_for_rule_kit(bundle)
    assert eq_id == "ahu-1"
    assert "ahu" in reason.lower()


def test_equipment_kit_missing_manifest_fails():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hi")
    errors, _ = validate_equipment_kit_zip(buf.getvalue(), "ahu-1")
    assert any("manifest" in e for e in errors)


def test_equipment_kit_valid_minimal_passes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            '{"equipment_id":"ahu-1","rules":[{"rule_id":"r1","status":"ok"}]}',
        )
        zf.writestr("rules/r1/rule.py", "def apply_faults_arrow(t,c,x): return t")
        zf.writestr("rules/r1/column_map.json", "{}")
        zf.writestr("rules/r1/sample.feather", b"")
        zf.writestr("rules/r1/result.json", "{}")
    errors, _ = validate_equipment_kit_zip(buf.getvalue(), "ahu-1")
    assert not errors


def test_sparql_preset_failure_fails_in_full():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={},
        auth_env=Path("/nonexistent"),
        mode="full",
    )
    validator.token = "tok"
    presets = {"presets": [{"preset_id": pid} for pid in [
        "rules_to_equipment", "rules_to_sensors", "rules_to_bacnet_devices",
        "equipment_to_points", "missing_rule_bindings", "orphan_points", "points_by_bacnet_device",
    ]]}

    def fake_get(path, auth=True):
        if path.endswith("/fdd-query-presets"):
            return 200, presets, 1.0
        if "rules_to_equipment" in path:
            return 500, {}, 1.0
        return 200, {"rows": [{"a": 1}]}, 1.0

    validator.client.get_json = fake_get  # type: ignore[method-assign]
    status, msg, _ = validator._check_sparql()
    assert status == "fail"
    assert "rules_to_equipment" in msg


def test_pypi_smoke_fails_strict_full_mode():
    validator = AcmeLiveValidator(
        base="http://127.0.0.1:8765",
        site_id="acme",
        building_id="vm-bbartling",
        profile={"strict_fdd_in_full": True},
        auth_env=Path("/nonexistent"),
        mode="full",
        strict_fdd=True,
    )
    with patch("subprocess.run", return_value=type("R", (), {"returncode": 1, "stderr": "boom", "stdout": ""})()):
        with patch("pathlib.Path.is_file", return_value=True):
            status, msg, _ = validator._check_pypi_rules()
    assert status == "fail"
    assert "smoke failed" in msg


def test_trend_all_null_fails():
    errors, _, _ = validate_trend_payload(
        {"series": [{"points": [{"ts": "2026-01-01T00:00:00Z", "value": None}]}]},
        min_samples=1,
    )
    assert any("null" in e for e in errors)


def test_trend_timestamps_series_dict_passes():
    errors, _, details = validate_trend_payload(
        {
            "row_count": 10,
            "timestamps": [f"2026-01-01T00:{i:02d}:00Z" for i in range(10)],
            "series": {"space_temperature_local": [72.0 + i * 0.1 for i in range(10)]},
        },
        min_samples=3,
    )
    assert not errors
    assert details["point_count"] == 10


def test_normalize_image_tag_strips_v():
    assert normalize_image_tag("v3.0.32") == "3.0.32"
    assert parse_container_image_tag("ghcr.io/o/openfdd-bridge:3.0.32") == "3.0.32"


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
