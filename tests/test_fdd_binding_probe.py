"""FDD binding ref counting for post-deploy probes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_http_probes():
    path = REPO / "infra" / "ansible" / "scripts" / "http_probes.py"
    spec = importlib.util.spec_from_file_location("http_probes", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_rule_binding_ref_count_brick_scoped():
    hp = _load_http_probes()
    p, e, b, total = hp._rule_binding_ref_count(
        {"point_ids": [], "equipment_ids": [], "brick_types": ["Zone_Air_Temperature_Sensor"]}
    )
    assert p == 0
    assert e == 0
    assert b == 1
    assert total == 1


def test_rule_binding_ref_count_mixed():
    hp = _load_http_probes()
    p, e, b, total = hp._rule_binding_ref_count(
        {
            "point_ids": ["1100-analog-output-1"],
            "equipment_ids": ["acme-vm-bbartling-rtu-01"],
            "brick_types": ["Supply_Air_Temperature_Sensor"],
        }
    )
    assert total == 3
