from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge import fault_catalog  # noqa: E402
RULE_CODE = (
    "def evaluate(row, cfg, prev_row=None, rows=None):\n"
    "    sat = row.get('SAT') or row.get('temp')\n"
    "    return sat is not None and float(sat) > float(cfg.get('high', 50))\n"
)


def test_catalog_integrity():
    codes = fault_catalog.all_codes()
    assert codes, "catalog must not be empty"
    # codes globally unique and well-formed
    assert len(codes) == sum(len(b["codes"]) for b in fault_catalog.FAULT_CATALOG.values())
    for code, entry in codes.items():
        assert code == code.upper()
        assert entry["category"] in fault_catalog.CATEGORIES
        assert entry["severity"] in fault_catalog.SEVERITIES
        assert entry["title"]
        assert isinstance(entry["likely_causes"], list)
        assert isinstance(entry["suggested_checks"], list)


def test_expected_families_present():
    expected = {"AHU", "VAV", "HEATPUMP", "GEO", "CHILLER", "DATACENTER", "BUILDING"}
    assert expected <= set(fault_catalog.FAULT_CATALOG)


def test_validation_helpers():
    assert fault_catalog.is_valid_code("AHU-02")
    assert fault_catalog.is_valid_code("ahu-02")  # case-insensitive
    assert not fault_catalog.is_valid_code("ZZZ-99")
    assert not fault_catalog.is_valid_code("")
    assert fault_catalog.family_for_code("CH-01") == "CHILLER"
    assert fault_catalog.entry_for_code("DC-01")["category"] == "simultaneous_heat_cool"


def test_catalog_api(client: TestClient):
    r = client.get("/api/faults/catalog")
    assert r.status_code == 200
    body = r.json()
    assert set(body["categories"]) == set(fault_catalog.CATEGORIES)
    assert {f["family"] for f in body["families"]} >= {"AHU", "CHILLER"}


def test_tree_api(client: TestClient):
    r = client.get("/api/faults/tree")
    assert r.status_code == 200
    fams = {f["family"]: f for f in r.json()["families"]}
    ahu_cats = {c["category"] for c in fams["AHU"]["categories"]}
    assert "simultaneous_heat_cool" in ahu_cats


def test_public_check_engine_endpoints_no_auth_header(raw_client: TestClient):
    for path in (
        "/api/building/status",
        "/api/faults/status",
        "/health/stack",
        "/openfdd-agent/building-insight",
    ):
        r = raw_client.get(path)
        assert r.status_code == 200, path


def test_status_api_starts_green(client: TestClient):
    r = client.get("/api/faults/status")
    assert r.status_code == 200
    body = r.json()
    assert body["traffic"] == "green"
    assert body["model_configured"] is False
    assert body["alert_count"] == 0
    assert "families" in body


def test_unknown_code_rejected_on_alert(client: TestClient):
    bad = client.put(
        "/api/building/alerts",
        json={"alerts": [{"title": "x", "code": "ZZZ-99"}]},
    )
    assert bad.status_code == 400

    good = client.put(
        "/api/building/alerts",
        json={"alerts": [{"title": "AHU fighting", "severity": "critical", "code": "AHU-02"}]},
    )
    assert good.status_code == 200


def test_unknown_code_rejected_on_rule(client: TestClient):
    bad = client.post(
        "/api/rules/save",
        json={"name": "x", "mode": "rule", "code": RULE_CODE, "fault_code": "NOPE-1"},
    )
    assert bad.status_code == 400


def test_fault_code_groups_into_family_tree(client: TestClient):
    save = client.post(
        "/api/rules/save",
        json={
            "name": "SAT high",
            "mode": "rule",
            "code": RULE_CODE,
            "config": {"high": 50},
            "severity": "critical",
            "fault_code": "AHU-02",
        },
    )
    assert save.status_code == 200
    assert client.post("/api/rules/batch", json={"limit": 500}).status_code == 200

    status = client.get("/api/faults/status").json()
    assert status["traffic"] == "red"
    families = {f["family"]: f for f in status["families"]}
    assert "AHU" in families
    assert any(a.get("code") == "AHU-02" for a in families["AHU"]["faults"])
