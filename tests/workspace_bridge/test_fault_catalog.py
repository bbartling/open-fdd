from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
REPO = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge import fault_catalog, fault_catalog_scope  # noqa: E402

RULE_CODE = (
    "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n"
    "    high = float(cfg.get('high', 50))\n"
    "    return pc.greater(table['SAT'], high)\n"
)


def test_catalog_integrity():
    codes = fault_catalog.all_codes()
    assert codes, "catalog must not be empty"
    assert len(codes) == sum(len(b["codes"]) for b in fault_catalog.FAULT_CATALOG.values())
    for code, entry in codes.items():
        assert fault_catalog.CODE_PATTERN.match(code), f"code must be letter suffix: {code}"
        assert "-" in code and not any(ch.isdigit() for ch in code.split("-", 1)[1])
        assert entry["category"] in fault_catalog.CATEGORIES
        assert entry["severity"] in fault_catalog.SEVERITIES
        assert entry["title"]
        assert isinstance(entry["likely_causes"], list)
        assert isinstance(entry["suggested_checks"], list)
        assert isinstance(entry.get("cookbook_patterns"), list)


def test_expected_families_present():
    expected = {"AHU", "VAV", "HEATPUMP", "GEO", "CHILLER", "DATACENTER", "BUILDING"}
    assert expected <= set(fault_catalog.FAULT_CATALOG)


def test_validation_helpers():
    assert fault_catalog.is_valid_code("AHU-B")
    assert fault_catalog.is_valid_code("ahu-b")
    assert not fault_catalog.is_valid_code("ZZZ-ZZ")
    assert not fault_catalog.is_valid_code("")
    # Numeric suffix collides with equipment names — not valid catalog codes
    assert not fault_catalog.is_valid_code("VAV-03")
    assert not fault_catalog.is_valid_code("AHU-02")
    assert fault_catalog.normalize_code("VAV-03") == "VAV-C"
    assert fault_catalog.family_for_code("CH-A") == "CHILLER"
    assert fault_catalog.entry_for_code("DC-A")["category"] == "simultaneous_heat_cool"


def test_catalog_graph_links_patterns():
    graph = fault_catalog.catalog_graph()
    assert graph["version"] == fault_catalog.CATALOG_VERSION
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "VAV-C" in node_ids
    assert "pat:flatline_1h" in node_ids
    assert "cat:sensor_fault" in node_ids
    edges = {(e["from"], e["to"], e["relation"]) for e in graph["edges"]}
    assert ("VAV-C", "cat:sensor_fault", "has_category") in edges
    assert ("VAV-C", "pat:flatline_1h", "implemented_by") in edges
    assert ("VAV-C", "pat:oob_rolling", "implemented_by") in edges


