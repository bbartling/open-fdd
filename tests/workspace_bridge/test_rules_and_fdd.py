from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

RULE_CODE = (
    "import pyarrow.compute as pc\n\n"
    "def apply_faults_arrow(table, cfg, context=None):\n"
    "    col = 'SAT' if 'SAT' in table.column_names else 'temp'\n"
    "    return pc.greater(pc.cast(table[col], pa.float64()), float(cfg.get('high', 50)))\n"
)


def test_rules_routes_registered(client: TestClient):
    r = client.get("/api/rules/saved")
    assert r.status_code == 200
    assert r.json()["rules"] == []


def test_save_list_delete_rule(client: TestClient):
    r = client.post(
        "/api/rules/save",
        json={"name": "SAT high", "mode": "rule", "code": RULE_CODE, "config": {"high": 50}},
    )
    assert r.status_code == 200
    rule_id = r.json()["rule"]["id"]

    listing = client.get("/api/rules/saved").json()["rules"]
    assert any(rr["id"] == rule_id for rr in listing)

    d = client.delete(f"/api/rules/saved/{rule_id}")
    assert d.status_code == 200
    assert client.get("/api/rules/saved").json()["rules"] == []


def test_save_rule_with_short_description(client: TestClient):
    r = client.post(
        "/api/rules/save",
        json={
            "name": "Multi code",
            "mode": "rule",
            "code": RULE_CODE,
            "short_description": "Temperature reading is outside the configured range.",
        },
    )
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert rule["short_description"] == "Temperature reading is outside the configured range."

    src = client.get(f"/api/rules/saved/{rule['id']}/source")
    assert src.status_code == 200
    assert "apply_faults_arrow" in src.json()["code"]

    client.delete(f"/api/rules/saved/{rule['id']}")


def test_batch_run_lights_check_engine(client: TestClient):
    save = client.post(
        "/api/rules/save",
        json={
            "name": "SAT high",
            "mode": "rule",
            "backend": "arrow",
            "code": RULE_CODE,
            "config": {"high": 50},
            "severity": "warning",
        },
    )
    assert save.status_code == 200

    batch = client.post("/api/rules/batch", json={"limit": 500})
    assert batch.status_code == 200
    body = batch.json()
    assert body["rules_run"] == 1
    assert body["site_runs"] >= 1
    assert body["flagged_runs"] >= 1

    status = client.get("/api/building/status").json()
    assert status["fdd_alert_count"] >= 1
    assert status["check_engine"] is True
    assert any(a.get("source") == "fdd" for a in status["alerts"])


def test_playground_test_rule_uses_demo_frame(client: TestClient):
    r = client.post(
        "/api/playground/test-rule",
        json={"code": RULE_CODE, "config": {"high": 50}, "limit": 200},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("data_source") == "demo"
    assert body.get("flagged", 0) >= 0


def test_playground_test_rule_bad_indent_not_500(client: TestClient):
    bad = "def apply_faults_arrow(table, cfg, context=None):\nreturn False\n"
    r = client.post(
        "/api/playground/test-rule",
        json={"code": bad, "config": {}, "limit": 10},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False
    assert body.get("issues") or body.get("events")
