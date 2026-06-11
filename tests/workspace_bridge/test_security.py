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
        json={"code": "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.greater(table['SAT'], 50)\n"},
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
    monkeypatch.delenv("OFDD_INSECURE_LAN_DEV", raising=False)
    monkeypatch.delenv("OFDD_ALLOW_PUBLIC_UNAUTHENTICATED_DEV", raising=False)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.security import auth_dev_bypass_enabled  # noqa: E402

    assert auth_dev_bypass_enabled() is False


def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OFDD_AUTH_SECRET",
        "OFDD_OPERATOR_USER",
        "OFDD_OPERATOR_PASSWORD",
        "OFDD_INTEGRATOR_USER",
        "OFDD_INTEGRATOR_PASSWORD",
        "OFDD_AGENT_USER",
        "OFDD_AGENT_PASSWORD",
        "OFDD_WEB_USER",
        "OFDD_WEB_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)


def _reload_security(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]


def test_startup_localhost_auth_disabled_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _clear_auth_env(monkeypatch)
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="127.0.0.1",
        OFDD_AUTH_DISABLED="1",
    )
    from openfdd_bridge.main import create_app  # noqa: E402

    create_app()


def test_startup_lan_ip_no_auth_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _clear_auth_env(monkeypatch)
    _reload_security(monkeypatch, tmp_path, OFDD_BRIDGE_HOST="192.168.1.50")
    from openfdd_bridge.security import validate_startup_auth  # noqa: E402

    with pytest.raises(RuntimeError, match="cannot start"):
        validate_startup_auth()


def test_startup_public_bind_no_auth_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _clear_auth_env(monkeypatch)
    _reload_security(monkeypatch, tmp_path, OFDD_BRIDGE_HOST="0.0.0.0")
    from openfdd_bridge.security import validate_startup_auth  # noqa: E402

    with pytest.raises(RuntimeError, match="cannot start"):
        validate_startup_auth()


def test_startup_public_bind_auth_disabled_without_insecure_flag_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    _clear_auth_env(monkeypatch)
    monkeypatch.delenv("OFDD_INSECURE_LAN_DEV", raising=False)
    monkeypatch.delenv("OFDD_ALLOW_PUBLIC_UNAUTHENTICATED_DEV", raising=False)
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="0.0.0.0",
        OFDD_AUTH_DISABLED="1",
    )
    from openfdd_bridge.main import create_app  # noqa: E402

    with pytest.raises(RuntimeError, match="OFDD_AUTH_DISABLED"):
        create_app()


def test_startup_public_bind_with_configured_auth_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="0.0.0.0",
        OFDD_AUTH_SECRET="test-secret-key-32chars-minimum!!",
        OFDD_INTEGRATOR_USER="integrator",
        OFDD_INTEGRATOR_PASSWORD="msi",
    )
    from openfdd_bridge.main import create_app  # noqa: E402

    create_app()


def test_startup_public_bind_insecure_lan_dev_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _clear_auth_env(monkeypatch)
    _reload_security(
        monkeypatch,
        tmp_path,
        OFDD_BRIDGE_HOST="::",
        OFDD_AUTH_DISABLED="1",
        OFDD_ALLOW_PUBLIC_UNAUTHENTICATED_DEV="1",
    )
    from openfdd_bridge.main import create_app  # noqa: E402

    create_app()


def test_integrator_route_rejects_operator(raw_client: TestClient, operator_headers: dict[str, str]):
    r = raw_client.post(
        "/api/playground/lint",
        json={"code": "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.greater(table['SAT'], 50)\n"},
        headers=operator_headers,
    )
    assert r.status_code == 403


