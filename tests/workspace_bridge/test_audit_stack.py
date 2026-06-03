from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture
def authed_integrator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("OFDD_AUDIT_LOG_PATH", str(log_dir / "audit.jsonl"))
    monkeypatch.setenv("OFDD_ERROR_LOG_PATH", str(log_dir / "error.jsonl"))
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "op")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_login_writes_audit(authed_integrator: TestClient, tmp_path: Path):
    audit_file = tmp_path / "logs" / "audit.jsonl"
    bad = authed_integrator.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "wrong"},
    )
    assert bad.status_code == 401
    assert audit_file.is_file()
    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    ev = json.loads(lines[-1])
    assert ev["event_type"] == "auth.login.failure"
    assert ev["client"]["ip"]


def test_stack_health_public_for_check_engine(authed_integrator: TestClient):
    """Stack traffic-light is public (same as /api/faults/status) for OT wall displays."""
    r = authed_integrator.get("/health/stack")
    assert r.status_code == 200
    body = r.json()
    assert "services" in body
    assert any(s["id"] == "bridge" for s in body["services"])

    login = authed_integrator.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    authed = authed_integrator.get(
        "/health/stack",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert authed.status_code == 200
    assert "services" in authed.json()


def test_audit_api_integrator_only(authed_integrator: TestClient):
    denied_no_token = authed_integrator.get("/api/audit/events?limit=5")
    assert denied_no_token.status_code == 401

    op_login = authed_integrator.post("/api/auth/login", json={"username": "operator", "password": "op"})
    assert op_login.status_code == 200
    op_token = op_login.json()["token"]
    denied_operator = authed_integrator.get(
        "/api/audit/events?limit=5",
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert denied_operator.status_code == 403

    login = authed_integrator.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    token = login.json()["token"]
    r = authed_integrator.get(
        "/api/audit/events?limit=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert "events" in r.json()
