"""Permanent EQ-VOCAB + ECM-ADAPT + Pages parity tests."""

from __future__ import annotations

import json
from pathlib import Path

from open_fdd.ecm_engineering.eq_vocab import (
    EQ_VOCAB_VERSION,
    docs_vocab_paths,
    load_quantity_schema,
    load_vocab_ttl,
    validate_engineering_quantity,
)
from open_fdd.ecm_engineering.model_adapter import adapt_model_to_calculator


def _electrical_kw(qid: str = "q-elec-1") -> dict:
    return {
        "schema_version": EQ_VOCAB_VERSION,
        "quantity_id": qid,
        "equipment_id": "AHU_1",
        "building_id": "SYNTH_ECM_1",
        "tenant_id": "acme",
        "property": "ratedElectricalInputPower",
        "numeric_value": 18.5,
        "unit_code": "kW",
        "quantity_kind": "ElectricalPower",
        "value_basis": "Rated",
        "source_type": "nameplate",
        "review_status": "Reviewed",
    }


def test_vocab_ttl_declares_version_and_core_properties():
    ttl = load_vocab_ttl()
    assert 'ofdd:vocabVersion "ofdd_engineering_quantities_v1"' in ttl
    assert "ofdd:ratedElectricalInputPower" in ttl
    assert "ofdd:EngineeringQuantity" in ttl
    assert "project-haystack.org" not in ttl  # do not mint inside Haystack NS


def test_quantity_schema_const_version():
    schema = load_quantity_schema()
    assert schema["properties"]["schema_version"]["const"] == EQ_VOCAB_VERSION


def test_docs_vocab_parity_with_package_data():
    """Pages copies must not drift from the wheel-authoritative files."""
    pkg_ttl = Path(__file__).resolve().parents[2] / (
        "open_fdd/ecm_engineering/data/ofdd_engineering_quantities_v1.ttl"
    )
    pkg_schema = Path(__file__).resolve().parents[2] / (
        "open_fdd/ecm_engineering/data/ofdd_engineering_quantities_v1.schema.json"
    )
    docs_ttl, docs_schema = docs_vocab_paths()
    assert docs_ttl.read_text(encoding="utf-8") == pkg_ttl.read_text(encoding="utf-8")
    assert docs_schema.read_text(encoding="utf-8") == pkg_schema.read_text(
        encoding="utf-8"
    )


def test_validate_quantity_rejects_kind_mismatch_and_nonfinite():
    bad = _electrical_kw()
    bad["quantity_kind"] = "ThermalPower"
    issues = validate_engineering_quantity(bad)
    assert any("incompatible" in i for i in issues)

    bad2 = _electrical_kw()
    bad2["numeric_value"] = float("nan")
    assert any("finite" in i for i in validate_engineering_quantity(bad2))


def test_fan_affinity_adapter_known_answer():
    out = adapt_model_to_calculator(
        "fan_affinity",
        [_electrical_kw()],
        {
            "hours": 4000.0,
            "baseline_speed_fraction": 1.0,
            "proposed_speed_fraction": 0.8,
            "power_exponent": 3.0,
        },
    )
    assert out.ok is True
    assert out.result is not None
    # 18.5 * 1^3 * 4000 - 18.5 * 0.8^3 * 4000
    expected = 18.5 * 4000.0 * (1.0 - 0.8**3)
    assert abs(out.result["savings_kwh"] - expected) < 1e-6
    assert out.selected_quantity_ids == ["q-elec-1"]


def test_schedule_reduction_adapter():
    out = adapt_model_to_calculator(
        "schedule_reduction",
        [_electrical_kw("q-sched")],
        {"baseline_annual_hours": 5000.0, "proposed_annual_hours": 3500.0},
    )
    assert out.ok is True
    assert abs(out.result["savings_kwh"] - (18.5 * 1500.0)) < 1e-9


def test_thermal_kw_rejected_for_electrical_input():
    thermal = _electrical_kw("q-thermal")
    thermal["property"] = "ratedCoolingCapacity"
    thermal["quantity_kind"] = "ThermalPower"
    thermal["unit_code"] = "kW"
    out = adapt_model_to_calculator(
        "fan_affinity",
        [thermal],
        {
            "hours": 1000.0,
            "baseline_speed_fraction": 1.0,
            "proposed_speed_fraction": 0.9,
        },
    )
    assert out.ok is False
    assert any(i.code == "missing_quantity" for i in out.missing_evidence)


def test_kw_per_ton_capacity_only_missing_ton_hours():
    cool = {
        "schema_version": EQ_VOCAB_VERSION,
        "quantity_id": "q-cool",
        "property": "ratedCoolingCapacity",
        "numeric_value": 120.0,
        "unit_code": "kW",
        "quantity_kind": "ThermalPower",
        "value_basis": "Design",
        "source_type": "design_document",
        "review_status": "Reviewed",
    }
    out = adapt_model_to_calculator(
        "kw_per_ton_improvement",
        [cool],
        {"baseline_kw_per_ton": 0.7, "proposed_kw_per_ton": 0.55},
    )
    assert out.ok is False
    codes = {i.code for i in out.missing_evidence}
    assert "missing_scenario" in codes
    assert "capacity_only" in codes


def test_kw_per_ton_with_scenario_runs():
    out = adapt_model_to_calculator(
        "kw_per_ton_improvement",
        [],
        {
            "annual_ton_hours": 1_000_000.0,
            "baseline_kw_per_ton": 0.7,
            "proposed_kw_per_ton": 0.55,
        },
    )
    assert out.ok is True
    assert abs(out.result["savings_kwh"] - 150_000.0) < 1e-6


def test_adapter_round_trip_json():
    out = adapt_model_to_calculator(
        "fan_affinity",
        [_electrical_kw()],
        {
            "hours": 100.0,
            "baseline_speed_fraction": 1.0,
            "proposed_speed_fraction": 1.0,
        },
    )
    payload = out.to_dict()
    assert json.loads(json.dumps(payload))["ok"] is True
