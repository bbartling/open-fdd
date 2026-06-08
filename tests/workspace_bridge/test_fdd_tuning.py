from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_build_assignments_infers_site_from_equipment():
    from openfdd_bridge.rule_bindings import build_assignments_view

    model = {
        "sites": [{"id": "acme", "name": "Acme"}],
        "equipment": [{"id": "rtu-01", "site_id": "acme", "name": "RTU-01"}],
        "points": [
            {
                "id": "1100-analog-output-1",
                "equipment_id": "rtu-01",
                "name": "Fan CMD",
                "bacnet_device_id": 1100,
            }
        ],
    }
    rules = [
        {
            "id": "r1",
            "name": "run hours",
            "enabled": True,
            "bindings": {"point_ids": ["1100-analog-output-1"]},
        }
    ]
    view = build_assignments_view(model, rules, site_id="acme")
    assert len(view["points"]) == 1
    assert view["points"][0]["bound_rules"][0]["rule_id"] == "r1"


def test_fdd_runner_script_error_uses_table_rows(monkeypatch: pytest.MonkeyPatch):
    import pyarrow as pa

    from openfdd_bridge import fdd_runner

    table = pa.table({"timestamp": [1, 2, 3], "SAT": [70.0, 71.0, 72.0]})
    monkeypatch.setattr(
        "openfdd_bridge.playground.run_arrow_script",
        lambda *_a, **_k: {"ok": False, "error": "script blew up"},
    )
    rule = {
        "id": "script-err",
        "name": "Script err",
        "mode": "script",
        "code": "out = {}",
        "config": {},
        "enabled": True,
    }
    run = fdd_runner._run_one(  # noqa: SLF001
        rule,
        "acme",
        limit=10,
        model={"sites": [{"id": "acme"}]},
        frame=table,
    )
    assert run["status"] == "error"
    assert run["rows"] == 3
    assert "df" not in run["error"]


def test_tuning_brief_endpoint(agent_client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import os

    from openfdd_bridge import fdd_results as fr

    doc = {
        "version": 1,
        "generated_at": "2026-06-01T00:00:00Z",
        "runs": [
            {
                "rule_id": "acme-zn-t-oob",
                "rule_name": "Zone OOB",
                "site_id": "acme",
                "status": "ok",
                "rows": 24,
                "flagged": 22,
                "fault_code": "VAV-C",
            },
            {
                "rule_id": "acme-ahu-run-hours",
                "rule_name": "Run hours",
                "site_id": "acme",
                "status": "error",
                "rows": 0,
                "flagged": 0,
                "error": "name 'df' is not defined",
            },
        ],
    }
    path = Path(os.environ["OFDD_DESKTOP_DATA_DIR"]) / "fdd_results.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(fr, "fdd_results_path", lambda: path)
    monkeypatch.setattr(
        "openfdd_bridge.fdd_tuning.compute_poll_throughput",
        lambda **_: {"ok": True, "status": "healthy", "keepup_ratio": 0.95, "enabled_points": 10},
    )
    r = agent_client.get("/api/building-agent/tuning-brief?site_id=acme")
    assert r.status_code == 200
    body = r.json()
    assert body["poll_ready_for_tuning"] is True
    kinds = {x["kind"] for x in body["recommendations"]}
    assert "rule_error" in kinds
    assert "threshold_review" in kinds
