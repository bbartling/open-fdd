"""Parity: open_fdd.role_candidates vs fdd_core haystack golden snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from open_fdd.role_candidates import haystack_point_to_role

GOLDEN = (
    Path(__file__).resolve().parents[2]
    / "crates/fdd_core/testdata/haystack_point_role_golden.json"
)

ISSUE_1405_CASES = [
    ("discharge-air-temperature-setpoint-active", "sat_sp"),
    ("duct-static-pressure-setpoint-active", "duct_static_sp"),
    ("hw-supply-temp", "hw_supply_t"),
    ("hw-return-temp", "hw_return_t"),
    ("zone-air-temp-setpoint", "zone_air_temp_sp"),
    ("zone-airflow-setpoint", "zone_airflow_sp"),
    ("return-air-humidity-local", "ra_h"),
]


def test_issue_1405_nf_tag_spellings_table() -> None:
    for tag, want in ISSUE_1405_CASES:
        assert haystack_point_to_role(tag) == want, f"tag {tag}"
    assert haystack_point_to_role("chw_supply_t") == "chw_supply_t"


def test_haystack_point_role_golden_snapshot_parity() -> None:
    rows: list[list[str]] = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for tag, want in rows:
        assert haystack_point_to_role(tag) == want, f"golden drift for tag {tag}"
