"""T1284-6 and display/storage helpers for offline Typst reports."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from open_fdd.analytics.report_storage import (
    STORAGE_ABI_METRIC,
    economizer_identifiable_delta_min,
    frame_for_display,
    normalize_display_units,
)
from open_fdd.reporting.single_system_typst import build_single_system_report, compile_typst

FIXTURE = Path(__file__).parent / "fixtures" / "ahu_typst_mini"
SI_FIXTURE = Path(__file__).parent / "fixtures" / "ahu_typst_mini_si"


def _build_si_fixture() -> None:
    from open_fdd.units.convert import PA_PER_IN_WC, fahrenheit_to_celsius

    if SI_FIXTURE.is_dir():
        return
    shutil.copytree(FIXTURE, SI_FIXTURE)
    column_map = json.loads((SI_FIXTURE / "column_map.json").read_text(encoding="utf-8"))
    column_map["storage_abi"] = STORAGE_ABI_METRIC
    (SI_FIXTURE / "column_map.json").write_text(json.dumps(column_map, indent=2) + "\n", encoding="utf-8")
    lines = (SI_FIXTURE / "history_wide.csv").read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    temp_cols = {"DAT", "MAT", "RAT", "OAT"}
    pressure_cols = {"DSP", "DSPSP"}
    out_lines = [lines[0]]
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        row = dict(zip(header, parts, strict=True))
        for key in temp_cols:
            if key in row:
                row[key] = f"{fahrenheit_to_celsius(float(row[key])):.6f}"
        for key in pressure_cols:
            if key in row:
                row[key] = f"{float(row[key]) * PA_PER_IN_WC:.6f}"
        out_lines.append(",".join(row[c] for c in header))
    (SI_FIXTURE / "history_wide.csv").write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def test_normalize_display_units_rejects_unknown():
    with pytest.raises(ValueError, match="imperial or si"):
        normalize_display_units("kelvin")


def test_economizer_delta_threshold_scales_with_display():
    assert economizer_identifiable_delta_min("imperial") == 10.0
    assert economizer_identifiable_delta_min("si") == pytest.approx(5.555556, rel=1e-5)


def test_frame_for_display_rejects_legacy_or_undeclared_storage():
    import pandas as pd

    frame = pd.DataFrame({"outside-air-temp": [32.0, 50.0]})
    with pytest.raises(ValueError, match="missing storage_abi"):
        frame_for_display(frame, "si")
    frame.attrs["storage_abi"] = "imperial-f-v1"
    with pytest.raises(ValueError, match="unsupported storage_abi"):
        frame_for_display(frame, "si")


def test_t1284_6_undeclared_storage_fixture_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="missing storage_abi"):
        build_single_system_report(FIXTURE, tmp_path / "undeclared", month="2026-06", units="si")


@pytest.mark.skipif(shutil.which("typst") is None, reason="typst is not on PATH")
def test_t1284_6_compiles_in_both_display_modes(tmp_path):
    _build_si_fixture()
    for units in ("imperial", "si"):
        out = tmp_path / units
        result = build_single_system_report(SI_FIXTURE, out, month="2026-06", units=units, compile_pdf=True)
        assert result.pdf_path is not None
        assert result.pdf_path.is_file()
        assert result.pdf_path.stat().st_size > 500


def test_si_storage_fixture_display_modes_share_fault_content(tmp_path):
    _build_si_fixture()
    out_imperial = tmp_path / "imperial"
    out_si = tmp_path / "si"
    build_single_system_report(SI_FIXTURE, out_imperial, month="2026-06", units="imperial")
    build_single_system_report(SI_FIXTURE, out_si, month="2026-06", units="si")
    summary_i = json.loads((out_imperial / "report_summary.json").read_text(encoding="utf-8"))
    summary_s = json.loads((out_si / "report_summary.json").read_text(encoding="utf-8"))
    assert summary_i["devices"][0]["storage_abi"] == STORAGE_ABI_METRIC
    assert {row["rule_id"]: row["fault_hours"] for row in summary_i["devices"][0]["faults"]} == {
        row["rule_id"]: row["fault_hours"] for row in summary_s["devices"][0]["faults"]
    }
