"""C1 Haystack RDF synthetic fixtures — presence and independent answers."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "scripts" / "fixtures" / "haystack_rdf"

REQUIRED = (
    "README.md",
    "synthetic_mapping_inventory.json",
    "synthetic_point_metadata_v1.json",
    "expected_c1_answers.json",
)


def test_c1_fixture_files_exist() -> None:
    for name in REQUIRED:
        assert (FIX / name).is_file(), f"missing {name}"


def test_expected_answers_match_inventory() -> None:
    inv = json.loads((FIX / "synthetic_mapping_inventory.json").read_text())
    exp = json.loads((FIX / "expected_c1_answers.json").read_text())
    assert inv["building_id"] == exp["fixture_building_id"]
    ids = {eq["equipment_id"] for eq in inv["equipment"]}
    assert ids == set(exp["inventory"]["equipment_ids"])
    assert len(inv["equipment"]) == exp["inventory"]["equipment_count"]
    vav_amb = next(e for e in inv["equipment"] if e["equipment_id"] == "VAV_CASE_1")
    assert "sat_sp" in vav_amb["ambiguous_roles"]
    assert vav_amb["parent_ahu"] is None
    missing = exp["inventory"]["missing_parent_ahu_equipment_ids"]
    assert "VAV_CASE_1" in missing


def test_unknown_unit_sidecar_documented() -> None:
    meta = json.loads((FIX / "synthetic_point_metadata_v1.json").read_text())
    assert meta["schema"] in (
        "openfdd_semantic_meta_v1",
        "openfdd_point_metadata_v1_sketch",
    )
    unknown = [p for p in meta["points"] if p.get("unit_status") == "unknown"]
    assert len(unknown) == 1
    exp = json.loads((FIX / "expected_c1_answers.json").read_text())
    assert exp["inventory"]["unknown_unit_points"][0]["column"] == unknown[0]["column"]
