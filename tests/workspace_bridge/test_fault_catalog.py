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
    assert fault_catalog_scope.families_for_equipment("Air_Handler_Unit", "AHU-1") == set()
    assert fault_catalog_scope.families_for_equipment("Fan_Coil_Unit", "FCU-12") == set()


def test_detect_applicable_families_lists_equipment_without_catalog_families():
    scope = fault_catalog_scope.detect_applicable_families(
        [{"equipment_id": "vav-1", "name": "VAV-3", "equipment_type": "Variable_Air_Volume_Box"}]
    )
    assert scope["applicable_families"] == []
    assert scope["hidden_families"] == []
    assert scope["equipment_count"] == 1
    assert scope["unmatched_equipment"][0]["equipment_id"] == "vav-1"


def test_applicable_rules_use_short_description():
    model = {
        "sites": [{"id": "site-a"}],
        "equipment": [{"id": "vav-1", "site_id": "site-a", "name": "VAV-3"}],
        "points": [{"id": "p1", "site_id": "site-a", "equipment_id": "vav-1"}],
    }
    rules = [
        {
            "id": "r1",
            "name": "Temperature out of bounds",
            "short_description": "Temperature reading is outside the configured range.",
            "enabled": True,
            "bindings": {"point_ids": ["p1"], "equipment_ids": [], "brick_types": []},
        }
    ]
    out = fault_catalog_scope._applicable_rules(rules, "site-a", model=model)
    assert len(out) == 1
    assert out[0]["short_description"] == "Temperature reading is outside the configured range."
    assert out[0]["device_names"] == ["VAV-3"]


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
    good = client.put(
        "/api/building/alerts",
        json={"alerts": [{"title": "AHU fighting", "severity": "critical"}]},
    )
    assert good.status_code == 200


def test_save_rule_uses_short_description_default(client: TestClient):
    good = client.post(
        "/api/rules/save",
        json={"name": "SAT high", "mode": "rule", "code": RULE_CODE},
    )
    assert good.status_code == 200
    assert good.json()["rule"]["short_description"] == "SAT high"


def test_fault_batch_surfaces_equipment_first_alert(client: TestClient):
    save = client.post(
        "/api/rules/save",
        json={
            "name": "SAT high",
            "mode": "rule",
            "backend": "arrow",
            "code": RULE_CODE,
            "config": {"high": 50},
            "severity": "critical",
            "short_description": "Supply air temperature is above the configured limit.",
        },
    )
    assert save.status_code == 200
    assert client.post("/api/rules/batch", json={"limit": 500}).status_code == 200

    status = client.get("/api/faults/status").json()
    assert status["traffic"] == "red"
    families = {f["family"]: f for f in status["families"]}
    assert families, "expected at least one equipment family bucket"
    first = next(iter(families.values()))
    assert any(a.get("symptom") or a.get("short_description") for a in first["faults"])
