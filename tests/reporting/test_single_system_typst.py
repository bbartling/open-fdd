"""Offline single-system AHU Typst pack from a tiny device folder."""

from __future__ import annotations

import inspect
import json
import shutil
import stat
from pathlib import Path

import pytest

import pandas as pd

from open_fdd.analytics.anomaly.cli import main
from open_fdd.reporting.single_system_typst import (
    EXAMPLE_LOCATION,
    anomaly_plain_checklist,
    attach_web_oat,
    build_single_system_report,
    compile_typst,
    dominant_month,
    filter_to_month,
    render_typst,
    representative_week,
    write_econ_scatter,
)
from open_fdd.analytics.anomaly.io import load_device_folder
from open_fdd.reporting.single_system_typst import role_frame


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")

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
    assert "outside its physical range" in typ
    assert "stuck flat" in typ
    assert "look normal" in typ or "needs a look" in typ
    assert "Fail." not in typ
    assert "not equipment faults" in typ
    assert "histogram" not in typ.lower()
    assert "scoreboard" not in typ.lower()
    assert "z-score" not in typ.lower()
    assert "isolation forest" not in typ.lower()
    assert " stl " not in typ.lower()
    assert "delta_or_f" not in typ
    assert "delta_mr_f" not in typ
    assert "OAT − RAT" in typ
    assert "MAT − RAT" in typ
    assert "bottom-left" in typ
    assert "fresh-air fraction" in typ
    assert "actuator position" in typ
    assert "100% outdoor-air line" in typ
    assert "mild economizer weather" in typ
    assert typ.index("AHU_1_econ_scatter.png") < typ.index("Outdoor-air mixing with the supply fan on")
    assert '#image("figures/AHU_1_econ_scatter.png", width: 100%)' in typ
    assert "width: 80%" not in typ
    assert "x = (OAT - MAT)" not in typ
    assert "Open-FDD AI Agent Report" in typ
    assert "AHU screening" not in typ
    assert "BUILDING_100" not in typ
    assert "Offline report from mapped roles" not in typ
    assert "#2563eb" in typ
    assert "samples" in typ
    assert "Δt" in typ
    assert "Troubleshoot:" in typ
    assert "In the data:" in typ
    assert "open-fdd-anomaly" not in typ
    assert "how to run" not in typ.lower()
    assert "FC1" in typ
    assert "ECON-1" in typ
    assert "FC2" not in typ
    assert result.devices == ["AHU_1"]
    pngs = list((out / "figures").glob("*.png"))
    names = {path.name for path in pngs}
    assert pngs
    assert all("hist" not in path.name for path in pngs)
    scatter_png = out / "figures" / "AHU_1_econ_scatter.png"
    rainbow_png = out / "figures" / "AHU_1_rcx_econ_temps.png"
    assert scatter_png.stat().st_size > 100
    assert _png_size(scatter_png) == _png_size(rainbow_png)
    assert (out / "figures" / "AHU_1_fault_FC1.png").stat().st_size > 100
    assert not (out / "figures" / "AHU_1_fault_SV-RANGE.png").exists()
    assert "AHU_1_rcx_econ_temps.png" in names
    assert "AHU_1_rcx_duct_static_box.png" in names
    assert "AHU_1_rcx_duct_static_ts.png" not in names
    assert "AHU_1_rcx_ahu_sat_reset_scatter.png" not in names
    for skipped in (
        "ahu_dats",
        "ahu_mats",
        "ahu_rats",
        "ahu_dampers",
        "ahu_cooling_valves",
        "fan_speeds",
    ):
        assert f"AHU_1_rcx_{skipped}.png" not in names

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["month"] == "2026-06"
    assert summary["devices"][0]["profile"] == "vav_ahu"
    assert "sensor_checks" in summary["ai_comment_slots"]
    assert "device_folder" in summary["history_sources"]
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
    coverage = summary["devices"][0]["coverage"]
    assert coverage["samples"] == 72
    assert coverage["interval"].endswith("min")
    assert summary["title"] == "Open-FDD AI Agent Report"
    assert summary["location"] == ""


