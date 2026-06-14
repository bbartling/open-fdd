from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

def test_model_site_and_ttl(client: TestClient):
    r = client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    assert r.status_code == 200
    assert r.json()["site_id"] == "s1"

    r_ttl = client.get("/api/model/ttl?save=false")
    assert r_ttl.status_code == 200
    assert "brick:Site" in r_ttl.text


def test_model_export_import(client: TestClient):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    payload = {
        "sites": [{"id": "s1", "name": "Demo Site"}],
        "equipment": [{"id": "e1", "site_id": "s1", "name": "AHU-1", "equipment_type": "Air_Handling_Unit"}],
        "points": [
            {
                "id": "p1",
                "site_id": "s1",
                "equipment_id": "e1",
                "external_id": "SAT",
                "brick_type": "Supply_Air_Temperature_Sensor",
                "fdd_input": "SAT",
            }
        ],
    }
    r = client.post("/api/model/import", json={"payload": payload, "replace": True})
    assert r.status_code == 200
    assert r.json()["sites"] == 1

    r2 = client.get("/api/model/export")
    assert r2.status_code == 200
    body = r2.json()
    assert len(body["points"]) == 1


def test_model_import_requires_site(client: TestClient):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    payload = {"sites": [], "equipment": [], "points": []}
    r = client.post("/api/model/import", json={"payload": payload, "replace": True})
    assert r.status_code == 400
    export = client.get("/api/model/export").json()
    assert export["sites"]
    assert export["sites"][0]["id"] == "s1"


def test_model_delete_point_and_equipment(client: TestClient):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    payload = {
        "sites": [{"id": "s1", "name": "Demo Site"}],
        "equipment": [{"id": "e1", "site_id": "s1", "name": "AHU-1", "equipment_type": "Air_Handling_Unit"}],
        "points": [
            {
                "id": "p1",
                "site_id": "s1",
                "equipment_id": "e1",
                "external_id": "SAT",
                "brick_type": "Supply_Air_Temperature_Sensor",
            },
            {
                "id": "p2",
                "site_id": "s1",
                "equipment_id": "e1",
                "external_id": "OAT",
                "brick_type": "Outside_Air_Temperature_Sensor",
            },
        ],
    }
    client.post("/api/model/import", json={"payload": payload, "replace": True})

    r = client.delete("/api/model/points/p1")
    assert r.status_code == 200
    assert r.json()["deleted"] == "p1"

    export = client.get("/api/model/export").json()
    assert len(export["points"]) == 1

    r2 = client.delete("/api/model/equipment/e1")
    assert r2.status_code == 200
    assert r2.json()["points_removed"] == 1

    export2 = client.get("/api/model/export").json()
    assert export2["equipment"] == []
    assert export2["points"] == []


def test_bacnet_sync_status(client: TestClient):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    r = client.get("/api/model/bacnet-sync")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "in_sync" in body
    assert "poll_enabled_count" in body


def test_model_tree(client: TestClient):
    client.post("/api/model/sites", json={"id": "s1", "name": "Demo Site"})
    payload = {
        "sites": [{"id": "s1", "name": "Demo Site"}],
        "equipment": [{"id": "e1", "site_id": "s1", "name": "AHU-1", "equipment_type": "Air_Handling_Unit"}],
        "points": [
            {
                "id": "p1",
                "site_id": "s1",
                "equipment_id": "e1",
                "external_id": "SAT",
                "brick_type": "Supply_Air_Temperature_Sensor",
            }
        ],
    }
    client.post("/api/model/import", json={"payload": payload, "replace": True})
    tree = client.get("/api/model/tree").json()
    assert tree["points"]
    assert "Supply_Air_Temperature_Sensor" in tree["brick_types"]


