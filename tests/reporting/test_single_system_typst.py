"""Offline single-system AHU Typst pack from a tiny device folder."""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

import pytest

import pandas as pd

from open_fdd.reporting.single_system_typst import (
    anomaly_plain_checklist,
    attach_web_oat,
    build_single_system_report,
    dominant_month,
    filter_to_month,
    representative_week,
    write_econ_scatter,
)
from open_fdd.analytics.anomaly.io import load_device_folder
from open_fdd.reporting.single_system_typst import role_frame

FIXTURE = Path(__file__).parent / "fixtures" / "ahu_typst_mini"


def test_single_system_report_is_plotly_pack_without_histograms(tmp_path):
    out = tmp_path / "out"
    result = build_single_system_report(
        FIXTURE,
        out,
        scope="single-system",
        month="2026-06",
    )
    typ = result.typ_path.read_text(encoding="utf-8")
    assert typ.index("Sensor checks") < typ.index("Anomaly screening")
    assert typ.index("Anomaly screening") < typ.index("Executive summary")
    assert typ.index("Executive summary") < typ.index("RCx week")
    assert typ.index("RCx week") < typ.index("Confirmed faults")
    assert typ.index("Confirmed faults") < typ.index("Economizer delta scatter")
    assert "out of physical range" in typ or "stuck flat" in typ
    assert "looks normal" in typ or "needs a look" in typ
    assert "not equipment faults" in typ
    assert "histogram" not in typ.lower()
    assert "scoreboard" not in typ.lower()
    assert "z-score" not in typ.lower()
    assert "isolation forest" not in typ.lower()
    assert " stl " not in typ.lower()
    assert "delta_or_f" in typ
    assert "delta_mr_f" in typ
    assert "OAT - RAT" in typ
    assert "MAT - RAT" in typ
    assert "bottom-left" in typ
    assert "x = (OAT - MAT)" not in typ
    assert "BUILDING_100 Overview-mirrored" in typ
    assert "Rule:" in typ
    assert "Data:" in typ
    assert "FC1" in typ
    assert "ECON-1" in typ
    assert "FC2" not in typ
    assert result.devices == ["AHU_1"]
    pngs = list((out / "figures").glob("*.png"))
    assert pngs
    assert all("hist" not in path.name for path in pngs)
    assert (out / "figures" / "AHU_1_econ_scatter.png").stat().st_size > 100
    assert (out / "figures" / "AHU_1_fault_FC1.png").stat().st_size > 100
    assert not (out / "figures" / "AHU_1_fault_SV-RANGE.png").exists()
    assert any("rcx_" in path.name for path in pngs)

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["month"] == "2026-06"
    health = {row["role"]: row for row in summary["devices"][0]["health"]}
    assert health["outside-air-temp"]["out_of_range"] >= 1
    fault_ids = {row["rule_id"] for row in summary["devices"][0]["faults"]}
    assert "FC1" in fault_ids
    assert "ECON-1" in fault_ids
    assert "FC2" not in fault_ids
    assert "SV-RANGE" not in fault_ids
    summary_text = summary["devices"][0]["executive_summary"]
    assert summary_text.index("Sensor checks") < summary_text.index("Anomaly screening")
    assert any(row["outcome"] == "fail" for row in summary["devices"][0]["sensor_checks"])


def test_month_filter_drops_other_months():
    device = load_device_folder(FIXTURE)
    frame = role_frame(device)
    kept = filter_to_month(frame, "2026-06")
    assert len(kept) == len(frame)
    assert dominant_month(frame.index) == "2026-06"
    with pytest.raises(ValueError, match="no samples in 2026-05"):
        filter_to_month(frame, "2026-05")


def test_month_outside_history_fails_the_report(tmp_path):
    with pytest.raises(ValueError, match="no samples in 2026-04"):
        build_single_system_report(FIXTURE, tmp_path / "out", month="2026-04")


