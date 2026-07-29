"""Stage-1 ECM contracts + Stage-2 workbook + evidence validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_fdd.ecm_engineering.agent_cli import (
    cmd_import_energyplus_evidence,
    cmd_list_missing_inputs,
    cmd_list_workbook_inputs,
    cmd_propose_input_update,
)
from open_fdd.ecm_engineering.contracts import (
    AllocationStatus,
    ComparisonMode,
    EngineeringInput,
    InputRail,
    MeasureResultMeta,
    ResultScope,
    AdditiveStatus,
    SourceType,
    AssumptionMethod,
    validate_engineering_inputs,
    validate_measure_meta,
    validate_simulation_evidence,
)
from open_fdd.ecm_engineering.fixtures import (
    synthetic_evidence,
    synthetic_inputs_manifest,
    write_fixtures,
)
from open_fdd.ecm_engineering.stage2_workbook import (
    STAGE2_SHEET_ORDER,
    build_stage2_workbook,
    dual_rail_fixture_inputs,
)


def test_evidence_round_trip(tmp_path: Path) -> None:
    paths = write_fixtures(tmp_path)
    doc = json.loads(paths["evidence"].read_text(encoding="utf-8"))
    assert validate_simulation_evidence(doc) == []
    result = cmd_import_energyplus_evidence(paths["evidence"])
    assert result["ok"] is True
    assert result["measure_count"] == 2


def test_reject_physical_ahu_without_allocation() -> None:
    meta = MeasureResultMeta(
        measure_id="ECM-X",
        result_scope=ResultScope.PHYSICAL_AHU,
        allocation_status=AllocationStatus.NOT_ALLOCATED,
        comparison_mode=ComparisonMode.VS_COMMON_BASELINE,
        additive_status=AdditiveStatus.NON_ADDITIVE,
    )
    issues = validate_measure_meta(meta)
    assert any("allocation" in i for i in issues)


def test_reject_ep_labeled_measured() -> None:
    inp = EngineeringInput(
        input_id="ep_fan_hp",
        display_name="EP fan",
        value=10.0,
        unit="hp",
        rail=InputRail.ENERGYPLUS,
        source_type=SourceType.MEASURED,
        assumption_note="should still fail",
    )
    issues = validate_engineering_inputs([inp])
    assert any("measured" in i.lower() for i in issues)


def test_reject_estimated_hours_without_assumption_note() -> None:
    inp = EngineeringInput(
        input_id="ss_sched_hours_saved",
        display_name="hours",
        value=1000.0,
        unit="h",
        rail=InputRail.SPREADSHEET,
        source_type=SourceType.AGENT_INFERRED,
        assumption_note="",
    )
    issues = validate_engineering_inputs([inp])
    assert any("assumption_note" in i for i in issues)


def test_dual_rail_presence_in_fixture() -> None:
    ids = {i.input_id for i in dual_rail_fixture_inputs()}
    assert any(i.startswith("ss_") for i in ids)
    assert any(i.startswith("ep_") for i in ids)
    assert "ss_fan_hp" in ids and "ep_fan_hp" in ids


def test_list_inputs_and_propose(tmp_path: Path) -> None:
    paths = write_fixtures(tmp_path)
    listed = cmd_list_workbook_inputs(paths["inputs"])
    assert listed["ok"] is True
    assert listed["count"] >= 4
    missing = cmd_list_missing_inputs(paths["inputs"])
    assert missing["missing"] == []
    prop = cmd_propose_input_update(
        paths["inputs"],
        input_id="ss_fan_hp",
        value=30.0,
        reason="TAB update",
        assumption_note="Revised nameplate",
        dry_run=True,
    )
    assert prop["ok"] is True
    assert prop["action"]["dry_run"] is True
    assert prop["action"]["persisted"] is False


def test_evidence_rejects_bad_physical_ahu() -> None:
    doc = synthetic_evidence()
    doc["individual_measures"].append(
        {
            "measure_id": "ECM-BAD",
            "run_id": "r1",
            "baseline_run_id": "baseline-001",
            "comparison_mode": "vs_common_baseline",
            "result_scope": "physical_ahu",
            "allocation_status": "not_allocated",
        }
    )
    issues = validate_simulation_evidence(doc)
    assert any("physical_ahu" in i for i in issues)


def test_stage2_workbook_dual_rail(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "Stage2_ECM.xlsx"
    path = build_stage2_workbook(out, project_name="Test Project")
    assert path.is_file()
    wb = openpyxl.load_workbook(path)
    for sheet in STAGE2_SHEET_ORDER:
        assert sheet in wb.sheetnames
    inputs = wb["Inputs"]
    headers = [c.value for c in inputs[1]]
    assert "Assumption_Note" in headers
    assert "rail" in headers
    names = {dn.name for dn in wb.defined_names.values()}
    assert "Assumption_Note" in names
    assert "Inputs_Table" in names
    sidecar = path.with_suffix(".ecm_engineering_inputs.json")
    assert sidecar.is_file()
    man = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(i["input_id"].startswith("ss_") for i in man["inputs"])
    assert any(i["input_id"].startswith("ep_") for i in man["inputs"])


def test_synthetic_inputs_manifest_validates() -> None:
    man = synthetic_inputs_manifest()
    from open_fdd.ecm_engineering.contracts import EngineeringInput

    inputs = [
        EngineeringInput(
            input_id=d["input_id"],
            display_name=d["display_name"],
            value=d["value"],
            unit=d["unit"],
            rail=InputRail(d["rail"]),
            source_type=SourceType(d["source_type"]),
            assumption_note=d.get("assumption_note") or "",
            assumption_method=AssumptionMethod(d.get("assumption_method") or "unknown"),
            linked_measure_ids=list(d.get("linked_measure_ids") or []),
            source_reference=d.get("source_reference") or "",
        )
        for d in man["inputs"]
    ]
    assert validate_engineering_inputs(inputs) == []
