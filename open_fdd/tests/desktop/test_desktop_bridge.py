from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from open_fdd.desktop_bridge.server import create_app


def test_desktop_bridge_health() -> None:
    app = create_app()
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json().get("status") == "ok"


def test_desktop_bridge_sites_and_sparql() -> None:
    app = create_app()
    client = TestClient(app)
    created = client.post("/sites", json={"name": "Test Site"})
    assert created.status_code == 200
    site_id = created.json()["id"]
    listed = client.get("/sites")
    assert listed.status_code == 200
    assert any(s.get("id") == site_id for s in listed.json())
    sparql = client.post(
        "/data-model/testing/query",
        json={
            "query": """PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT (COUNT(?s) AS ?count) WHERE { ?s a brick:Site . }"""
        },
    )
    assert sparql.status_code == 200
    body = sparql.json()
    assert "rows" in body
    defaults = client.get("/rules/defaults")
    assert defaults.status_code == 200
    assert defaults.json().get("rule_pack") == "ahu_vav"
    install = client.post("/rules/defaults/install")
    assert install.status_code == 200
    attach = client.post(f"/sites/{site_id}/rule-pack", json={"rule_pack": "ahu_vav"})
    assert attach.status_code == 200
    stats = client.get("/storage/timeseries/stats")
    assert stats.status_code == 200
    ttl_status = client.get("/model/ttl/status")
    assert ttl_status.status_code == 200
    purge = client.post("/storage/timeseries/purge", json={"source": None, "site_id": None, "prune_points": False})
    assert purge.status_code == 200


def test_desktop_bridge_csv_ingest_missing_file_returns_400() -> None:
    app = create_app()
    client = TestClient(app)
    missing_csv = "/not/a/real/path/missing.csv"
    res = client.post(
        "/ingest/csv",
        json={
            "site_id": "site-missing",
            "source": "csv",
            "csv_path": missing_csv,
        },
    )
    assert res.status_code == 400
    detail = res.json().get("detail", "")
    assert "CSV file not found" in detail
    assert "Use an absolute file path" in detail


def test_desktop_bridge_purge_can_prune_matching_points() -> None:
    app = create_app()
    client = TestClient(app)
    created = client.post("/sites", json={"name": "Purge Site"})
    assert created.status_code == 200
    site_id = created.json()["id"]

    imported = client.post(
        "/model/import",
        json={
            "replace": False,
            "payload": {
                "sites": [],
                "equipment": [],
                "points": [
                    {"id": "p1", "site_id": site_id, "metadata": {"source": "csv"}},
                    {"id": "p2", "site_id": site_id, "metadata": {"source": "weather"}},
                ],
            },
        },
    )
    assert imported.status_code == 200

    purge = client.post(
        "/storage/timeseries/purge",
        json={"source": "csv", "site_id": site_id, "prune_points": True},
    )
    assert purge.status_code == 200
    purge_body = purge.json()
    assert purge_body.get("points_removed") == 1

    exported = client.get("/model/export")
    assert exported.status_code == 200
    points = exported.json().get("points", [])
    point_ids = {str(p.get("id")) for p in points}
    assert "p1" not in point_ids
    assert "p2" in point_ids
