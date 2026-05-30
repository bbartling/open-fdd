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

RULE_CODE = (
    "def evaluate(row, cfg, prev_row=None, rows=None):\n"
    "    sat = row.get('SAT') or row.get('temp')\n"
    "    return sat is not None and float(sat) > float(cfg.get('high', 50))\n"
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    return TestClient(create_app())


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


def test_batch_run_lights_check_engine(client: TestClient):
    save = client.post(
        "/api/rules/save",
        json={"name": "SAT high", "mode": "rule", "code": RULE_CODE, "config": {"high": 50}, "severity": "warning"},
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


def test_run_uses_data_source_label(client: TestClient):
    import os

    # Create a YAML engine rule under the tmp data dir.
    data_dir = Path(os.environ["OFDD_DESKTOP_DATA_DIR"]) / "rules"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sat.yaml").write_text(
        "name: sat_high\ntype: expression\nflag: sat_high_flag\n"
        "inputs:\n  SAT:\n    column: SAT\nexpression: \"SAT > 50\"\n",
        encoding="utf-8",
    )
    r = client.post("/api/rules/run", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "demo"
    assert "sat_high_flag" in body["flag_columns"]
