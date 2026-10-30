"""Ambiguous SI kinds (L/s air vs water) must declare their imperial unit."""

from __future__ import annotations

import copy
import json

import pytest

from scripts.ci import unit_contract_lib as uc
from scripts.stress.si_cutover import product_sql_params as psp


def _metric() -> dict:
    return uc.load_json(uc.METRIC_UNITS)


def _catalog() -> dict:
    return json.loads(uc.TUNING.read_text(encoding="utf-8"))


def _flow_param(data: dict, rule_id: str, key: str) -> dict:
    for rule in data["rules"]:
        if rule["rule_id"] == rule_id:
            return rule["parameters"][key]
    raise KeyError(rule_id)


def test_catalog_flow_controls_declare_medium() -> None:
    uc.apply_tuning_catalog(_catalog())


def test_undeclared_flow_control_fails_unit_contract() -> None:
    data = _catalog()
    del _flow_param(data, "VAV-3", "flow_on_min")["ip_unit"]
    with pytest.raises(ValueError, match="must declare ip_unit"):
        uc.apply_tuning_catalog(data)


def test_flow_ip_unit_must_be_a_flow_unit() -> None:
    data = _catalog()
    _flow_param(data, "VAV-3", "flow_on_min")["ip_unit"] = "psi"
    with pytest.raises(ValueError, match="not in"):
        uc.apply_tuning_catalog(data)


def test_unambiguous_kind_rejects_ip_unit() -> None:
    with pytest.raises(ValueError, match="unambiguous"):
        uc.assert_ip_unit_declared(_metric(), "x", "air_pressure", {"ip_unit": "in_wc"})


def test_converter_maps_declared_medium() -> None:
    metric = _metric()
    data = _catalog()
    air = _flow_param(data, "VAV-3", "flow_on_min")
    water = _flow_param(data, "CHW-4", "flow_hi")
    assert psp._si_control_as_ip("VAV-3", "flow_on_min", air, metric)["unit"] == "cfm"
    assert psp._si_control_as_ip("CHW-4", "flow_hi", water, metric)["unit"] == "gpm"
    bare = copy.deepcopy(air)
    del bare["ip_unit"]
    with pytest.raises(ValueError, match="must declare ip_unit"):
        psp._si_control_as_ip("VAV-3", "flow_on_min", bare, metric)
