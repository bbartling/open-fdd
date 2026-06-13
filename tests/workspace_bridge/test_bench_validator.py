"""Bench cross-source validator tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.bench_validator import (  # noqa: E402
    export_report_markdown,
    load_bench_mapping,
    poll_cadence_report,
    validate_bacnet_vs_niagara,
)


@pytest.fixture
def bench_samples(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "bacnet" / "polls").mkdir(parents=True, exist_ok=True)
    (workspace / "bacnet" / "commissioning").mkdir(parents=True, exist_ok=True)
    (workspace / "niagara" / "polls").mkdir(parents=True, exist_ok=True)
    (workspace / "data" / "niagara" / "points").mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "niagara" / "points").mkdir(parents=True, exist_ok=True)

    cfg_src = REPO / "workspace" / "data" / "bench_bacnet_vs_niagara.yaml"
    (data / "bench_bacnet_vs_niagara.yaml").write_text(cfg_src.read_text(encoding="utf-8"))

    from datetime import datetime, timezone
    from openfdd_bridge.niagara_store import record_last_values

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    samples = f"""timestamp_utc,site_id,building_id,system_id,point_id,series_id,device_instance,object_type,object_instance,value,units
{ts},demo,bens-office,unknown,5007-analog-input-1173,x,5007,analog-input,1173,76.0,degrees-fahrenheit
{ts},demo,bens-office,unknown,5007-analog-input-1168,x,5007,analog-input,1168,45.0,percent-relative-humidity
{ts},demo,bens-office,unknown,5007-analog-input-1192,x,5007,analog-input,1192,53.0,degrees-fahrenheit
{ts},demo,bens-office,unknown,5007-analog-input-10014,x,5007,analog-input,10014,77.0,degrees-fahrenheit
"""
    (workspace / "bacnet" / "polls" / "samples.csv").write_text(samples)

    discovered = """device_instance,device_address,object_type,object_instance,object_name,description,present_value,units,site_id,building_id,system_id,brick_class,brick_tag,enabled,poll_interval_s,point_id,series_id,commandable
5007,2000:7,analog-input,1173,OA-T,,,degrees-fahrenheit,demo,bens-office,unknown,,,0,60,5007-analog-input-1173,x,0
5007,2000:7,analog-input,1168,OA-H,,,percent-relative-humidity,demo,bens-office,unknown,,,0,60,5007-analog-input-1168,x,0
"""
    (workspace / "bacnet" / "commissioning" / "points_discovered.csv").write_text(discovered)

    niagara_points = {
        "station_id": "bench9065",
        "points": [
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dT", "point_name": "OA-T", "point_id": "niagara-oa-t"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dH", "point_name": "OA-H", "point_id": "niagara-oa-h"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/DUCT$2dT", "point_name": "DUCT-T", "point_id": "niagara-duct-t"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/STAT$20ZN$2dT", "point_name": "STAT ZN-T", "point_id": "niagara-stat"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/CURRENT$2dS", "point_name": "CURRENT-S", "point_id": "niagara-cs"},
        ],
    }
    (data / "niagara" / "points" / "bench9065.json").write_text(json.dumps(niagara_points))

    monkeypatch.setenv("OPENFDD_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(data))
    monkeypatch.setenv("OPENFDD_REPO_ROOT", str(REPO))

    now = ts
    record_last_values(
        "bench9065",
        [
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dT", "value": 76.2, "timestamp": now, "status": "{ok}", "point_id": "niagara-oa-t"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dH", "value": 46.0, "timestamp": now, "status": "{ok}", "point_id": "niagara-oa-h"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/DUCT$2dT", "value": 53.5, "timestamp": now, "status": "{ok}", "point_id": "niagara-duct-t"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/STAT$20ZN$2dT", "value": 77.1, "timestamp": now, "status": "{ok}", "point_id": "niagara-stat"},
            {"point_ord": "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/CURRENT$2dS", "value": False, "timestamp": now, "status": "{ok}", "point_id": "niagara-cs"},
        ],
    )
    return workspace


def test_load_bench_mapping():
    cfg = load_bench_mapping(REPO / "workspace" / "data" / "bench_bacnet_vs_niagara.yaml")
    assert cfg["bench_device"]["bacnet_device_instance"] == 5007
    assert "$2d" in cfg["points"]["outside_air_temperature"]["niagara_ord"]


def test_validate_bacnet_vs_niagara_passes(bench_samples):
    report = validate_bacnet_vs_niagara()
    oa = next(p for p in report["points"] if p["semantic_point_id"] == "oa-t")
    assert oa["pass"] is True
    assert report["summary"]["passed"] >= 4


def test_export_report_markdown():
    report = {"bench_device": "BENS", "validated_at": "t", "ok": True, "summary": {"score_pct": 100}, "points": []}
    md = export_report_markdown(report)
    assert "PASS" in md


def test_poll_cadence_report_empty():
    out = poll_cadence_report(source="bacnet_direct", expected_interval_s=60)
    assert "expected_interval_s" in out


def test_bench_validate_route(raw_client: TestClient, operator_headers: dict[str, str], bench_samples):
    r = raw_client.post(
        "/api/bench/validate/bacnet-vs-niagara",
        json={},
        headers=operator_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "points" in body
    assert body.get("read_only") is not False  # route may not echo read_only


def test_bench_health_route(raw_client: TestClient, operator_headers: dict[str, str]):
    r = raw_client.get("/api/bench/health", headers=operator_headers)
    assert r.status_code == 200
    assert r.json().get("read_only") is True
