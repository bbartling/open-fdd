"""Explicit equipment context for run_all / run_rule and skip explanations (#1661)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from open_fdd.rules import run_all, run_rule, summarize

NORMAL_CSV = Path(__file__).resolve().parent / "fixtures" / "lbnl_sdahu" / "AHU_annual_2018-07-03_10.csv"


def _external():
    return pd.DataFrame(
        {"sat": [13.0] * 12, "fan_status": [1.0] * 12},
        index=pd.date_range("2026-01-05", periods=12, freq="5min", tz="UTC"),
    )


def test_unstamped_external_frame_accepts_an_explicit_type():
    frame = _external()
    before = Counter(r.status for r in run_all(frame))
    assert before == {"NOT_APPLICABLE_EQUIPMENT_TYPE": len(list(run_all(frame)))}
    results = run_all(frame, equipment_type="AHU", equipment_id="AHU-X", site_id="S1", building_id="B1")
    statuses = Counter(r.status for r in results)
    assert statuses["SKIPPED_MISSING_ROLES"] > 0
    assert {r.equipment_type for r in results} == {"AHU"}
    assert {(r.equipment_id, r.site_id, r.building_id) for r in results} == {("AHU-X", "S1", "B1")}
    assert frame.attrs == {}  # the caller's frame is not modified


def test_explicit_keywords_win_over_frame_attrs():
    frame = _external()
    frame.attrs.update({"equipment_type": "VAV", "equipment_id": "VAV-9"})
    attrs_only = run_all(frame)
    assert {r.equipment_type for r in attrs_only} == {"VAV"}
    explicit = run_all(frame, equipment_type="AHU")
    assert {r.equipment_type for r in explicit} == {"AHU"}
    assert {r.equipment_id for r in explicit} == {"VAV-9"}  # unspecified keys still come from attrs
    assert frame.attrs["equipment_type"] == "VAV"
    one = run_rule("FC1", _external(), equipment_type="AHU")
    assert one.equipment_type == "AHU" and one.status != "NOT_APPLICABLE_EQUIPMENT_TYPE"


def test_summarize_explains_an_all_skipped_run():
    untyped = summarize(run_all(_external()))
    assert untyped["all_skipped"] and untyped["assessed"] == 0
    assert "no equipment type" in untyped["explanation"] and "equipment_type=" in untyped["explanation"]
    typed = summarize(run_all(_external(), equipment_type="AHU"))
    assert typed["all_skipped"]
    assert "missing input roles" in typed["explanation"] and "most needed:" in typed["explanation"]
    assert typed["missing_roles"] and max(typed["missing_roles"].values()) >= 2
    assert typed["by_status"]["SKIPPED_MISSING_ROLES"] == sum(
        1 for r in run_all(_external(), equipment_type="AHU") if r.status == "SKIPPED_MISSING_ROLES"
    )


def test_summarize_is_quiet_when_rules_were_assessed():
    from open_fdd.ml.lbnl import load_sdahu_csv

    results = run_all(load_sdahu_csv(NORMAL_CSV))
    s = summarize(results)
    assert s["assessed"] > 0 and not s["all_skipped"] and s["explanation"] == ""
    assert s["equipment_types"] == ["AHU"] and s["total"] == len(results)
