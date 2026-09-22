"""Permanent tests for ecm_context_v1 envelope + schedule/fan interaction."""

from __future__ import annotations

import json

from open_fdd.ecm_engineering.context_envelope import (
    ECM_CONTEXT_SCHEMA_VERSION,
    AssetKind,
    EcmContext,
    EquipmentAsset,
    GapItem,
    PointProvenance,
    ReadinessStatus,
    CalcResult,
    assess_screening_gaps,
    combine_schedule_then_fan_reset,
    ecm_context_from_dict,
    reject_incompatible_units,
    validate_ecm_context,
)
from open_fdd.ecm_engineering.contracts import SourceType
from open_fdd.ecm_engineering.provenance import EvidenceValue, ProvenanceClass


def _fan_pair_context(*, share_command: bool, with_proxy: bool = False) -> dict:
    supply_cmd = PointProvenance(
        role="fan-cmd",
        point_id="AHU1_SF_CMD",
        source_type=SourceType.BAS_DERIVED,
        units="%",
    )
    return_cmd = PointProvenance(
        role="fan-cmd",
        point_id="AHU1_SF_CMD" if share_command else "AHU1_RF_CMD",
        source_type=SourceType.BAS_DERIVED,
        units="%",
        proxy_of="AHU1_SF_CMD" if with_proxy else "",
        proxy_warning="Return fan uses supply command as proxy" if with_proxy else "",
    )
    ctx = EcmContext(
        schema_version=ECM_CONTEXT_SCHEMA_VERSION,
        building_id="SYNTH_ECM_1",
        tenant_id="acme",
        equipment_ids=["AHU_1"],
        equipment_types={"AHU_1": "ahu"},
        retrieved_at="2026-09-22T12:00:00Z",
        api_or_package_version="4.4.4",
        assets=[
            EquipmentAsset(
                asset_id="AHU1_SF",
                kind=AssetKind.SUPPLY_FAN,
                equipment_id="AHU_1",
                nameplate={
                    "hp": EvidenceValue(
                        25.0, ProvenanceClass.NAMEPLATE, source="TAB", method="nameplate"
                    )
                },
                command_point=supply_cmd,
                power_point=PointProvenance(
                    role="fan-power",
                    point_id="AHU1_SF_KW",
                    source_type=SourceType.MEASURED,
                    units="kW",
                ),
            ),
            EquipmentAsset(
                asset_id="AHU1_RF",
                kind=AssetKind.RETURN_FAN,
                equipment_id="AHU_1",
                nameplate={
                    "hp": EvidenceValue(
                        10.0, ProvenanceClass.NAMEPLATE, source="TAB", method="nameplate"
                    )
                },
                command_point=return_cmd,
                power_point=PointProvenance(
                    role="fan-power",
                    point_id="AHU1_RF_KW",
                    source_type=SourceType.MEASURED,
                    units="kW",
                ),
            ),
        ],
    )
    return ctx.as_dict()


def test_ecm_context_round_trip_and_schema() -> None:
    doc = _fan_pair_context(share_command=False)
    assert validate_ecm_context(doc) == []
    loaded = ecm_context_from_dict(doc)
    again = loaded.as_dict()
    assert again["schema_version"] == ECM_CONTEXT_SCHEMA_VERSION
    assert again["assets"][0]["command_point"]["point_id"] == "AHU1_SF_CMD"
    assert again["assets"][1]["command_point"]["point_id"] == "AHU1_RF_CMD"
    # JSON serializable
    json.dumps(again)


def test_shared_fan_command_without_proxy_fails() -> None:
    doc = _fan_pair_context(share_command=True, with_proxy=False)
    issues = validate_ecm_context(doc)
    assert any("shared" in i for i in issues)


def test_shared_fan_command_with_proxy_ok() -> None:
    doc = _fan_pair_context(share_command=True, with_proxy=True)
    assert validate_ecm_context(doc) == []


def test_missing_nameplate_and_tariff_gaps() -> None:
    ctx = EcmContext(
        schema_version=ECM_CONTEXT_SCHEMA_VERSION,
        building_id="SYNTH_ECM_1",
        tenant_id="acme",
        equipment_ids=["AHU_1"],
        retrieved_at="2026-09-22T12:00:00Z",
        assets=[
            EquipmentAsset(
                asset_id="AHU1_SF",
                kind=AssetKind.SUPPLY_FAN,
                equipment_id="AHU_1",
            )
        ],
    )
    assess_screening_gaps(ctx)
    codes = {g.code for g in ctx.missing_evidence}
    assert "missing_nameplate_power" in codes
    assert "missing_tariff" in codes
    assert any(g.code == "rebate_blocked_nameplate" for g in ctx.blocking_issues)
    assert ctx.tariff.monetary_available is False
    doc = ctx.as_dict()
    assert validate_ecm_context(doc) == []


def test_incompatible_units_rejected() -> None:
    assert reject_incompatible_units("hp", "kW") is not None
    assert reject_incompatible_units("°F", "°C") is not None
    assert reject_incompatible_units("kW", "kW") is None


def test_submission_ready_requires_human_review() -> None:
    doc = _fan_pair_context(share_command=False)
    doc["calc_result"] = CalcResult(
        calculator="fan_affinity",
        package_version="4.4.4",
        readiness=ReadinessStatus.SUBMISSION_READY,
        human_review=False,
    ).as_dict()
    issues = validate_ecm_context(doc)
    assert any("human_review" in i for i in issues)
    doc["calc_result"]["human_review"] = True
    assert validate_ecm_context(doc) == []


def test_schedule_then_fan_reset_no_double_count() -> None:
    result = combine_schedule_then_fan_reset(
        equipment_kw=20.0,
        baseline_annual_hours=6000.0,
        proposed_annual_hours=4000.0,
        design_kw=20.0,
        baseline_speed_fraction=0.9,
        proposed_speed_fraction=0.7,
    )
    assert result["combined_savings_kwh"] < result["naive_sum_savings_kwh"]
    assert result["double_count_delta_kwh"] > 0
    # Remaining-runtime fan savings must use proposed hours, not baseline.
    assert result["fan_on_remaining_hours"]["savings_kwh"] < result[
        "fan_on_baseline_hours_naive"
    ]["savings_kwh"]
