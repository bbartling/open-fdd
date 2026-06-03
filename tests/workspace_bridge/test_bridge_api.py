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

def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["auth_required"] is True


def test_playground_lint(client: TestClient, integrator_headers: dict[str, str]):
    r = client.post(
        "/api/playground/lint",
        json={"code": "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"},
        headers=integrator_headers,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_playground_test_rule(client: TestClient, integrator_headers: dict[str, str]):
    code = """def evaluate(row, cfg, prev_row=None, rows=None):
    sat = row.get("SAT") or row.get("temp")
    return sat is not None and float(sat) > float(cfg.get("high", 75))
"""
    r = client.post(
        "/api/playground/test-rule",
        json={"code": code, "config": {"high": 75}, "limit": 50},
        headers=integrator_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["rows"] > 0


def test_agent_context(client: TestClient, operator_headers: dict[str, str]):
    r = client.get("/openfdd-agent/context", headers=operator_headers)
    assert r.status_code == 200
    assert "repo_root" not in r.json()


def test_model_export_auto_site(
    client: TestClient,
    integrator_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_ID", "test-site")
    r = client.get("/api/model/export", headers=integrator_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["sites"]) == 1
    assert body["sites"][0]["id"] == "test-site"


def test_spa_index_when_built(client: TestClient):
    static_index = REPO / "workspace" / "api" / "static" / "app" / "index.html"
    if not static_index.is_file():
        return
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_assets_cache_control_when_built(client: TestClient):
    assets_dir = REPO / "workspace" / "api" / "static" / "app" / "assets"
    if not assets_dir.is_dir():
        return
    sample = next(assets_dir.glob("*"), None)
    if sample is None:
        return
    r = client.get(f"/assets/{sample.name}")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=31536000, immutable"
