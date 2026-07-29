"""Synthetic fixtures for Stage-1 ECM contracts / evidence import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_fdd.ecm_engineering.contracts import EVIDENCE_SCHEMA_VERSION
from open_fdd.ecm_engineering.stage2_workbook import dual_rail_fixture_inputs


def synthetic_evidence() -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "project": {"id": "synth-1", "name": "Synthetic ECM Project"},
        "facility": {"id": "fac-1", "name": "Synthetic Facility", "area_ft2": 85000},
        "baseline": {"run_id": "baseline-001", "status": "calibrated"},
        "calibration": {"g14_pass_fail": "PASS", "note": "synthetic"},
        "model": {"idf_ref": "models/synth.idf", "energyplus_version": "23.2.0"},
        "weather": {"epw": "USA_IL_Chicago-OHare.epw", "amy_year": 2019},
        "equipment_autosizing": {
            "fans": [{"id": "AHU1_SUPPLY", "ep_fan_hp": 22.4, "source": "eio"}],
            "cooling": [{"id": "CHILLER1", "ep_cooling_tons": 180.0, "source": "eio"}],
        },
        "individual_measures": [
            {
                "measure_id": "ECM-DSP-RESET",
                "run_id": "meas-dsp-001",
                "baseline_run_id": "baseline-001",
                "comparison_mode": "vs_common_baseline",
                "result_scope": "whole_building",
                "allocation_status": "not_allocated",
                "hour_bases": {
                    "ep_dsp_reset_hours": 2100,
                    "ss_dsp_reset_hours": 2200,
                },
            },
            {
                "measure_id": "ECM-FAN-SCHED",
                "run_id": "meas-sched-001",
                "baseline_run_id": "baseline-001",
                "comparison_mode": "vs_common_baseline",
                "result_scope": "whole_building",
                "allocation_status": "not_allocated",
                "hour_bases": {
                    "ep_sched_hours_saved": 1085,
                    "ss_sched_hours_saved": 1200,
                },
            },
        ],
        "package_runs": [],
        "sequential_cascades": [],
        "run_artifacts": {"cascade_dir": "reports/cascade/synth"},
        "warnings": [],
    }


def synthetic_inputs_manifest() -> dict[str, Any]:
    return {
        "schema": "ecm_engineering_inputs_v1",
        "inputs": [i.as_dict() for i in dual_rail_fixture_inputs()],
    }


def write_fixtures(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence = out_dir / "ecm_simulation_evidence.json"
    inputs = out_dir / "ecm_engineering_inputs.json"
    evidence.write_text(json.dumps(synthetic_evidence(), indent=2) + "\n", encoding="utf-8")
    inputs.write_text(json.dumps(synthetic_inputs_manifest(), indent=2) + "\n", encoding="utf-8")
    return {"evidence": evidence, "inputs": inputs}


__all__ = [
    "synthetic_evidence",
    "synthetic_inputs_manifest",
    "write_fixtures",
]