def test_catalog_api(client: TestClient):
    r = client.get("/api/faults/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 2
    assert "cookbook_patterns" in body
    assert set(body["categories"]) == set(fault_catalog.CATEGORIES)
    assert {f["family"] for f in body["families"]} >= {"AHU", "CHILLER"}
    assert all(fault_catalog.CODE_PATTERN.match(c["code"]) for fam in body["families"] for c in fam["codes"])


def test_tree_api(client: TestClient):
    r = client.get("/api/faults/tree")
    assert r.status_code == 200
    fams = {f["family"]: f for f in r.json()["families"]}
    ahu_cats = {c["category"] for c in fams["AHU"]["categories"]}
    assert "simultaneous_heat_cool" in ahu_cats


def test_families_for_equipment_detection():
    assert "AHU" in fault_catalog_scope.families_for_equipment("Air_Handler_Unit", "AHU-1")
    assert "AHU" in fault_catalog_scope.families_for_equipment("", "AHU-1")
    assert "VAV" in fault_catalog_scope.families_for_equipment("Fan_Coil_Unit", "FCU-12")
    assert "HEATPUMP" in fault_catalog_scope.families_for_equipment("Heat_Pump", "HP roof")
    assert not fault_catalog_scope.families_for_equipment("Laboratory_Equipment", "Lab bench")


def test_detect_applicable_families_hides_heatpump_without_equipment():
    scope = fault_catalog_scope.detect_applicable_families(
        [{"equipment_id": "vav-1", "name": "VAV-3", "equipment_type": "Variable_Air_Volume_Box"}]
    )
    assert "VAV" in scope["applicable_families"]
    assert "BUILDING" in scope["applicable_families"]
    assert "HEATPUMP" in scope["hidden_families"]
    assert "AHU" in scope["hidden_families"]


def test_applicable_rules_pick_matched_fault_code():
    rules = [
        {
            "id": "r1",
            "name": "Multi",
            "enabled": True,
            "fault_codes": ["AHU-B", "VAV-C"],
        }
    ]
    out = fault_catalog_scope._applicable_rules(rules, {"VAV", "BUILDING"}, "site-a")
    assert len(out) == 1
    assert out[0]["fault_code"] == "VAV-C"
    assert out[0]["family"] == "VAV"


def test_applicable_api(client: TestClient):
    r = client.get("/api/faults/applicable")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "families" in body
    assert "query_engine" in body
    assert "hidden_families" in body
    assert "assigned_rules" in body


def test_graph_api(client: TestClient):
    r = client.get("/api/faults/graph")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == fault_catalog.CATALOG_VERSION
    assert body["nodes"]
    assert body["edges"]


def test_public_check_engine_endpoints_no_auth_header(raw_client: TestClient):
    for path in (
        "/api/building/status",
        "/api/building/snapshot",
        "/api/faults/status",
        "/health/stack",
    ):
        r = raw_client.get(path)
        assert r.status_code == 401, path
    for path in (
        "/openfdd-agent/building-insight",
        "/openfdd-agent/operational-brief",
        "/openfdd-agent/zone-temps",
        "/openfdd-agent/device-poll-health",
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
        json={"alerts": [{"title": "x", "code": "ZZZ-ZZ"}]},
    )
    assert bad.status_code == 400

    numeric = client.put(
        "/api/building/alerts",
        json={"alerts": [{"title": "zone 3", "code": "VAV-03"}]},
    )
    assert numeric.status_code == 400

    good = client.put(
        "/api/building/alerts",
        json={"alerts": [{"title": "AHU fighting", "severity": "critical", "code": "AHU-B"}]},
    )
    assert good.status_code == 200


def test_unknown_code_rejected_on_rule(client: TestClient):
    bad = client.post(
        "/api/rules/save",
        json={"name": "x", "mode": "rule", "code": RULE_CODE, "fault_code": "NOPE-X"},
    )
    assert bad.status_code == 400

    legacy = client.post(
        "/api/rules/save",
        json={"name": "x", "mode": "rule", "code": RULE_CODE, "fault_code": "VAV-03"},
    )
    assert legacy.status_code == 400


def test_fault_code_groups_into_family_tree(client: TestClient):
    save = client.post(
        "/api/rules/save",
        json={
            "name": "SAT high",
            "mode": "rule",
            "backend": "arrow",
            "code": RULE_CODE,
            "config": {"high": 50},
            "severity": "critical",
            "fault_code": "AHU-B",
        },
    )
    assert save.status_code == 200
    assert client.post("/api/rules/batch", json={"limit": 500}).status_code == 200

    status = client.get("/api/faults/status").json()
    assert status["traffic"] == "red"
    families = {f["family"]: f for f in status["families"]}
    # FDD alerts with equipment_name group under EQ:<id|name>, not generic AHU family.
    eq_family = "EQ:AHU-B"
    assert eq_family in families, f"expected equipment family {eq_family!r}, got {list(families)}"
    assert families[eq_family]["label"] == "AHU-B"
    assert any(a.get("code") == "AHU-B" for a in families[eq_family]["faults"])
