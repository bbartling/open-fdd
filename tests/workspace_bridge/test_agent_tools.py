from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.main import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.delenv("OFDD_AGENT_ALLOW_APP_EDIT", raising=False)
    return TestClient(create_app())


def test_context_includes_model_and_tools(client: TestClient):
    r = client.get("/openfdd-agent/context")
    assert r.status_code == 200
    body = r.json()
    assert "model_summary" in body
    assert "tools" in body
    assert body["app_edit_enabled"] is False
    assert any(t["name"] == "model.add_site" for t in body["tools"])


def test_tool_builds_model(client: TestClient):
    site = client.post("/openfdd-agent/tool", json={"tool": "model.add_site", "args": {"name": "HQ"}})
    assert site.status_code == 200
    site_id = site.json()["result"]["site_id"]

    eq = client.post(
        "/openfdd-agent/tool",
        json={"tool": "model.add_equipment", "args": {"site_id": site_id, "name": "AHU-1", "equipment_type": "Air_Handling_Unit"}},
    )
    assert eq.status_code == 200

    model = client.get("/api/model/export").json()
    assert any(s["id"] == site_id for s in model["sites"])
    assert len(model["equipment"]) == 1


def test_tool_save_rule_and_batch(client: TestClient):
    code = (
        "def evaluate(row, cfg, prev_row=None, rows=None):\n"
        "    sat = row.get('SAT') or row.get('temp')\n"
        "    return sat is not None and float(sat) > 50\n"
    )
    saved = client.post(
        "/openfdd-agent/tool",
        json={"tool": "rules.save", "args": {"name": "agent rule", "code": code}},
    )
    assert saved.status_code == 200
    assert saved.json()["result"]["rule"]["saved_by"] == "agent"

    batch = client.post("/openfdd-agent/tool", json={"tool": "rules.run_batch", "args": {"limit": 200}})
    assert batch.status_code == 200
    assert batch.json()["result"]["rules_run"] == 1


def test_tool_run_batch_rejects_invalid_limit(client: TestClient):
    r = client.post("/openfdd-agent/tool", json={"tool": "rules.run_batch", "args": {"limit": "nope"}})
    assert r.status_code == 400
    assert "invalid limit" in r.json()["detail"].lower()


def test_app_edit_gated(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    blocked = client.post(
        "/openfdd-agent/tool",
        json={"tool": "app.edit_file", "args": {"path": "scratch/agent_test.txt", "contents": "hi"}},
    )
    assert blocked.status_code == 400

    monkeypatch.setenv("OFDD_AGENT_ALLOW_APP_EDIT", "1")
    allowed = client.post(
        "/openfdd-agent/tool",
        json={"tool": "app.edit_file", "args": {"path": "scratch/agent_test.txt", "contents": "hi"}},
    )
    assert allowed.status_code == 200
    assert allowed.json()["result"]["bytes"] == 2


def test_app_edit_rejects_path_traversal(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_AGENT_ALLOW_APP_EDIT", "1")
    r = client.post(
        "/openfdd-agent/tool",
        json={"tool": "app.edit_file", "args": {"path": "../escape.txt", "contents": "x"}},
    )
    assert r.status_code == 400


def test_unknown_tool(client: TestClient):
    r = client.post("/openfdd-agent/tool", json={"tool": "does.not_exist", "args": {}})
    assert r.status_code == 400
