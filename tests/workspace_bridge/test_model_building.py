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
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    return TestClient(create_app())


def test_model_export_import(client: TestClient):
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


def test_model_health_and_building_status(client: TestClient):
    r = client.get("/api/model/health")
    assert r.status_code == 200
    health = r.json()
    assert "score" in health
    assert health["status"] == "critical"

    r2 = client.get("/api/building/status")
    assert r2.status_code == 200
    status = r2.json()
    assert status["check_engine"] is True
    assert status["alert_count"] >= 1


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
