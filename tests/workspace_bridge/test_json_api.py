"""JSON HTTP API driver tests."""

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
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data_dir))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app

    return TestClient(create_app())


def test_expand_env_string(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    env_file = tmp_path / "workspace" / "json_api.env.local"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("OPENWEATHER_API_KEY=secret-key\nOPENWEATHER_CITY=Madison,WI,US\n", encoding="utf-8")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(env_file.parent))
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.json_api_env import expand_env_string, load_json_api_env

    load_json_api_env(reload=True)
    url = expand_env_string(
        "https://api.openweathermap.org/data/2.5/weather?q=${ENV:OPENWEATHER_CITY}&appid=${ENV:OPENWEATHER_API_KEY}"
    )
    assert "secret-key" in url
    assert "Madison" in url
    assert "${" not in url


def test_extract_json_path():
    from openfdd_bridge.json_api_service import _extract_json_path

    data = {"title": "delectus aut autem", "user": {"name": "Leanne"}}
    assert _extract_json_path(data, "title") == "delectus aut autem"
    assert _extract_json_path(data, "user.name") == "Leanne"


def test_build_request_auth_bearer_and_basic():
    from openfdd_bridge.json_api_service import _build_request_auth

    headers, auth, verify = _build_request_auth(
        {
            "auth_type": "bearer",
            "bearer_token": "secret-key",
            "verify_tls": False,
        }
    )
    assert headers["Authorization"] == "Bearer secret-key"
    assert auth is None
    assert verify is False

    headers, auth, verify = _build_request_auth(
        {
            "auth_type": "basic",
            "basic_user": "ot",
            "basic_password": "pass",
        }
    )
    assert headers["Authorization"].startswith("Basic ")
    assert auth == ("ot", "pass")
    assert verify is True


def test_json_api_read_and_store_mocked(authed_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeResp:
        status_code = 200
        is_success = True

        def json(self):
            return {"title": "bench todo", "id": 1}

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, headers=None):
            self.last_headers = headers or {}
            return _FakeResp()

    fake_client = _FakeClient()

    monkeypatch.setattr("openfdd_bridge.json_api_service.httpx.Client", lambda **kwargs: fake_client)

    login = authed_client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    token = login.json()["token"]
    r = authed_client.post(
        "/api/json-api/read_and_store",
        json={
            "url": "https://jsonplaceholder.typicode.com/todos/1",
            "method": "GET",
            "json_path": "title",
            "label": "todo-title",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["present_value"] == "bench todo"
    assert body["ingest"]["ok"] is True

    tree = authed_client.get(
        "/api/json-api/driver/tree",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tree.status_code == 200
    assert len(tree.json()["devices"]) >= 1

    r2 = authed_client.post(
        "/api/json-api/request",
        json={
            "url": "https://example.local/status",
            "method": "GET",
            "json_path": "value",
            "auth_type": "bearer",
            "bearer_token": "bench-token",
            "verify_tls": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert fake_client.last_headers.get("Authorization") == "Bearer bench-token"


def test_json_api_driver_tree(tmp_path, monkeypatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.json_api_store import driver_tree, upsert_endpoint

    upsert_endpoint(
        {
            "url": "https://jsonplaceholder.typicode.com/todos/1",
            "method": "GET",
            "json_path": "title",
            "label": "todo-title",
            "enabled": True,
            "poll_interval_s": 300,
            "last_value": "hello",
        }
    )
    tree = driver_tree()
    assert tree["devices"][0]["host"] == "jsonplaceholder.typicode.com"
    assert tree["devices"][0]["points"][0]["present_value"] == "hello"


def test_openweather_preset_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "json_api.env.local").write_text(
        "OPENWEATHER_API_KEY=bench-key\nOPENWEATHER_CITY=Madison,WI,US\nOPENWEATHER_UNITS=imperial\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("OPENWEATHER_CITY", raising=False)
    monkeypatch.delenv("OPENWEATHER_UNITS", raising=False)
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data_dir))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app

    client = TestClient(create_app())

    class _FakeResp:
        status_code = 200
        is_success = True

        def json(self):
            return {
                "main": {"temp": 42.5, "humidity": 55},
                "weather": [{"description": "clear sky"}],
            }

    class _FakeClient:
        def __init__(self, **kwargs):
            self.last_url = ""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, headers=None):
            self.last_url = url
            return _FakeResp()

    fake = _FakeClient()
    monkeypatch.setattr("openfdd_bridge.json_api_service.httpx.Client", lambda **kwargs: fake)

    login = client.post("/api/auth/login", json={"username": "integrator", "password": "msi"})
    token = login.json()["token"]
    r = client.post(
        "/api/json-api/presets/openweather",
        json={"poll_interval_s": 300, "enabled": True, "poll_once": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert "bench-key" in fake.last_url
    tree = client.get(
        "/api/json-api/driver/tree",
        headers={"Authorization": f"Bearer {token}"},
    )
    labels = {p["label"] for d in tree.json()["devices"] for p in d["points"]}
    assert {"web-oat-t", "web-rh"} <= labels
    assert "web-weather-desc" not in labels


def test_json_api_presets_catalog(authed_client: TestClient):
    login = authed_client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    token = login.json()["token"]
    r = authed_client.get(
        "/api/json-api/presets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    ids = {p["id"] for p in body["presets"]}
    assert "jsonplaceholder-todo" in ids
    assert "open-meteo-bundle" in ids
    assert body["poll_intervals"][-1]["label"] == "1 hour"


def test_json_api_test_multi_sensor_mocked(authed_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeResp:
        status_code = 200
        is_success = True

        def json(self):
            return {"main": {"temp": 72.1, "humidity": 44}, "weather": [{"description": "clear"}]}

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url, headers=None):
            return _FakeResp()

    monkeypatch.setattr("openfdd_bridge.json_api_service.httpx.Client", lambda **kwargs: _FakeClient())

    login = authed_client.post(
        "/api/auth/login",
        json={"username": "integrator", "password": "msi"},
    )
    token = login.json()["token"]
    r = authed_client.post(
        "/api/json-api/test",
        json={
            "url": "https://example.com/weather",
            "method": "GET",
            "sensors": [
                {"json_path": "main.temp", "label": "oat"},
                {"json_path": "main.humidity", "label": "rh"},
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert len(body["sensors"]) == 2
    assert body["sensors"][0]["present_value"] == "72.1"


def test_list_endpoints_redacts_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.json_api_store import list_endpoints, upsert_endpoint

    upsert_endpoint(
        {
            "url": "https://gw.local/status",
            "method": "GET",
            "json_path": "value",
            "label": "status",
            "auth_type": "bearer",
            "bearer_token": "secret-token",
            "basic_password": "ignored",
        }
    )
    row = list_endpoints()["endpoints"][0]
    assert row["bearer_token"] == "***"
    assert row["basic_password"] == "***"
