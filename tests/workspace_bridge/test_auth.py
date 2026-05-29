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
    monkeypatch.setenv("OFDD_WEB_USER", "operator")
    monkeypatch.setenv("OFDD_WEB_PASSWORD", "changeme")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_operator_can_use_agent_chat(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    token = login.json()["token"]
    with patch(
        "openfdd_bridge.routes.agent_routes.ollama_client.chat",
        return_value={"ok": True, "mode": "ollama", "model": "tinyllama", "reply": "hi"},
    ):
        r = authed_client.post(
            "/openfdd-agent/chat",
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_login_and_call(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "operator"
    token = login.json()["token"]
    denied = authed_client.post("/api/playground/lint", json={"code": "x=1"})
    assert denied.status_code == 401
    forbidden = authed_client.post(
        "/api/playground/lint",
        json={"code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert forbidden.status_code == 403
    msi = authed_client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    msi_token = msi.json()["token"]
    ok = authed_client.post(
        "/api/playground/lint",
        json={"code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"},
        headers={"Authorization": f"Bearer {msi_token}"},
    )
    assert ok.status_code == 200
