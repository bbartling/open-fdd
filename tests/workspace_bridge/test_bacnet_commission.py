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
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_operator_can_bacnet_whois(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.commission_client.whois",
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
