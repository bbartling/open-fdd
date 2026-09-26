"""Offline single-system AHU Typst pack from a tiny device folder."""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

from open_fdd.reporting.single_system_typst import build_single_system_report, write_econ_scatter

FIXTURE = Path(__file__).parent / "fixtures" / "ahu_typst_mini"


def _status(summary: dict, section: str, rule_id: str) -> str:
    rows = summary["devices"][0][section]
    return next(row["status"] for row in rows if row["rule_id"] == rule_id)


def test_single_system_report_sections_and_oracle(tmp_path):
    out = tmp_path / "out"
    result = build_single_system_report(
        FIXTURE,
        out,
        scope="single-system",
        methods=["zscore", "mad"],
        top_n=1,
        max_days=2,
    )
    typ = result.typ_path.read_text(encoding="utf-8")
    for heading in (
        "1. Data health",
        "2. Sensor validation",
        "3. Anomaly screening",
        "4. Duct static / FC1",
        "5. Economizer performance",
        "6. Economizer scatter",
    ):
        assert heading in typ
    assert "not FDD faults" in typ
    assert "delta_or_f" in typ
    assert "delta_mr_f" in typ
    assert "OAT - RAT" in typ
    assert "MAT - RAT" in typ
    assert "x = (OAT - MAT)" not in typ
    assert "y = (RAT - MAT)" not in typ
    assert "economizer_delta_scatter" in typ
    assert "BUILDING_100 Overview-mirrored" in typ
    assert result.devices == ["AHU_1"]
    assert (out / "figures" / "AHU_1_fc1.png").stat().st_size > 100
    assert (out / "figures" / "AHU_1_econ_scatter.png").stat().st_size > 100

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["scope"] == "single-system"
    health = {row["role"]: row for row in summary["devices"][0]["health"]}
    assert health["outside-air-temp"]["out_of_range"] >= 1
    assert _status(summary, "sensor_validation", "SV-RANGE") == "FAULT"
    assert _status(summary, "fc1", "FC1") == "FAULT"
    assert _status(summary, "economizer", "ECON-1") == "FAULT"


def test_building_scope_skips_non_ahu_child(tmp_path):
    root = tmp_path / "site"
    ahu = root / "AHU_1"
    vav = root / "VAV_1"
    shutil.copytree(FIXTURE, ahu)
    vav.mkdir()
    (vav / "history_wide.csv").write_text(
        "timestamp_utc,ZT\n2026-06-01T00:00:00Z,72\n",
        encoding="utf-8",
    )
    (vav / "column_map.json").write_text(
        json.dumps(
            {
                "equipType": "vav",
                "equip": "VAV_1",
                "points": {"zone-air-temp": "ZT"},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    result = build_single_system_report(
        root,
        out,
        scope="building",
        methods=["zscore"],
        top_n=1,
        max_days=1,
    )
    assert result.devices == ["AHU_1"]
    assert result.skipped == [{"folder": "VAV_1", "reason": "no AHU IO in column_map"}]
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["scope"] == "building"
    assert "VAV_1" in result.typ_path.read_text(encoding="utf-8")


def test_scatter_writer_calls_canonical_chart():
    source = inspect.getsource(write_econ_scatter)
    assert "build_economizer_delta_points" in source
    assert "economizer_delta_scatter" in source
    assert "OAT − MAT" not in source
    assert "RAT − MAT" not in source