def test_report_chrome_uses_title_location_and_coverage():
    typ = render_typst(
        {
            "title": "Open-FDD AI Agent Report",
            "location": EXAMPLE_LOCATION,
            "devices": [
                {
                    "equipment_id": "AHU_1",
                    "week": "2026-06-01 to 2026-06-07",
                    "executive_summary": "Summary.",
                    "sensor_narrative": "Sensor checks passed.",
                    "anomaly_narrative": "Outdoor air temperature looks normal.",
                    "profile_implemented": True,
                    "rcx": [],
                    "faults": [],
                    "scatter_figure": "",
                    "scatter_caption": "Caption.",
                    "coverage": {
                        "month_phrase": "June 2026",
                        "samples": 72,
                        "interval": "60 min",
                        "span_h": "72.0",
                    },
                }
            ],
            "skipped": [],
        }
    )
    assert "Open-FDD AI Agent Report" in typ
    assert EXAMPLE_LOCATION in typ
    assert "June 2026, 72 samples, Δt ≈ 60 min, span 72.0 h" in typ
    assert "AHU screening" not in typ
    assert "BUILDING_100" not in typ
    assert "#2563eb" in typ
    assert "#1e3a8a" in typ


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
    assert (out / "figures" / "AHU_1_rcx_ahu_sat_reset_scatter.png").stat().st_size > 100


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


def test_compile_typst_invokes_binary_on_path(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    compiler = bindir / "typst"
    compiler.write_text(
        "#!/bin/sh\ntest \"$1\" = compile || exit 1\nprintf '%s\\n' '%PDF-1.4' > \"$3\"\n",
        encoding="utf-8",
    )
    compiler.chmod(compiler.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bindir))
    typ = tmp_path / "report.typ"
    typ.write_text("= Hello\n", encoding="utf-8")
    pdf = compile_typst(typ)
    assert pdf == tmp_path / "report.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")


