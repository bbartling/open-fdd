from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.main import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["auth_required"] is False


def test_playground_lint(client: TestClient):
    r = client.post(
        "/api/playground/lint",
        json={"code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_playground_test_rule(client: TestClient):
    code = """def evaluate(row, cfg, prev_row=None, rows=None):
    sat = row.get("SAT") or row.get("temp")
    return sat is not None and float(sat) > float(cfg.get("high", 75))
"""
    r = client.post(
        "/api/playground/test-rule",
        json={"code": code, "config": {"high": 75}, "limit": 50},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["rows"] > 0


def test_rules_run(client: TestClient):
    r = client.post(
        "/api/rules/run",
        json={"column_map": {"SAT": "SAT"}, "skip_missing_columns": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["flag_columns"]


def test_agent_context(client: TestClient):
    r = client.get("/openfdd-agent/context")
    assert r.status_code == 200
    assert "repo_root" in r.json()


def test_spa_index_when_built(client: TestClient):
    static_index = REPO / "workspace" / "api" / "static" / "app" / "index.html"
    if not static_index.is_file():
        return
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
