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
def authed_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_OPERATOR_USER", "operator")
    monkeypatch.setenv("OFDD_OPERATOR_PASSWORD", "changeme")
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app

    return TestClient(create_app())


def test_extract_json_path():
    from openfdd_bridge.json_api_service import _extract_json_path

    data = {"title": "delectus aut autem", "user": {"name": "Leanne"}}
    assert _extract_json_path(data, "title") == "delectus aut autem"
    assert _extract_json_path(data, "user.name") == "Leanne"


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
            return _FakeResp()

    monkeypatch.setattr("openfdd_bridge.json_api_service.httpx.Client", _FakeClient)

    login = authed_client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "changeme"},
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
