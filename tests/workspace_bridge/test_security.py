from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]


def _reload_and_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> TestClient:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OFDD_BRIDGE_HOST", env.get("OFDD_BRIDGE_HOST", "127.0.0.1"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_missing_auth_does_not_grant_integrator(raw_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("OFDD_AUTH_SECRET", raising=False)
    monkeypatch.delenv("OFDD_AUTH_DISABLED", raising=False)
    c = _reload_and_client(monkeypatch, tmp_path, OFDD_BRIDGE_HOST="127.0.0.1")
    r = c.post(
        "/api/playground/lint",
        json={"code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"},
    )
    assert r.status_code == 503


def test_auth_disabled_only_on_localhost_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    c = _reload_and_client(
        monkeypatch,
        tmp_path,
        OFDD_AUTH_DISABLED="1",
        OFDD_BRIDGE_HOST="127.0.0.1",
    )
    monkeypatch.delenv("OFDD_AUTH_SECRET", raising=False)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.deps import require_user  # noqa: E402
    from openfdd_bridge.security import auth_dev_bypass_enabled  # noqa: E402

    assert auth_dev_bypass_enabled() is True


def test_auth_disabled_rejected_on_public_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OFDD_AUTH_DISABLED", "1")
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "0.0.0.0")
    monkeypatch.delenv("OFDD_AUTH_SECRET", raising=False)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.security import auth_dev_bypass_enabled  # noqa: E402

    assert auth_dev_bypass_enabled() is False


def test_integrator_route_rejects_operator(raw_client: TestClient, operator_headers: dict[str, str]):
    r = raw_client.post(
        "/api/playground/lint",
        json={"code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"},
        headers=operator_headers,
    )
    assert r.status_code == 403


def test_agent_tool_rejects_integrator(raw_client: TestClient, integrator_headers: dict[str, str]):
    r = raw_client.post(
        "/openfdd-agent/tool",
        json={"tool": "rules.list", "args": {}},
        headers=integrator_headers,
    )
    assert r.status_code == 403


def test_cors_origins_default_no_lan_auto(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "0.0.0.0")
    monkeypatch.delenv("OFDD_CORS_ALLOW_PRIVATE_LAN", raising=False)
    monkeypatch.delenv("OFDD_CORS_ORIGINS", raising=False)
    for name in list(sys.modules):
        if name.startswith("openfdd_bridge.settings") or name == "openfdd_bridge.settings":
            del sys.modules[name]
    from openfdd_bridge.settings import cors_allow_private_lan as lan  # noqa: E402
    from openfdd_bridge.settings import cors_origins as origins  # noqa: E402

    assert lan() is False
    assert "http://127.0.0.1:5173" in origins()


def test_security_headers_on_health(client: TestClient):
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Content-Security-Policy")


def test_anonymous_cannot_read_host_stats(raw_client: TestClient):
    assert raw_client.get("/api/host/stats").status_code == 401


def test_anonymous_can_read_public_check_engine(raw_client: TestClient):
    assert raw_client.get("/health/stack").status_code == 200
    assert raw_client.get("/openfdd-agent/building-insight").status_code == 200


def test_anonymous_cannot_read_agent_context(raw_client: TestClient):
    assert raw_client.get("/openfdd-agent/context").status_code == 401


def test_playground_rejects_import_os(client: TestClient, integrator_headers: dict[str, str]):
    r = client.post(
        "/api/playground/test-rule",
        json={
            "code": "import os\ndef evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n",
            "config": {},
            "limit": 5,
        },
        headers=integrator_headers,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_playground_row_timeout_returns_error_event():
    from concurrent.futures import TimeoutError as FuturesTimeout
    from openfdd_bridge import playground  # noqa: E402

    rows = [{"row": 0, "ts_ms": 1, "temp": 72.0, "ts": "2020-01-01"}]
    code = "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"
    with patch("openfdd_bridge.playground._call_with_timeout", side_effect=FuturesTimeout()):
        _flags, events = playground.sweep_rule(code, {}, rows)
    assert any("timed out" in str(e.get("message", "")).lower() for e in events)


def test_playground_huge_print_truncated(client: TestClient, integrator_headers: dict[str, str]):
    r = client.post(
        "/api/playground/test-rule",
        json={
            "code": 'def evaluate(row, cfg, prev_row=None, rows=None):\n    print("x" * 20000)\n    return False\n',
            "config": {},
            "limit": 2,
        },
        headers=integrator_headers,
    )
    events = r.json().get("events") or []
    stdout = next((e for e in events if e.get("type") == "stdout"), None)
    assert stdout is None or len(str(stdout.get("text", ""))) <= 9000


def test_tracebacks_hidden_without_debug(client: TestClient, integrator_headers: dict[str, str]):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("OFDD_DEBUG_TRACEBACKS", raising=False)
    r = client.post(
        "/api/playground/run-script",
        json={"code": "raise RuntimeError('secret-path /home/ben/open-fdd')"},
        headers=integrator_headers,
    )
    body = r.json()
    trace = str(body.get("trace") or "")
    assert "/home/ben" not in trace


def test_bacnet_write_disabled_by_default(client: TestClient, integrator_headers: dict[str, str]):
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


def test_bacnet_write_allowlist_skips_bad_device_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi import HTTPException

    from openfdd_bridge.bacnet_write_guard import validate_write_target

    allow = tmp_path / "bacnet"
    allow.mkdir(parents=True)
    (allow / "write_allowlist.json").write_text(
        '{"device_instances": ["1001", "not-a-number", 1002]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "openfdd_bridge.bacnet_write_guard.workspace_dir",
        lambda: tmp_path,
    )
    validate_write_target(device_instance=1001, object_identifier="analog-value,1")
    with pytest.raises(HTTPException) as exc:
        validate_write_target(device_instance=9999, object_identifier="analog-value,1")
    assert exc.value.status_code == 403


def test_bacnet_write_bad_priority(client: TestClient, integrator_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_ENABLE_BACNET_WRITE", "1")
    r = client.post(
        "/api/bacnet/write",
        json={
            "device_instance": 1001,
            "object_identifier": "analog-value,1",
            "property_identifier": "present-value",
            "value": 72.0,
        },
        headers=integrator_headers,
    )
    assert r.status_code == 400


def test_agent_chat_requires_auth(raw_client: TestClient):
    with patch(
        "openfdd_bridge.routes.agent_routes.ollama_client.chat",
        return_value={"ok": True, "mode": "ollama", "model": "tinyllama", "reply": "hi"},
    ):
        assert raw_client.post("/openfdd-agent/chat", json={"message": "hi"}).status_code == 401
