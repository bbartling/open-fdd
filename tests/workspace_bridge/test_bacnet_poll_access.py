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


@pytest.fixture
def authed_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.delenv("OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS", raising=False)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_operator_can_set_point_poll_without_mutations_flag(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.routes.bacnet_routes.set_point_poll",
        return_value={"ok": True, "point_id": "5007-analog-input-1168", "enabled": True},
    ) as mock_poll:
        r = authed_client.patch(
            "/api/bacnet/driver/point",
            json={"point_id": "5007-analog-input-1168", "enabled": True, "poll_interval_s": 60},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    mock_poll.assert_called_once()


def test_bacnet_refresh_pv_uses_single_read_not_rpm(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.routes.bacnet_routes.commission_read",
        return_value=(
            200,
            {
                "device_instance": 5007,
                "object_identifier": "analog-input,1168",
                "property_identifier": "present-value",
                "value": 50.128082275390625,
            },
        ),
    ) as mock_read:
        with patch("openfdd_bridge.routes.bacnet_routes.commission_read_multiple") as mock_rpm:
            r = authed_client.post(
                "/api/bacnet/read",
                json={
                    "device_instance": 5007,
                    "device_address": "",
                    "object_identifier": "analog-input,1168",
                    "property_identifier": "present-value",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
    assert r.status_code == 200
    assert r.json()["value"] == 50.128082275390625
    mock_read.assert_called_once_with(
        5007,
        "analog-input,1168",
        "present-value",
        device_address="",
    )
    mock_rpm.assert_not_called()
