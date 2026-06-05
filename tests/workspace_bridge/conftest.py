from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
for p in (str(REPO), str(API_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _reload_bridge_modules() -> None:
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def bridge_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "127.0.0.1")
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OFDD_AGENT_USER", "agent")
    monkeypatch.setenv("OFDD_AGENT_PASSWORD", "agent-secret")
    monkeypatch.delenv("OFDD_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("OFDD_PLAYGROUND_INPROCESS", "1")
    _reload_bridge_modules()


class _AuthedClient:
    """TestClient wrapper that sends integrator Bearer token by default."""

    def __init__(self, inner: TestClient, default_headers: dict[str, str]) -> None:
        self._inner = inner
        self._default_headers = default_headers

    def _headers(self, extra: dict[str, str] | None) -> dict[str, str]:
        merged = dict(self._default_headers)
        if extra:
            merged.update(extra)
        return merged

    def get(self, url: str, **kwargs):
        return self._inner.get(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def post(self, url: str, **kwargs):
        return self._inner.post(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def put(self, url: str, **kwargs):
        return self._inner.put(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def patch(self, url: str, **kwargs):
        return self._inner.patch(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def delete(self, url: str, **kwargs):
        return self._inner.delete(url, headers=self._headers(kwargs.pop("headers", None)), **kwargs)

    def websocket_connect(self, url: str, **kwargs):
        headers = self._headers(kwargs.pop("headers", None))
        if url.startswith("/ws/dashboard") and "ticket=" not in url:
            ticket_resp = self._inner.post("/api/auth/ws-ticket", headers=headers)
            if ticket_resp.status_code == 200:
                ticket = ticket_resp.json().get("ticket", "")
                if ticket:
                    headers = {**headers, "sec-websocket-protocol": f"ofdd.ws, {ticket}"}
        return self._inner.websocket_connect(url, headers=headers, **kwargs)


@pytest.fixture
def raw_client() -> TestClient:
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


@pytest.fixture
def client(raw_client: TestClient, integrator_headers: dict[str, str]) -> _AuthedClient:
    return _AuthedClient(raw_client, integrator_headers)


@pytest.fixture
def agent_client(raw_client: TestClient, agent_headers: dict[str, str]) -> _AuthedClient:
    return _AuthedClient(raw_client, agent_headers)


@pytest.fixture
def integrator_headers(raw_client: TestClient) -> dict[str, str]:
    login = raw_client.post("/api/auth/login", json={"username": "integrator", "password": "msi"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


@pytest.fixture
def operator_headers(raw_client: TestClient) -> dict[str, str]:
    login = raw_client.post("/api/auth/login", json={"username": "operator", "password": "changeme"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


@pytest.fixture
def agent_headers(raw_client: TestClient) -> dict[str, str]:
    login = raw_client.post("/api/auth/login", json={"username": "agent", "password": "agent-secret"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}
