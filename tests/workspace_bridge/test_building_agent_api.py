from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_poll_throughput_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "openfdd_bridge.poll_throughput.commission_poll_status",
        lambda: (200, {"enabled_points": 2, "samples": 2, "interval_s": 60, "at": "2026-06-01T12:00:00Z"}),
    )
    r = client.get("/api/analytics/poll-throughput?window_minutes=15")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "expected_all_polled_per_min" in body
    assert body["cycle_model"] == "all_enabled_each_cycle"


def test_site_memory_roundtrip(agent_client: TestClient):
    import os

    mem_root = Path(os.environ["OPENFDD_WORKSPACE_DIR"]) / "memory" / "sites"
    r = agent_client.put(
        "/api/sites/acme-test/memory?kind=memory",
        json={"content": "# Acme test memory\n", "mode": "replace"},
    )
    assert r.status_code == 200
    assert r.json()["site_id"] == "acme-test"
    g = agent_client.get("/api/sites/acme-test/memory?kind=memory")
    assert g.status_code == 200
    assert "Acme test memory" in g.json()["content"]
    assert (mem_root / "acme-test.md").is_file()


def test_fdd_results_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import os

    from openfdd_bridge import fdd_results as fr

    doc = {
        "version": 1,
        "generated_at": "2026-06-01T00:00:00Z",
        "runs": [{"rule_id": "r1", "site_id": "s1", "flagged": 3, "rows": 10}],
    }
    path = Path(os.environ["OFDD_DESKTOP_DATA_DIR"]) / "fdd_results.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(fr, "fdd_results_path", lambda: path)
    r = client.get("/api/fdd/results?site_id=s1")
    assert r.status_code == 200
    assert r.json()["summary"]["runs"] == 1


def test_ops_logs_endpoint(client: TestClient):
    r = client.get("/api/ops/logs?tail=20&include_docker=false")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "bridge_errors" in body


def test_building_agent_checkin(agent_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "openfdd_bridge.building_agent.compute_poll_throughput",
        lambda **_: {
            "ok": True,
            "status": "healthy",
            "keepup_ratio": 1.0,
            "enabled_points": 1,
            "observed_samples_per_min": 1.0,
        },
    )
    monkeypatch.setattr(
        "openfdd_bridge.building_agent.run_batch",
        lambda **_: {"ok": True, "rules_run": 0},
    )
    monkeypatch.setattr(
        "openfdd_bridge.building_agent.get_device_poll_snapshot",
        lambda **_: {"summary_sentence": "ok", "healthy_count": 0, "offline_equipment": [], "flaky_equipment": []},
    )
    monkeypatch.setattr(
        "openfdd_bridge.building_agent.collect_ops_logs",
        lambda **_: {"ok": True, "summary": {"healthy": True, "has_bridge_errors": False}},
    )
    r = agent_client.post(
        "/api/building-agent/checkin",
        json={"site_id": "checkin-site", "run_fdd_batch": False, "write_memory": True, "window_minutes": 15},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "summary" in body
    assert body["memory"]["site_id"] == "checkin-site"


def test_poll_throughput_with_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from openfdd_bridge.poll_throughput import compute_poll_throughput

    ws = tmp_path / "workspace"
    polls = ws / "bacnet" / "polls"
    polls.mkdir(parents=True)
    comm = ws / "bacnet" / "commissioning"
    comm.mkdir(parents=True)
    (comm / "points_discovered.csv").write_text(
        "point_id,device_instance,object_type,object_instance,enabled\n"
        "p1,1,analogInput,1,1\n",
        encoding="utf-8",
    )
    (comm / "points.csv").write_text(
        "point_id,enabled,poll_interval_s,series_id\np1,1,60,s1\n",
        encoding="utf-8",
    )
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    rows = []
    for i in range(5):
        ts = (now - timedelta(minutes=i)).isoformat()
        rows.append(f"{ts},site,bld,sys,p1,s1,1,analogInput,1,{70+i}")
    (polls / "samples.csv").write_text(
        "timestamp_utc,site_id,building_id,system_id,point_id,series_id,device_instance,object_type,object_instance,value\n"
        + "\n".join(rows),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(ws))
    monkeypatch.setattr(
        "openfdd_bridge.poll_throughput.commission_poll_status",
        lambda: (200, {"enabled_points": 1, "samples": 1, "interval_s": 60, "at": now.isoformat()}),
    )
    out = compute_poll_throughput(window_minutes=30)
    assert out["enabled_points"] == 1
    assert out["observed"]["rows_in_window"] >= 1