def test_compile_without_typst_names_the_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    typ = tmp_path / "report.typ"
    typ.write_text("= Hello\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="open-fdd-anomaly report"):
        compile_typst(typ)


def test_report_compile_flag_prints_pdf(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "report.pdf"

    def fake(*_args, **kwargs):
        assert kwargs["compile_pdf"] is True
        from open_fdd.reporting.single_system_typst import SingleSystemReport

        return SingleSystemReport(
            typ_path=tmp_path / "report.typ",
            summary_path=tmp_path / "report_summary.json",
            pdf_path=pdf,
        )

    monkeypatch.setattr(
        "open_fdd.reporting.single_system_typst.build_single_system_report",
        fake,
    )
    code = main(
        [
            "report",
            str(FIXTURE),
            "--out",
            str(tmp_path / "out"),
            "--month",
            "2026-06",
            "--compile",
        ]
    )
    assert code == 0
    assert str(pdf) in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("typst") is None, reason="typst is not on PATH")
def test_compile_writes_pdf_when_typst_is_on_path(tmp_path):
    result = build_single_system_report(
        FIXTURE,
        tmp_path / "out",
        month="2026-06",
        compile_pdf=True,
    )
    assert result.pdf_path is not None
    assert result.pdf_path.is_file()
    assert result.pdf_path.stat().st_size > 1000
    assert result.pdf_path.read_bytes().startswith(b"%PDF")


def test_scatter_writer_calls_canonical_chart():
    source = inspect.getsource(write_econ_scatter)
    assert "build_economizer_delta_points" in source
    assert "economizer_delta_scatter" in source
    assert "bottom_left" in source
    assert "height=400" in source
    assert "width=980" in source
    assert "OAT − MAT" not in source
    assert "RAT − MAT" not in source


def test_narrative_groups_sensor_faults_without_fail_prefix():
    from open_fdd.reporting.narrative_polish import polish_anomaly_paragraph, polish_sensor_paragraph

    sensor = polish_sensor_paragraph(
        [
            {
                "outcome": "fail",
                "rule_id": "SV-RANGE",
                "labels": ["Outdoor air temperature"],
                "low": "35.0",
                "high": "200.0",
            },
            {
                "outcome": "fail",
                "rule_id": "SV-FLATLINE",
                "labels": ["Return air temperature", "Supply air temperature"],
            },
            {"outcome": "fail", "rule_id": "SV-SPIKE", "labels": ["Outdoor air temperature"]},
            {"outcome": "fail", "rule_id": "SV-RATE", "labels": ["Outdoor air temperature"]},
        ]
    )
    assert "Fail." not in sensor
    assert "stayed stuck flat" in sensor
    assert "jumped suddenly and changed faster than expected" in sensor
    assert sensor.index("physical range") < sensor.index("stuck flat")
    anomaly = polish_anomaly_paragraph(
        [
            {"outcome": "looks_normal", "labels": ["Mixed air temperature"]},
            {"outcome": "looks_normal", "labels": ["Outdoor air temperature"]},
        ]
    )
    assert anomaly == "Mixed air temperature and outdoor air temperature look normal."
    one = polish_anomaly_paragraph(
        [{"outcome": "looks_normal", "labels": ["Outdoor air temperature"]}]
    )
    assert one == "Outdoor air temperature looks normal."
    ordered = polish_sensor_paragraph(
        [
            {"outcome": "fail", "rule_id": "SV-SPIKE", "labels": ["Mixed air temperature", "Supply air temperature"]},
            {"outcome": "fail", "rule_id": "SV-RATE", "labels": ["Return air temperature"]},
        ]
    )
    assert ordered.index("Mixed air temperature") < ordered.index("supply air temperature")


def test_fan_off_line_inserts_null_y():
    from open_fdd.analytics.charts import economizer_temps_overlay

    index = pd.date_range("2026-06-01", periods=8, freq="h", tz="UTC")
    fan_on = pd.Series([True, True, True, False, False, True, True, True], index=index)
    points = pd.DataFrame(
        {
            "oat_f": [50, 51, 52, 53, 54, 55, 56, 57],
            "rat_f": [70] * 8,
            "mat_f": [60] * 8,
            "equipment_id": "AHU_1",
        },
        index=index,
    ).loc[fan_on]
    figure = economizer_temps_overlay(points, equipment_id="AHU_1", full_index=index, temp_unit="°F")
    assert figure is not None
    oat = next(trace for trace in figure.data if trace.name == "OAT")
    assert oat.connectgaps is False
    assert figure.layout.yaxis.title.text == "Temperature (°F)"
    values = list(oat.y)
    assert any(value is None or (isinstance(value, float) and value != value) for value in values)
    # The off hours are not bridged: a null sits between 52 and 55.
    numeric = [None if value is None or value != value else value for value in values]
    assert 52 in numeric and 55 in numeric
    assert numeric[numeric.index(52) + 1] is None


def test_fc1_chart_omits_temperature_traces():
    from open_fdd.analytics.charts import rule_result_chart
    from open_fdd.rules.base import RuleResult

    index = pd.date_range("2026-06-01", periods=6, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "duct-static-pressure": [0.2] * 6,
            "duct-static-pressure-sp": [1.2] * 6,
            "fan-cmd": [1.0] * 6,
            "outside-air-temp": [70] * 6,
            "discharge-air-temp": [55] * 6,
        },
        index=index,
    )
    fault = pd.Series([True] * 6, index=index)
    result = RuleResult(
        rule_id="FC1",
        equipment_id="AHU_1",
        status="FAULT",
        applicable=True,
        fault_hours=6,
        confirmed_fault=fault,
        plot_series={
            "outside-air-temp": frame["outside-air-temp"],
            "duct-static-pressure": frame["duct-static-pressure"],
            "fan-cmd": frame["fan-cmd"],
        },
    )
    figure = rule_result_chart(
        frame,
        result,
        required_roles=["duct-static-pressure", "duct-static-pressure-sp", "fan-cmd"],
        pressure_and_fan_only=True,
    )
    assert figure is not None
    names = {str(trace.name) for trace in figure.data}
    assert any("duct-static-pressure" in name for name in names)
    assert any("fan-cmd" in name for name in names)
    assert "confirmed_fault" in names
    assert not any("temp" in name for name in names)


def test_metric_unit_labels():
    from open_fdd.analytics.units import report_units_map, stamp_display_units
    from open_fdd.reporting.single_system_typst import econ_scatter_caption

    units = report_units_map("metric")
    assert units["outside-air-temp"] == "°C"
    assert units["duct-static-pressure"] == "Pa"
    assert report_units_map("imperial")["duct-static-pressure"] == "in. w.c."
    assert "10°C" in econ_scatter_caption("°C")
    frame = pd.DataFrame({"outside-air-temp": [20.0]})
    stamped = stamp_display_units(frame, {"unit_system": "si", "units": {"duct-static-pressure": "Pa"}})
    assert stamped["outside-air-temp"] == "°C"
    assert frame.attrs["unit_system"] == "si"