def test_operator_read_tool_allowed(raw_client: TestClient, operator_headers: dict[str, str]):
    r = raw_client.post(
        "/openfdd-agent/tool",
        json={"tool": "faults.lookup", "args": {"code": "VAV-C"}},
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert r.json()["result"]["code"] == "VAV-C"


def test_operator_write_tool_blocked(raw_client: TestClient, operator_headers: dict[str, str]):
    r = raw_client.post(
        "/openfdd-agent/tool",
        json={"tool": "model.add_site", "args": {"name": "X"}},
        headers=operator_headers,
    )
    assert r.status_code == 400
    assert "integrator or agent" in r.json()["detail"].lower()


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
    csp = r.headers.get("Content-Security-Policy") or ""
    assert "frame-ancestors 'none'" in csp
    assert r.headers.get("Permissions-Policy") == (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    # COOP/CORP omitted on plain HTTP (Tailscale/LAN) — set only behind HTTPS.
    assert r.headers.get("Cross-Origin-Opener-Policy") is None
    assert r.headers.get("Cross-Origin-Resource-Policy") is None
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    # Single value per header (no Caddy + bridge duplication).
    raw = r.headers.raw
    for name in (
        b"x-content-type-options",
        b"x-frame-options",
        b"referrer-policy",
        b"content-security-policy",
    ):
        matches = [pair for pair in raw if pair[0].lower() == name]
        assert len(matches) == 1, f"duplicate header {name.decode()}"


def test_anonymous_cannot_read_host_stats(raw_client: TestClient):
    assert raw_client.get("/api/host/stats").status_code == 401


def test_anonymous_can_read_public_building_insights(raw_client: TestClient):
    for path in (
        "/openfdd-agent/building-insight",
        "/openfdd-agent/operational-brief",
        "/openfdd-agent/zone-temps",
        "/openfdd-agent/device-poll-health",
        "/openfdd-agent/ollama/health",
    ):
        assert raw_client.get(path).status_code == 200, path


def test_anonymous_cannot_read_authenticated_stack_health(raw_client: TestClient):
    assert raw_client.get("/health/stack").status_code == 401


def test_health_minimal_public(raw_client: TestClient):
    r = raw_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["service"] == "openfdd-bridge"
    assert "version" in body
    import open_fdd

    assert body.get("openfdd_version") == open_fdd.__version__
    assert "auth_required" in body
    assert "bacnet_poll" not in body
    assert "repo_root" not in body
    assert "data_dir" not in body


def test_health_stack_requires_auth(raw_client: TestClient):
    assert raw_client.get("/health/stack").status_code == 401


def test_health_stack_integrator(client: TestClient):
    r = client.get("/health/stack")
    assert r.status_code == 200
    body = r.json()
    assert "services" in body
    assert any(s["id"] == "bridge" for s in body["services"])


def test_ws_ticket_and_connect(raw_client: TestClient, integrator_headers: dict[str, str]):
    ticket_r = raw_client.post("/api/auth/ws-ticket", headers=integrator_headers)
    assert ticket_r.status_code == 200
    ticket = ticket_r.json()["ticket"]
    assert ticket
    with raw_client.websocket_connect(
        "/ws/dashboard",
        headers={**integrator_headers, "sec-websocket-protocol": f"ofdd.ws, {ticket}"},
    ) as ws:
        payload = ws.receive_json()
        assert "stack" in payload
        assert "faults" in payload


def test_ws_query_ticket_rejected_by_default(raw_client: TestClient, integrator_headers: dict[str, str]):
    ticket_r = raw_client.post("/api/auth/ws-ticket", headers=integrator_headers)
    ticket = ticket_r.json()["ticket"]
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with raw_client.websocket_connect(f"/ws/dashboard?ticket={ticket}"):
            pass
    assert excinfo.value.code == 1008


def test_ws_rejected_without_ticket(raw_client: TestClient):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with raw_client.websocket_connect("/ws/dashboard"):
            pass
    assert excinfo.value.code == 1008


def test_anonymous_cannot_read_agent_context(raw_client: TestClient):
    assert raw_client.get("/openfdd-agent/context").status_code == 401


def test_playground_rejects_import_os(client: TestClient, integrator_headers: dict[str, str]):
    r = client.post(
        "/api/playground/test-rule",
        json={
            "code": "import os\nimport pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.greater(table['SAT'], 50)\n",
            "config": {},
            "limit": 5,
        },
        headers=integrator_headers,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_playground_row_timeout_returns_error_event(monkeypatch: pytest.MonkeyPatch):
    import sys
    import time

    import pyarrow as pa

    monkeypatch.delenv("OFDD_PLAYGROUND_INPROCESS", raising=False)
    monkeypatch.setenv("OFDD_PLAYGROUND_SUBPROCESS", "1")
    monkeypatch.setenv("OFDD_PLAYGROUND_TIMEOUT_S", "2")
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge import playground  # noqa: E402

    table = pa.table({"SAT": pa.array([72.0], type=pa.float64())})
    code = (
        "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n"
        "    while True:\n        pass\n    return pc.greater(table['SAT'], 0)\n"
    )
    started = time.time()
    result = playground.run_arrow_table(code, table, {})
    assert time.time() - started < 25.0
    assert "timed out" in str(result.get("error", "")).lower()


def test_playground_huge_print_truncated(client: TestClient, integrator_headers: dict[str, str]):
    r = client.post(
        "/api/playground/test-rule",
        json={
            "code": "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    print(\"x\" * 20000)\n    return pc.greater(table[\"SAT\"], 0)\n",
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


def test_bacnet_write_bad_priority(
    client: TestClient,
    integrator_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv("OFDD_ENABLE_BACNET_WRITE", "1")
    allow = tmp_path / "bacnet"
    allow.mkdir(parents=True)
    (allow / "write_allowlist.json").write_text(
        '{"writes":[{"device_instance":1001,"object_identifier":"analog-value,1","property_identifier":"present-value"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr("openfdd_bridge.bacnet_write_guard.workspace_dir", lambda: tmp_path)
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
