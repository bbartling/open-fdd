"""Bench-style API integration: BACnet poll CRUD, Arrow FDD rules, graceful bad-code rejection."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

GOOD_ARROW = (
    "import pyarrow as pa\nimport pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n"
    "    return pc.greater(pc.cast(table['SAT'], pa.float64()), float(cfg.get('high', 50)))\n"
)
BAD_SYNTAX = "def apply_faults_arrow(table, cfg, context=None):\nreturn False\n"
LEGACY_EVAL = "def evaluate(row, cfg):\n    return True\n"
PANDAS_RULE = "import pandas as pd\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return False\n"




def test_playground_rejects_legacy_and_pandas(client: TestClient, integrator_headers: dict[str, str]):
    for code in (LEGACY_EVAL, PANDAS_RULE, BAD_SYNTAX):
        r = client.post("/api/playground/lint", json={"code": code}, headers=integrator_headers)
        assert r.status_code == 200
        assert r.json()["ok"] is False, code[:40]


def test_save_arrow_rule_and_batch_obvious_fault(client: TestClient, integrator_headers: dict[str, str]):
    save = client.post(
        "/api/rules/save",
        json={
            "name": "bench SAT always high",
            "mode": "rule",
            "code": GOOD_ARROW,
            "config": {"high": 0},
            "severity": "critical",
            "fault_code": "AHU-B",
        },
        headers=integrator_headers,
    )
    assert save.status_code == 200, save.text
    import pandas as pd

    df = pd.DataFrame({"SAT": [80.0, 85.0]})
    with patch(
        "openfdd_bridge.fdd_runner.load_frame_for_run",
        return_value=(df, "demo"),
    ):
        batch = client.post("/api/rules/batch", json={"limit": 100}, headers=integrator_headers)
    assert batch.status_code == 200
    assert batch.json().get("ok") is True


def test_operator_poll_point_without_mutations_flag(client: TestClient, operator_headers: dict[str, str]):
    with patch(
        "openfdd_bridge.routes.bacnet_routes.set_point_poll",
        return_value={"ok": True, "point_id": "5007-analog-input-1168"},
    ):
        r = client.patch(
            "/api/bacnet/driver/point",
            json={"point_id": "5007-analog-input-1168", "enabled": True, "poll_interval_s": 60},
            headers=operator_headers,
        )
    assert r.status_code == 200


def test_refresh_pv_single_read(client: TestClient, operator_headers: dict[str, str]):
    with patch(
        "openfdd_bridge.routes.bacnet_routes.commission_read",
        return_value=(200, {"value": 50.12}),
    ) as mock_read:
        with patch("openfdd_bridge.routes.bacnet_routes.commission_read_multiple") as mock_rpm:
            r = client.post(
                "/api/bacnet/read",
                json={
                    "device_instance": 5007,
                    "object_identifier": "analog-input,1168",
                    "property_identifier": "present-value",
                },
                headers=operator_headers,
            )
    assert r.status_code == 200
    mock_read.assert_called_once()
    mock_rpm.assert_not_called()


def test_commandable_inferred_for_analog_value(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    bacnet_dir = workspace / "bacnet" / "commissioning"
    bacnet_dir.mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge import bacnet_driver_store as store

    store.sync_discovery(
        device_instance=5007,
        device_address="10.0.0.1",
        objects=[{"object_identifier": "analog-value,1", "name": "SP", "commandable": False}],
        replace=True,
    )
    tree = store.driver_tree()
    pt = tree["devices"][0]["points"][0]
    assert pt["commandable"] is True
