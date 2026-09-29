"""Stamp-only equipment selection for pandas cohorts and WattLab export."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from open_fdd.analytics.core import (
    _equipment_plant_group,
    _mech_cooling_type,
    economizer_free_cooling_diagnostics,
)
from open_fdd.analytics.site_model import equipment_type_from_id, resolve_equipment_type
from open_fdd.reporting.candidates import vav_fleet_size
from open_fdd.reporting.charts import _is_vav_candidate
from open_fdd.reporting.models import CandidateDetection
from open_fdd.reporting.scope import equipment_system, is_terminal_finding
from open_fdd.rules.runner import infer_equipment_kind

_WATT = Path(__file__).resolve().parents[2] / "tools" / "wattlab_export"
if str(_WATT) not in sys.path:
    sys.path.insert(0, str(_WATT))

from app.column_map_json import haystack_equip_type_to_cookbook  # noqa: E402
from app.equipment_kind import infer_parent_ahu_from_path, is_vav_equipment  # noqa: E402
from app.model_seed import build_model_seed_dict  # noqa: E402


def test_resolve_equipment_type_ignores_id_text():
    assert equipment_type_from_id("AHU_1") == "UNKNOWN"
    assert equipment_type_from_id("jci_vav_1") == "UNKNOWN"
    assert resolve_equipment_type("jci_ahu_1") == "UNKNOWN"
    assert resolve_equipment_type("AC_1", explicit="ahu") == "AHU"
    assert resolve_equipment_type("CHILLER_HEAT_PUMP", explicit="chiller") == "CHW_PLANT"
    assert resolve_equipment_type("OA_REF", role_map={"OA_REF": {"equipType": "weather"}}) == "WEATHER"
    assert resolve_equipment_type("jci_vav_1", explicit="vav") == "VAV"
    assert resolve_equipment_type("UV_1", explicit="unitVentilator") == "AHU"
    assert infer_equipment_kind("AHU_1") == "unknown"
    assert infer_equipment_kind("AC_1", equipment_type="ahu") == "ahu"


def test_plant_group_and_mech_type_follow_stamp():
    assert _equipment_plant_group("jci_ahu_1", "") is None
    assert _equipment_plant_group("HP_3", "") is None
    assert _equipment_plant_group("CHLR_1", "") is None
    assert _equipment_plant_group("AC_1", "ahu") == "air"
    assert _equipment_plant_group("HP_HEAT_PUMP_X", "chiller") == "chiller"
    assert _equipment_plant_group("TOWER_1", "coolingTower") == "chiller"
    assert _equipment_plant_group("VAV_1", "vav") is None
    assert _mech_cooling_type("", "CHILLER_1") == ""
    assert _mech_cooling_type("heatPump", "CHILLER_1") == "HP"


def test_economizer_membership_is_air_stamp():
    idx = pd.date_range("2026-06-01", periods=2, freq="h", tz="UTC")
    bare = pd.DataFrame({"fan-status": [1.0, 1.0]}, index=idx)
    ahu = bare.copy()
    ahu.attrs["equipment_type"] = "ahu"
    vav = bare.copy()
    vav.attrs["equipment_type"] = "vav"
    out = economizer_free_cooling_diagnostics(
        {"AHU_1": bare, "jci_ahu_1": ahu, "VAV_1": vav},
        {},
    )
    skipped = {row["equipment_id"] for row in out["skipped"]}
    metrics = set(out["metrics"]["equipment_id"]) if len(out["metrics"]) else set()
    assert "AHU_1" not in skipped and "AHU_1" not in metrics
    assert "VAV_1" not in skipped and "VAV_1" not in metrics
    assert "jci_ahu_1" in skipped


def test_reporting_cohorts_ignore_id_and_rule_prefix():
    assert equipment_system("", "SCHED-1") == "Other"
    assert equipment_system("", "VAV-1") == "Other"
    assert equipment_system("vav", "AHU-1") == "VAV"
    assert equipment_system("ahu", "VAV-1") == "AHU"
    assert _is_vav_candidate({"equipment_id": "VAV_1", "equipment_type": "", "rule_id": "VAV-1"}) is False
    assert _is_vav_candidate({"equipment_id": "jci_box", "equipment_type": "vav", "rule_id": "AHU-1"}) is True
    cands = [
        CandidateDetection("B", "VAV_GHOST", "AHU", "VAV-1", ""),
        CandidateDetection("B", "jci_vav_1", "VAV", "FC1", ""),
        CandidateDetection("B", "box_2", "vav", "SV-1", ""),
    ]
    assert vav_fleet_size(cands, {}) == 2
    assert is_terminal_finding(SimpleNamespace(systems=["AHU"])) is False
    assert is_terminal_finding(SimpleNamespace(systems=["VAV"])) is True


def test_wattlab_stamp_only():
    assert haystack_equip_type_to_cookbook("", "AHU_1") == "UNKNOWN"
    assert haystack_equip_type_to_cookbook("", "jci_vav_1") == "UNKNOWN"
    assert haystack_equip_type_to_cookbook("ahu", "jci_vav_1") == "AHU"
    assert haystack_equip_type_to_cookbook("vav", "AHU_1") == "VAV"
    assert is_vav_equipment({"equipment_id": "VAV_1"}) is False
    assert is_vav_equipment({"equipment_id": "AC_1", "equipType": "vav"}) is True
    assert infer_parent_ahu_from_path(Path("VAV_2_AHU_1"), Path(".")) is None
    seed = build_model_seed_dict(
        building_id="B1",
        schedule_payload={
            "equipment": {
                "AHU_1": {"weekday_start_hour": 6},
                "jci_ahu_1": {"equipment_type": "ahu", "weekday_start_hour": 7},
            }
        },
    )
    assert seed["schedule_hints"]["equipment_id"] == "jci_ahu_1"
    unstamped = build_model_seed_dict(
        building_id="B1",
        schedule_payload={"equipment": {"AHU_1": {"weekday_start_hour": 6}}},
    )
    assert unstamped["schedule_hints"] == {}
