from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_ensure_default_site(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_ID", "edge-1")
    monkeypatch.setenv("OPENFDD_DEFAULT_SITE_NAME", "Edge box")
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.model_service import ModelService  # noqa: E402
    from openfdd_bridge.site_defaults import ensure_default_site  # noqa: E402
    from openfdd_bridge.ttl_service import TtlService  # noqa: E402

    svc = ModelService()
    sid = ensure_default_site(svc, TtlService())
    assert sid == "edge-1"
    model = svc.load()
    assert model["sites"][0]["id"] == "edge-1"
    assert model["sites"][0]["name"] == "Edge box"


def test_rule_source_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.rule_source import read_source, write_source  # noqa: E402

    path = write_source(
        rule_id="abc",
        name="SAT High",
        code="import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.greater(table['SAT'], 50)\n",
    )
    assert Path(path).is_file()
    assert "apply_faults_arrow" in read_source(path)


def test_read_source_resolves_stale_host_absolute_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Docker bridge may see host paths in rules_store; load by basename under rules_py/."""
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.rule_source import read_source, write_source  # noqa: E402

    path = write_source(
        rule_id="abc",
        name="SAT High",
        code="import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.greater(table['SAT'], 0)\n",
    )
    stale = f"/home/ben/open-fdd/workspace/data/rules_py/{Path(path).name}"
    assert Path(path).is_file()
    assert not Path(stale).is_file()
    assert "apply_faults_arrow" in read_source(stale)


def test_write_source_rejects_path_outside_rules_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.rule_source import rules_py_dir, write_source  # noqa: E402

    outside = tmp_path / "escape.py"
    path = write_source(
        rule_id="abc",
        name="Safe",
        code="x = 1\n",
        existing_path=str(outside),
    )
    assert Path(path).resolve().is_relative_to(rules_py_dir().resolve())
    assert not outside.is_file()


def test_column_map_for_rule_merges_scoped_over_base():
    from openfdd_bridge.data_loader import column_map_for_rule  # noqa: E402

    model = {
        "points": [
            {
                "id": "p1",
                "site_id": "s1",
                "external_id": "oa-h",
                "fdd_input": "SAT",
                "brick_type": "Supply_Air_Temperature_Sensor",
            }
        ]
    }
    rule = {
        "column_map": {"RULE_KEY": "some_col"},
        "bindings": {"point_ids": ["p1"]},
    }
    merged = column_map_for_rule(model, "s1", rule)
    assert merged["SAT"] == "oa-h"
    assert merged["Supply_Air_Temperature_Sensor"] == "oa-h"
    assert merged["RULE_KEY"] == "some_col"


def test_rule_store_prune_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.rule_store import RuleStore  # noqa: E402

    store = RuleStore()
    store.upsert(
        {
            "name": "Bound",
            "code": "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.greater(table['SAT'], 50)\n",
            "bindings": {
                "point_ids": ["p1", "p2"],
                "direct_point_ids": ["p1", "p2"],
                "equipment_ids": ["eq1"],
                "brick_types": [],
            },
        },
        saved_by="test",
    )
    n = store.prune_bindings(point_ids=["p1"], equipment_ids=["eq1"])
    assert n == 1
    rule = store.list_rules()[0]
    assert rule["bindings"]["point_ids"] == ["p2"]
    assert rule["bindings"]["direct_point_ids"] == ["p2"]
    assert rule["bindings"]["equipment_ids"] == []


def test_rule_store_prune_bindings_direct_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Prune must persist when only direct_point_ids changes (point_ids already empty)."""
    monkeypatch.setenv("OFDD_DESKTOP_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "openfdd_bridge" or name.startswith("openfdd_bridge."):
            del sys.modules[name]
    from openfdd_bridge.rule_store import RuleStore  # noqa: E402

    store = RuleStore()
    store.upsert(
        {
            "name": "Direct only",
            "code": "import pyarrow.compute as pc\n\ndef apply_faults_arrow(table, cfg, context=None):\n    return pc.greater(table['SAT'], 50)\n",
            "bindings": {
                "point_ids": [],
                "direct_point_ids": ["p-stale"],
                "equipment_ids": [],
                "brick_types": [],
            },
        },
        saved_by="test",
    )
    n = store.prune_bindings(point_ids=["p-stale"])
    assert n == 1
    b = store.list_rules()[0]["bindings"]
    assert b["direct_point_ids"] == []
