from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "bacnet" / "commissioning").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS", raising=False)
    monkeypatch.delenv("OFDD_DISABLE_BACNET_DISCOVERY_MUTATIONS", raising=False)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def _token(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_bacnet_config_mutations_enabled_by_default(client: TestClient):
    token = _token(client, "integrator", "msi")
    r = client.get("/config/bacnet", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["discovery_mutations_enabled"] is True


def test_integrator_sync_discovery_denied_when_explicitly_disabled(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS", "0")
    for name in list(sys.modules):
        if name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    c = TestClient(create_app())
    token = _token(c, "integrator", "msi")
    r = c.post(
        "/api/bacnet/driver/sync-discovery",
        json={
            "device_instance": 8,
            "device_address": "10.0.0.8",
            "objects": [{"object_identifier": "analog-input,1", "object_name": "x"}],
            "replace": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "bacnet_mutations_disabled"
    assert "point discovery" in detail["message"].lower()


def test_operator_sync_discovery_role_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS", "1")
    for name in list(sys.modules):
        if name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    c = TestClient(create_app())
    token = _token(c, "operator", "changeme")
    r = c.post(
        "/api/bacnet/driver/sync-discovery",
        json={
            "device_instance": 8,
            "device_address": "10.0.0.8",
            "objects": [{"object_identifier": "analog-input,1", "object_name": "x"}],
            "replace": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "bacnet_mutations_role"
    assert "integrator" in detail["message"].lower()
