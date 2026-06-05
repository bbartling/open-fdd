from __future__ import annotations

import os
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
def authed_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_integrator_can_bacnet_whois(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.routes.bacnet_routes.commission_whois",
        return_value=(200, {"devices": [], "count": 0}),
    ):
        r = authed_client.post(
            "/api/bacnet/whois",
            json={"range_low": 1, "range_high": 100},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_bacnet_inventory_empty(authed_client: TestClient):
    r = authed_client.get("/api/bacnet/inventory")
    assert r.status_code == 401
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    r = authed_client.get("/api/bacnet/inventory", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["devices"], list)


def test_bacnet_read_property(authed_client: TestClient):
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
                "device_instance": 100,
                "object_identifier": "analog-input,1",
                "property_identifier": "present-value",
                "value": 72.5,
            },
        ),
    ):
        r = authed_client.post(
            "/api/bacnet/read",
            json={
                "device_instance": 100,
                "object_identifier": "analog-input,1",
                "property_identifier": "present-value",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json()["value"] == 72.5


def test_bacnet_read_priority_array(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.routes.bacnet_routes.commission_priority_array",
        return_value=(
            200,
            {
                "device_instance": 100,
                "object_identifier": "analog-value,1",
                "priority_array": [
                    {"priority_level": 1, "type": "real", "value": 72.0},
                    {"priority_level": 16, "type": "null", "value": None},
                ],
            },
        ),
    ):
        r = authed_client.post(
            "/api/bacnet/priority-array",
            json={
                "device_instance": 100,
                "object_identifier": "analog-value,1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body["priority_array"]) == 2
    assert body["priority_array"][0]["priority_level"] == 1


def test_bacnet_read_multiple(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.routes.bacnet_routes.commission_read_multiple",
        return_value=(200, {"device_instance": 100, "results": []}),
    ):
        r = authed_client.post(
            "/api/bacnet/read-multiple",
            json={
                "device_instance": 100,
                "requests": [
                    {
                        "object_identifier": "analog-input,1",
                        "property_identifier": "present-value",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200


def test_bacnet_server_points(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.routes.bacnet_routes.commission_server_points",
        return_value=(
            200,
            {
                "ok": True,
                "points": [
                    {
                        "name": "openfdd-edge-online",
                        "object_identifier": "('binaryValue', 9001)",
                        "present_value": "active",
                    }
                ],
            },
        ),
    ):
        r = authed_client.get(
            "/api/bacnet/server/points",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json()["points"][0]["name"] == "openfdd-edge-online"


def test_bacnet_write_rejects_invalid_object_identifier(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    token = login.json()["token"]
    r = authed_client.post(
        "/api/bacnet/write",
        json={
            "device_instance": 1,
            "object_identifier": "not-valid",
            "property_identifier": "present-value",
            "value": 1.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_bacnet_import_to_model(authed_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    token = login.json()["token"]
    r = authed_client.post(
        "/api/bacnet/import-to-model",
        json={
            "device_instance": 5007,
            "device_address": "192.168.1.10:47808",
            "objects": [
                {"object_identifier": "analog-input,1", "name": "SAT", "commandable": False},
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["points_added"] == 1
    assert body["equipment_id"] == "bacnet-5007"