def test_web_oa_t_15min_reindexes_onto_5min_bas(tmp_path):
    """Open-Meteo ``web_oa_t`` at 15 min interpolates onto a 5-min BAS index."""
    index = pd.date_range("2026-04-01", periods=4, freq="5min", tz="UTC")
    frame = pd.DataFrame({"outside-air-temp": [50.0, 51.0, 52.0, 53.0]}, index=index)
    sidecar = tmp_path / "open_meteo_april.csv"
    sidecar.write_text(
        "timestamp_utc,web_oa_t\n"
        "2026-04-01T00:00:00Z,40\n"
        "2026-04-01T00:15:00Z,70\n",
        encoding="utf-8",
    )
    joined, source = attach_web_oat(frame, web_oat=sidecar)
    assert source == "csv"
    web = joined["web-outside-air-temp"]
    assert web.iloc[0] == pytest.approx(40.0)
    assert web.iloc[1] == pytest.approx(50.0)
    assert web.notna().all()
    assert joined["outside-air-temp"].iloc[0] == 50.0
    assert joined.attrs.get("oa_t_effective_source") == "web"
    assert joined["oa_t_effective"].iloc[0] == pytest.approx(40.0)


def test_pinned_rcx_week_is_seven_days_from_start():
    index = pd.date_range("2026-04-01", "2026-04-30 23:55", freq="5min", tz="UTC")
    frame = pd.DataFrame({"fan-status": 1}, index=index)
    window, label = representative_week(frame, week_start="2026-04-06")
    assert window.index.min() == pd.Timestamp("2026-04-06", tz="UTC")
    assert window.index.max() < pd.Timestamp("2026-04-13", tz="UTC")
    assert window.index.max() >= pd.Timestamp("2026-04-12", tz="UTC")
    assert label.startswith("2026-04-06")
    assert "2026-04-12" in label
    with pytest.raises(ValueError, match="no samples in the week starting 2026-05-01"):
        representative_week(frame, week_start="2026-05-01")


def test_pinned_week_outside_month_fails_the_report(tmp_path):
    with pytest.raises(ValueError, match="no samples in the week starting 2026-04-06"):
        build_single_system_report(
            FIXTURE,
            tmp_path / "out",
            month="2026-06",
            week="2026-04-06",
        )


def test_web_oat_csv_join_enables_meteo_rule(tmp_path):
    device = load_device_folder(FIXTURE)
    frame = role_frame(device)
    sidecar = tmp_path / "web_oat.csv"
    lines = ["timestamp_utc,web-outside-air-temp"]
    for stamp, oat in zip(frame.index, frame["outside-air-temp"], strict=True):
        lines.append(f"{stamp.strftime('%Y-%m-%dT%H:%M:%SZ')},{float(oat) - 12.0:.1f}")
    sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    result = build_single_system_report(
        FIXTURE,
        out,
        month="2026-06",
        web_oat=sidecar,
    )
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    device_summary = summary["devices"][0]
    assert device_summary["web_oat_source"] == "csv"
    fault_ids = {row["rule_id"] for row in device_summary["faults"]}
    assert "OAT-METEO" in fault_ids
    assert "included from csv" in device_summary["executive_summary"]
    assert (out / "figures" / "AHU_1_rcx_bas_web_oat.png").stat().st_size > 100


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
    result = build_single_system_report(root, out, scope="building", month="2026-06")
    assert result.devices == ["AHU_1"]
    assert result.skipped == [{"folder": "VAV_1", "reason": "no AHU IO in column_map"}]
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["scope"] == "building"
    assert "VAV_1" in result.typ_path.read_text(encoding="utf-8")


def test_anomaly_checklist_skips_without_fan_on_data():
    index = pd.date_range("2026-06-01", periods=24, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "outside-air-temp": [50.0 + i for i in range(24)],
            "fan-status": [0] * 24,
        },
        index=index,
    )
    rows = anomaly_plain_checklist(
        frame,
        [("outside-air-temp", "OAT"), ("fan-status", "SF")],
        "2026-06",
    )
    assert rows == [{"outcome": "skipped", "text": "Skipped — not enough fan-on data."}]


def test_scatter_writer_calls_canonical_chart():
    source = inspect.getsource(write_econ_scatter)
    assert "build_economizer_delta_points" in source
    assert "economizer_delta_scatter" in source
    assert "bottom_left" in source
    assert "OAT − MAT" not in source
    assert "RAT − MAT" not in source
