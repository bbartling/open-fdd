"""Tests for Open-FDD Central (offline, mocked edges)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from portfolio.central.edge_probes import _fdd_alerts_missing_equipment, validate_edge_readonly
from portfolio.central.fault_hours import fault_summary_from_validation
from portfolio.central.job_store import create_job, list_jobs, load_job
from portfolio.central.registry import list_edge_sites, touch_site
from portfolio.collector.collector import SiteConfig


def test_fdd_alerts_missing_equipment_detects_gap():
    faults = {
        "families": [
            {
                "faults": [
                    {
                        "source": "fdd",
                        "code": "AHU-C",
                        "model_context": {"equipment": {"name": ""}},
                    }
                ]
            }
        ]
    }
    assert _fdd_alerts_missing_equipment(faults) == ["AHU-C"]


def test_fdd_alerts_with_equipment_passes():
    faults = {
        "families": [
            {
                "faults": [
                    {
                        "source": "fdd",
                        "code": "AHU-C",
                        "model_context": {"equipment": {"name": "AHU-C", "type": "AHU"}},
                    }
                ]
            }
        ]
    }
    assert not _fdd_alerts_missing_equipment(faults)


def test_fault_summary_includes_equipment():
    validation = {
        "site_id": "acme",
        "checks": {
            "faults_status": {
                "body": {
                    "families": [
                        {
                            "label": "AHU-C",
                            "faults": [
                                {
                                    "source": "fdd",
                                    "code": "AHU-C",
                                    "title": "AHU SAT flatline",
                                    "severity": "warning",
                                    "model_context": {
                                        "equipment": {"name": "AHU-C", "type": "AHU"},
                                        "rule_id": "acme-sat-flatline-1h",
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }
    rows = fault_summary_from_validation(validation)
    assert rows[0]["equipment"] == "AHU-C"
    assert rows[0]["rule_id"] == "acme-sat-flatline-1h"


def test_validation_job_store(tmp_path: Path):
    job = create_job(site_id="acme", plan="one_off", data_dir=tmp_path)
    assert job["id"]
    loaded = load_job(job["id"], data_dir=tmp_path)
    assert loaded["site_id"] == "acme"
    assert len(list_jobs(data_dir=tmp_path)) == 1


def test_registry_touch(tmp_path: Path):
    sites_file = tmp_path / "sites.json"
    sites_file.write_text(
        json.dumps(
            {
                "sites": [
                    {
                        "site_id": "demo",
                        "name": "Demo",
                        "base_url": "http://127.0.0.1:8765",
                        "username": "agent",
                        "password": "x",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    touch_site("demo", checkin=True, traffic="green", data_dir=tmp_path)
    rows = list_edge_sites(sites_path=sites_file, data_dir=tmp_path)
    assert rows[0].site_id == "demo"
    assert rows[0].last_checkin_at


@patch("portfolio.central.edge_probes.login", return_value="tok")
@patch("portfolio.central.edge_probes.api_get")
def test_validate_edge_readonly_mock(mock_get, _login):
    def fake_get(_base, _token, path, **kw):
        if path == "/health":
            return {"openfdd_version": "3.0.33"}
        if path == "/health/stack":
            return {"image_tag": "3.0.33"}
        if path == "/api/model/health":
            return {"counts": {"duplicate_point_ids": 0, "duplicate_bacnet_device_instances": 0}}
        if path == "/api/bacnet/poll/status":
            return {"enabled_points": 100}
        if path == "/api/faults/status":
            return {
                "traffic": "yellow",
                "families": [
                    {
                        "faults": [
                            {
                                "source": "fdd",
                                "code": "VAV-E",
                                "model_context": {"equipment": {"name": "VAV-E"}},
                            }
                        ]
                    }
                ],
            }
        return {}

    mock_get.side_effect = fake_get
    site = SiteConfig(
        site_id="acme",
        name="Acme",
        base_url="http://127.0.0.1:8765",
        username="agent",
        password="secret",
    )
    out = validate_edge_readonly(site)
    assert out["ok"] is True
    assert out["traffic"] == "yellow"


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("docx") is None,
    reason="python-docx not installed",
)
def test_rcx_docx_builds():
    from portfolio.central.rcx_report import build_rcx_docx

    blob = build_rcx_docx(
        site_id="acme",
        site_name="Acme Lab",
        validation={"ok": True, "errors": [], "checks": {}},
        rollups=[{"site_id": "acme", "faults": {"active_by_code": {"AHU-C": 2}}}],
        warnings=["sample warning"],
    )
    assert blob[:2] == b"PK"


def test_central_api_health():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from portfolio.central.api import app

    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
