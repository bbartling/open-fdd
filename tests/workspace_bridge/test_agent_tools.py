from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

def test_context_includes_model_and_tools(agent_client: TestClient):
    r = agent_client.get("/openfdd-agent/context")
    assert r.status_code == 200
    body = r.json()
    assert "model_summary" in body
    assert "tools" in body
    assert body["app_edit_enabled"] is False
    assert any(t["name"] == "model.add_site" for t in body["tools"])
    assert "brick_model" in body
    assert "api_query_guide" in body
    assert "model.graph" in body.get("read_only_tools", [])


def test_tool_builds_model(agent_client: TestClient):
    site = agent_client.post("/openfdd-agent/tool", json={"tool": "model.add_site", "args": {"name": "HQ"}})
    assert site.status_code == 200
    site_id = site.json()["result"]["site_id"]

    eq = agent_client.post(
        "/openfdd-agent/tool",
        json={"tool": "model.add_equipment", "args": {"site_id": site_id, "name": "AHU-1", "equipment_type": "Air_Handling_Unit"}},
    )
    assert eq.status_code == 200

    model = agent_client.get("/api/model/export").json()
    assert any(s["id"] == site_id for s in model["sites"])
    assert len(model["equipment"]) == 1


def test_tool_save_rule_and_batch(agent_client: TestClient):
    code = (
        "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n"
        "    sat = row.get('SAT') or row.get('temp')\n"
        "    return sat is not None and float(sat) > 50\n"
    )
    saved = agent_client.post(
        "/openfdd-agent/tool",
        json={"tool": "rules.save", "args": {"name": "agent rule", "code": code}},
    )
    assert saved.status_code == 200
    assert saved.json()["result"]["rule"]["saved_by"] == "agent"

    batch = agent_client.post("/openfdd-agent/tool", json={"tool": "rules.run_batch", "args": {"limit": 200}})
    assert batch.status_code == 200
    assert batch.json()["result"]["rules_run"] == 1


def test_tool_run_batch_rejects_invalid_limit(agent_client: TestClient):
    r = agent_client.post("/openfdd-agent/tool", json={"tool": "rules.run_batch", "args": {"limit": "nope"}})
    assert r.status_code == 400
    assert "invalid limit" in r.json()["detail"].lower()


def test_app_edit_gated(agent_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    blocked = agent_client.post(
        "/openfdd-agent/tool",
        json={"tool": "app.edit_file", "args": {"path": "scratch/agent_test.txt", "contents": "hi"}},
    )
    assert blocked.status_code == 400

    monkeypatch.setenv("OFDD_AGENT_ALLOW_APP_EDIT", "1")
    allowed = agent_client.post(
        "/openfdd-agent/tool",
        json={"tool": "app.edit_file", "args": {"path": "scratch/agent_test.txt", "contents": "hi"}},
    )
    assert allowed.status_code == 200
    assert allowed.json()["result"]["bytes"] == 2


def test_app_edit_rejects_path_traversal(agent_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_AGENT_ALLOW_APP_EDIT", "1")
    r = agent_client.post(
        "/openfdd-agent/tool",
        json={"tool": "app.edit_file", "args": {"path": "../escape.txt", "contents": "x"}},
    )
    assert r.status_code == 400


def test_unknown_tool(agent_client: TestClient):
    r = agent_client.post("/openfdd-agent/tool", json={"tool": "does.not_exist", "args": {}})
    assert r.status_code == 400
