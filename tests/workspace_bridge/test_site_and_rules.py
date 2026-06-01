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

    path = write_source(rule_id="abc", name="SAT High", code="def evaluate(row, cfg, **kw):\n    return False\n")
    assert Path(path).is_file()
    assert "evaluate" in read_source(path)


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
