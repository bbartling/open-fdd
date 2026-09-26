"""Generic report profiles, figure selection, and history sources."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from open_fdd.reporting.report_template import (
    HISTORY_SOURCES,
    PROFILES,
    SKIPPED_RCX_PRESET_IDS,
    DeviceFolderSource,
    OpenFddApiSource,
    VendorApiSource,
    load_ai_comments,
    profile_for_equip_type,
    select_figures,
)
from open_fdd.reporting.single_system_typst import build_single_system_report

FIXTURE = Path(__file__).parent / "fixtures" / "ahu_typst_mini"


def test_future_profiles_are_registered_stubs():
    assert PROFILES["vav_ahu"].implemented
    assert PROFILES["cv_ahu"].implemented
    for stub in (
        "single_zone",
        "chiller",
        "boiler",
        "heat_pump",
        "vav_box",
        "fan_coil",
        "geothermal_field",
        "data_hall",
    ):
        assert stub in PROFILES
        assert not PROFILES[stub].implemented
    assert set(HISTORY_SOURCES) == {"device_folder", "openfdd_api", "vendor_api"}


def test_equip_type_picks_vav_ahu_and_stubs():
    assert profile_for_equip_type("ahu") == "vav_ahu"
    assert profile_for_equip_type("unitventilator") == "cv_ahu"
    assert profile_for_equip_type("uv") == "cv_ahu"
    assert profile_for_equip_type("fcu") == "fan_coil"
    assert profile_for_equip_type("chiller") == "chiller"


def test_vav_ahu_skips_rainbow_duplicate_timeseries():
    roles = {
        "outside-air-temp",
        "return-air-temp",
        "mixed-air-temp",
        "discharge-air-temp",
        "duct-static-pressure",
        "duct-static-pressure-sp",
        "fan-status",
        "web-outside-air-temp",
        "outside-air-damper",
    }
    chosen = {spec.id for spec in select_figures("vav_ahu", roles)}
    assert chosen.isdisjoint(SKIPPED_RCX_PRESET_IDS)
    assert "econ_temps" in chosen
    assert "ahu_sat_reset_scatter" in chosen
    assert "duct_static_box" in chosen
    assert "ahu_dats" not in chosen
    assert "duct_static_ts" not in chosen
    cv_chosen = {spec.id for spec in select_figures("cv_ahu", roles)}
    assert cv_chosen == chosen
    without_web = select_figures("vav_ahu", roles - {"web-outside-air-temp"})
    assert "ahu_sat_reset_scatter" not in {spec.id for spec in without_web}
    assert select_figures("chiller", roles) == []


def test_device_folder_source_loads_roles():
    history = DeviceFolderSource(FIXTURE).load()
    assert history.source_id == "device_folder"
    assert history.equipment_id == "AHU_1"
    assert "discharge-air-temp" in history.frame.columns


def test_api_and_vendor_sources_wait_for_a_reader():
    with pytest.raises(NotImplementedError, match="device folder"):
        OpenFddApiSource("https://central.example").load()
    with pytest.raises(NotImplementedError, match="Vendor API"):
        VendorApiSource("example-vendor").load()
    frame = pd.DataFrame(
        {"discharge-air-temp": [55.0]},
        index=pd.date_range("2026-06-01", periods=1, freq="h", tz="UTC"),
    )
    loaded = OpenFddApiSource("https://central.example", reader=lambda: frame).load()
    assert loaded.source_id == "openfdd_api"
    assert loaded.frame["discharge-air-temp"].iloc[0] == 55.0


def test_ai_comment_slot_lands_in_the_pdf(tmp_path):
    comments = {"executive_summary": "The supply fan ran the whole month."}
    out = tmp_path / "out"
    result = build_single_system_report(
        FIXTURE,
        out,
        month="2026-06",
        ai_comments=comments,
    )
    typ = result.typ_path.read_text(encoding="utf-8")
    assert "The supply fan ran the whole month." in typ
    assert "open-fdd-anomaly" not in typ
    summary = __import__("json").loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["devices"][0]["ai_comments"]["rcx_week"] == ""


def test_ai_comments_file_merges(tmp_path):
    folder = tmp_path / "AHU_1"
    folder.mkdir()
    (folder / "ai_comments.json").write_text(
        '{"economizer": "Damper stayed near closed.", "not_a_slot": "ignore"}',
        encoding="utf-8",
    )
    comments = load_ai_comments(folder, {"sensor_checks": "OAT spiked once."})
    assert comments["economizer"] == "Damper stayed near closed."
    assert comments["sensor_checks"] == "OAT spiked once."
    assert "not_a_slot" not in comments