def test_model_health_and_building_status(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_ID", "test-site")
    r = client.get("/api/model/health")
    assert r.status_code == 200
    health = r.json()
    assert health["configured"] is True
    assert health["status"] == "ok"
    assert health["score"] == 100

    r2 = client.get("/api/building/status")
    assert r2.status_code == 200
    status = r2.json()
    assert status["check_engine"] is False
    assert status["model_configured"] is True
    assert status["alert_count"] == 0
    assert status["model_score"] == 100


def test_stack_health_not_mixed_into_faults(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_MCP_ENABLED", "1")

    r = client.get("/api/faults/status")
    assert r.status_code == 200
    body = r.json()
    assert body["traffic"] == "green"
    assert body["alert_count"] == 0
    titles = [f["title"] for fam in body["families"] for f in fam.get("faults", [])]
    assert not any("MCP" in t for t in titles)


def test_dashboard_websocket(client: TestClient):
    with client.websocket_connect("/ws/dashboard") as ws:
        payload = ws.receive_json()
        assert "stack" in payload
        assert "faults" in payload
        assert payload["faults"]["model_configured"] is False


def test_gl36_import_enriches_site_and_external_id(client: TestClient):
    """Acme GL36 exports often omit point site_id / external_id — import should infer them."""
    payload = {
        "site_id": "acme",
        "sites": [{"id": "acme", "name": "Acme Building"}],
        "equipment": [
            {
                "id": "acme-vm-bbartling-jci-vav-39",
                "name": "Jci Vav 39",
                "brick_type": "VAV",
                "site_id": "acme",
            }
        ],
        "points": [
            {
                "id": "39-analog-input-1106",
                "name": "ZN-T",
                "brick_type": "Zone_Air_Temperature_Sensor",
                "equipment_id": "acme-vm-bbartling-jci-vav-39",
                "brick_tag": "ZN-T",
            }
        ],
    }
    client.post("/api/model/import", json={"payload": payload, "replace": True})
    export = client.get("/api/model/export").json()
    pt = export["points"][0]
    assert pt["site_id"] == "acme"
    # external_id mirrors historian column (full point id when BACnet object suffix is ambiguous).
    assert pt["external_id"] == "39-analog-input-1106"


def test_model_health_skips_fdd_input_when_brick_type_set(client: TestClient):
    payload = {
        "sites": [{"id": "acme", "name": "Acme"}],
        "equipment": [{"id": "e1", "site_id": "acme", "name": "VAV-1", "brick_type": "VAV"}],
        "points": [
            {
                "id": "p1",
                "equipment_id": "e1",
                "external_id": "zn-t",
                "brick_type": "Zone_Air_Temperature_Sensor",
            }
        ],
    }
    client.post("/api/model/import", json={"payload": payload, "replace": True})
    health = client.get("/api/model/health").json()
    assert health["counts"]["missing_fdd_input"] == 0
    assert health["counts"]["missing_brick_type"] == 0


def test_building_alerts_put(client: TestClient):
    r = client.put(
        "/api/building/alerts",
        json={
            "alerts": [
                {
                    "severity": "warning",
                    "title": "SAT sensor drifting",
                    "detail": "Rule Lab flagged 12 rows above setpoint.",
                    "source": "agent",
                }
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "warning"

    r2 = client.get("/api/building/status")
    assert r2.status_code == 200
    titles = [a["title"] for a in r2.json()["alerts"]]
    assert "SAT sensor drifting" in titles


def test_building_status_with_unreadable_model(client: TestClient, tmp_path, monkeypatch):
    """Regression: unreadable model.json must not 500 the home dashboard."""
    import json

    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    unreadable = data / "model.json"
    unreadable.write_text('{"sites":[],"equipment":[],"points":[]}', encoding="utf-8")
    unreadable.chmod(0o000)
    fallback = data / "bench_dual_source_model.json"
    fallback.write_text(
        json.dumps(
            {
                "sites": [{"id": "demo", "name": "Demo"}],
                "equipment": [
                    {
                        "id": "bench-box",
                        "site_id": "demo",
                        "name": "Bench Box",
                        "equipment_type": "Air_Handling_Unit",
                    }
                ],
                "points": [
                    {
                        "id": "oa-t",
                        "site_id": "demo",
                        "equipment_id": "bench-box",
                        "name": "OA-T",
                        "brick_type": "Outside_Air_Temperature_Sensor",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))

    try:
        for path in ("/api/building/status", "/api/building/snapshot", "/api/faults/status"):
            r = client.get(path)
            assert r.status_code == 200, path
            body = r.json()
            assert body.get("ok", True) is not False or "traffic" in body or "stack" in body, path
        status = client.get("/api/building/status").json()
        assert status["model_configured"] is True
    finally:
        unreadable.chmod(0o644)
