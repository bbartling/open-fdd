"""output_units is declaration-only registry metadata (#1284 W5a, T1284-5)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import unit_contract_lib as ucl  # noqa: E402

METRIC = ucl.load_json(ucl.METRIC_UNITS)


def _registry(output_units: object | None) -> dict:
    rule = {
        "rule_id": "AVG",
        "sql_file": "avg.sql",
        "description": "avg",
        "output_columns": ["equipment_id", "avg_t", "pct"],
    }
    if output_units is not None:
        rule["output_units"] = output_units
    return {"rules": [rule]}


def _ok_units() -> dict:
    return {
        "avg_t": {"unit": "degC", "kind": "absolute_temperature"},
        "pct": {"unit": "percent_0_100", "kind": "percent"},
    }


def test_added_declaration_passes() -> None:
    master = _registry(None)
    branch = _registry(_ok_units())
    ucl.validate_output_units_declarations(METRIC, master, branch)
    assert ucl.registry_without_role_lists(master) == ucl.registry_without_role_lists(branch)


def test_unknown_unit_fails() -> None:
    units = _ok_units()
    units["avg_t"]["unit"] = "furlongs"
    with pytest.raises(AssertionError, match="furlongs"):
        ucl.validate_output_units_declarations(METRIC, _registry(None), _registry(units))


def test_unit_of_wrong_kind_fails() -> None:
    units = _ok_units()
    units["avg_t"]["unit"] = "Pa"
    with pytest.raises(AssertionError, match="belongs to air_pressure"):
        ucl.validate_output_units_declarations(METRIC, _registry(None), _registry(units))


def test_unknown_kind_fails() -> None:
    units = _ok_units()
    units["pct"]["kind"] = "vibes"
    with pytest.raises(AssertionError, match="not a metric_units.json quantity"):
        ucl.validate_output_units_declarations(METRIC, _registry(None), _registry(units))


def test_bare_unit_without_kind_fails() -> None:
    with pytest.raises(AssertionError, match="exactly unit and kind"):
        ucl.validate_output_units_declarations(
            METRIC, _registry(None), _registry({"avg_t": "degC"})
        )


def test_undeclared_column_fails() -> None:
    units = _ok_units()
    units["not_emitted"] = {"unit": "degC", "kind": "absolute_temperature"}
    with pytest.raises(AssertionError, match="not a declared output column"):
        ucl.validate_output_units_declarations(METRIC, _registry(None), _registry(units))


def test_changed_unit_is_a_value_change() -> None:
    branch = _ok_units()
    branch["avg_t"]["unit"] = "degF"
    with pytest.raises(AssertionError, match="declared unit changed"):
        ucl.validate_output_units_declarations(
            METRIC, _registry(_ok_units()), _registry(branch)
        )


def test_removed_declaration_fails() -> None:
    with pytest.raises(AssertionError, match="output_units removed"):
        ucl.validate_output_units_declarations(METRIC, _registry(_ok_units()), _registry(None))


def test_output_units_does_not_hide_other_edits() -> None:
    master = _registry(None)
    branch = _registry(_ok_units())
    branch["rules"][0]["description"] = "changed"
    assert ucl.registry_without_role_lists(master) != ucl.registry_without_role_lists(
        copy.deepcopy(branch)
    )
