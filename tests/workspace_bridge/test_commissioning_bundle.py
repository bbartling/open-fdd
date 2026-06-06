from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_build_commissioning_export_includes_point_rule_ids():
    from openfdd_bridge.commissioning_bundle import build_commissioning_export

    model = {
        "sites": [{"id": "demo", "name": "Demo"}],
        "equipment": [{"id": "vav1", "site_id": "demo", "name": "VAV-1"}],
        "points": [
            {
                "id": "p1",
                "site_id": "demo",
                "equipment_id": "vav1",
                "brick_type": "Zone_Air_Temperature_Sensor",
                "external_id": "zn-t",
            },
            {"id": "p2", "site_id": "demo", "brick_type": "Outside_Air_Temperature_Sensor"},
        ],
    }
    rules = [
        {
            "id": "rule-a",
            "name": "Zone OOB",
            "enabled": True,
            "bindings": {"point_ids": ["p1"], "direct_point_ids": ["p1"]},
        }
    ]
    out = build_commissioning_export(model, rules)
    p1 = next(p for p in out["points"] if p["id"] == "p1")
    p2 = next(p for p in out["points"] if p["id"] == "p2")
    assert p1["fdd_rule_ids"] == ["rule-a"]
    assert "fdd_rule_ids" not in p2
    assert out["fdd_rules"][0]["id"] == "rule-a"


def test_apply_commissioning_import_from_point_rule_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]

    from openfdd_bridge.commissioning_bundle import apply_commissioning_import
    from openfdd_bridge.rule_store import RuleStore

    store = RuleStore()
    store.upsert(
        {
            "id": "rule-a",
            "name": "Zone OOB",
            "mode": "rule",
            "code": "def apply_faults_arrow(t,cfg,ctx=None):\n return False\n",
            "bindings": {},
        },
        saved_by="test",
    )

    payload = {
        "sites": [{"id": "demo", "name": "Demo"}],
        "equipment": [],
        "points": [
            {
                "id": "p1",
                "site_id": "demo",
                "brick_type": "Zone_Air_Temperature_Sensor",
                "fdd_rule_ids": ["rule-a"],
            }
        ],
    }
    result = apply_commissioning_import(payload)
    assert result["points"] == 1
    assert result["fdd_rules_updated"] >= 1
    rule = store.get("rule-a")
    assert rule is not None
    assert "p1" in (rule.get("bindings") or {}).get("point_ids", [])


def test_apply_commissioning_import_strips_fdd_rule_ids_from_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]

    from openfdd_bridge.commissioning_bundle import apply_commissioning_import
    from openfdd_bridge.model_service import ModelService

    payload = {
        "sites": [{"id": "demo", "name": "Demo"}],
        "equipment": [],
        "points": [{"id": "p1", "site_id": "demo", "fdd_rule_ids": ["rule-a"]}],
        "fdd_rules": [],
    }
    apply_commissioning_import(payload)
    model = ModelService().load()
    assert "fdd_rule_ids" not in (model.get("points") or [{}])[0]
