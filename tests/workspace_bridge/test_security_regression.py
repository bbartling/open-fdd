from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]


def _reload_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> TestClient:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OFDD_BRIDGE_HOST", env.get("OFDD_BRIDGE_HOST", "127.0.0.1"))
    monkeypatch.setenv("OFDD_AUTH_SECRET", env.get("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!"))
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OFDD_AGENT_USER", "agent")
    monkeypatch.setenv("OFDD_AGENT_PASSWORD", "agent-secret")
    for key, value in env.items():
        if key.startswith("OFDD_") or key.startswith("OPENFDD_"):
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["token"]


def test_login_rate_limit_returns_429(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from openfdd_bridge.login_rate_limit import reset_for_tests  # noqa: E402

    reset_for_tests()
    monkeypatch.setenv("OFDD_AUTH_MAX_FAILURES", "3")
    monkeypatch.setenv("OFDD_AUTH_FAILURE_WINDOW_SECONDS", "300")
    client = _reload_client(monkeypatch, tmp_path)
    for _ in range(3):
        r = client.post("/api/auth/login", json={"username": "integrator", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "integrator", "password": "wrong"})
    assert r.status_code == 429


def test_weak_auth_secret_fails_public_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "192.168.1.10")
    monkeypatch.setenv("OFDD_AUTH_SECRET", "short")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.security import validate_startup_auth  # noqa: E402

    with pytest.raises(RuntimeError, match="OFDD_AUTH_SECRET"):
        validate_startup_auth()


def test_ws_ticket_cannot_call_api(raw_client: TestClient, integrator_headers: dict[str, str]):
    ticket_r = raw_client.post("/api/auth/ws-ticket", headers=integrator_headers)
    ticket = ticket_r.json()["ticket"]
    r = raw_client.get("/api/model/export", headers={"Authorization": f"Bearer {ticket}"})
    assert r.status_code == 401


def test_bearer_token_rejected_as_ws_ticket(raw_client: TestClient, integrator_headers: dict[str, str]):
    from starlette.websockets import WebSocketDisconnect

    token = integrator_headers["Authorization"].split(" ", 1)[1]
    with pytest.raises(WebSocketDisconnect):
        with raw_client.websocket_connect(
            "/ws/dashboard",
            headers={"sec-websocket-protocol": f"ofdd.ws, {token}"},
        ):
            pass


def test_operator_tools_list_read_only(raw_client: TestClient, operator_headers: dict[str, str]):
    r = raw_client.get("/openfdd-agent/tools", headers=operator_headers)
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["tools"]}
    assert "model.add_site" not in names
    assert "faults.lookup" in names


def test_agent_tool_audit_redacts_file_contents(raw_client: TestClient, integrator_headers: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    logs = tmp_path / "logs"
    logs.mkdir(parents=True)
    audit_path = logs / "audit.jsonl"
    monkeypatch.setenv("OFDD_AUDIT_LOG_PATH", str(audit_path))
    for name in list(sys.modules):
        if name.startswith("openfdd_bridge.audit"):
            del sys.modules[name]
    with patch("openfdd_bridge.agent_tools.app_edit_enabled", return_value=True), patch(
        "openfdd_bridge.agent_tools._tool_app_edit_file",
        return_value={"ok": True},
    ):
        r = raw_client.post(
            "/openfdd-agent/tool",
            json={"tool": "app.edit_file", "args": {"path": "x.py", "contents": "SECRET_CODE_BODY"}},
            headers=integrator_headers,
        )
    assert r.status_code == 200
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    record = json.loads(lines[-1])
    assert "SECRET_CODE_BODY" not in json.dumps(record)
    assert record["detail"]["args"]["content_hash"]


def test_bacnet_write_enabled_without_allowlist_denied(
    client: TestClient,
    integrator_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OFDD_ENABLE_BACNET_WRITE", "1")
    monkeypatch.setattr("openfdd_bridge.bacnet_write_guard.workspace_dir", lambda: tmp_path)
    r = client.post(
        "/api/bacnet/write",
        json={
            "device_instance": 1001,
            "object_identifier": "analog-value,1",
            "property_identifier": "present-value",
            "value": 72.0,
            "priority": 8,
        },
        headers=integrator_headers,
    )
    assert r.status_code == 403


def test_operator_cannot_bacnet_discover_without_flag(raw_client: TestClient, operator_headers: dict[str, str]):
    with patch(
        "openfdd_bridge.routes.bacnet_routes.commission_whois",
        return_value=(200, {"devices": [], "count": 0}),
    ):
        r = raw_client.post(
            "/api/bacnet/whois",
            json={"range_low": 1, "range_high": 100},
            headers=operator_headers,
        )
    assert r.status_code == 403


def test_operator_cannot_bacnet_mutate(raw_client: TestClient, operator_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS", "1")
    r = raw_client.delete("/api/bacnet/driver/registry", headers=operator_headers)
    assert r.status_code == 403


def test_integrator_bacnet_mutate_requires_flag(raw_client: TestClient, integrator_headers: dict[str, str]):
    r = raw_client.delete("/api/bacnet/driver/registry", headers=integrator_headers)
    assert r.status_code == 403


def test_operator_cannot_delete_model_point(raw_client: TestClient, operator_headers: dict[str, str]):
    r = raw_client.delete("/api/model/points/p1", headers=operator_headers)
    assert r.status_code == 403


def test_playground_worker_env_excludes_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OFDD_AUTH_SECRET", "super-secret-value")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "also-secret")
    from openfdd_bridge.playground_exec import _minimal_worker_env  # noqa: E402

    env = _minimal_worker_env(tmp_path / "api", tmp_path / "work")
    assert "OFDD_AUTH_SECRET" not in env
    assert "OFDD_OPERATOR_PASSWORD" not in env
    joined = json.dumps(env)
    assert "super-secret-value" not in joined


def test_inprocess_playground_rejected_on_public_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OFDD_PLAYGROUND_INPROCESS", "1")
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "0.0.0.0")
    _reload_client(monkeypatch, tmp_path, OFDD_BRIDGE_HOST="0.0.0.0")
    from openfdd_bridge.playground_exec import subprocess_enabled  # noqa: E402

    assert subprocess_enabled() is True


def test_audit_summary_hides_paths_by_default(raw_client: TestClient, integrator_headers: dict[str, str]):
    r = raw_client.get("/api/audit/summary", headers=integrator_headers)
    assert r.status_code == 200
    body = r.json()
    assert "audit_log_configured" in body
    assert "audit_log" not in body
