"""Startup SPARQL model health — same checks as http_probes.check_model_sparql_health."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
API_ROOT = REPO / "workspace" / "api"
for p in (str(REPO), str(API_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def bridge_client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OFDD_BRIDGE_HOST", "127.0.0.1")
    monkeypatch.setenv("OFDD_AUTH_SECRET", "test-secret-key-32chars-minimum!!")
    monkeypatch.setenv("OFDD_INTEGRATOR_USER", "integrator")
    monkeypatch.setenv("OFDD_INTEGRATOR_PASSWORD", "msi")
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.main import create_app  # noqa: E402

    return TestClient(create_app())


def test_model_sparql_health_endpoints(bridge_client: TestClient):
    login = bridge_client.post("/api/auth/login", json={"username": "integrator", "password": "msi"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    bench = json.loads((REPO / "workspace/data/bench_import_model.json").read_text(encoding="utf-8"))
    assert bridge_client.post("/api/model/import", json={"payload": bench, "replace": True}, headers=headers).status_code == 200

    health = bridge_client.get("/api/model/health", headers=headers)
    assert health.status_code == 200
    h = health.json()
    assert h["configured"] is True
    assert h["ttl_exists"] is True
    assert h["status"] != "critical"

    tree = bridge_client.get("/api/model/tree", headers=headers)
    assert tree.status_code == 200
    t = tree.json()
    assert t["query_engine"] == "sparql"
    assert len(t["points"]) >= 1

    sites = bridge_client.get("/api/model/sites", headers=headers).json()
    site_id = sites.get("active_site_id") or sites["sites"][0]["site_id"]
    graph = bridge_client.get(f"/api/model/graph?site_id={site_id}", headers=headers)
    assert graph.status_code == 200
    assert graph.json()["query_engine"] == "sparql"
