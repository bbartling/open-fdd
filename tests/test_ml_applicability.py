"""Per-method role requirements, applicability and the single-zone gray-box family (#1659)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from open_fdd.ml.applicability import METHOD_REQUIREMENTS, applicability
from open_fdd.ml.detectors import GreyBox, grey_box_families


def _furnace(n=6 * 288, seed=0, weak_heat_from=None):
    """Single-zone furnace: heat command 0/100 %, supply = zone + rise when heating."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    heat = ((np.arange(n) // 6) % 3 == 0).astype(float) * 100.0  # 30 min on, 60 min off
    zone = 21 + rng.normal(0, 0.2, n)
    rise = np.where(heat > 0, 18.0, 0.5) + rng.normal(0, 0.4, n)
    if weak_heat_from is not None:
        rise[weak_heat_from:] = np.where(heat[weak_heat_from:] > 0, 4.0, 0.5)
    return pd.DataFrame(
        {
            "discharge_air_temperature": zone + rise,
            "zone_air_temperature": zone,
            "heating_valve_position_command": heat,
            "outdoor_air_intake_temperature": 2 + rng.normal(0, 1.0, n),
            "supply_fan_operating_status": 1.0,
        },
        index=idx,
    )


def test_ahu_keeps_only_mixed_air_families():
    cols = ["mixed_air_temperature", "return_air_temperature", "outdoor_air_intake_temperature", "outdoor_air_intake_damper_position_command",
            "discharge_air_temperature", "cooling_valve_position_command", "zone_air_temperature", "heating_valve_position_command"]
    assert sorted(grey_box_families(cols)) == ["coil_delta_t", "oa_fraction"]


def test_single_zone_families_pick_zone_then_return():
    assert grey_box_families(["discharge_air_temperature", "zone_air_temperature", "return_air_temperature", "heating_valve_position_command"]) == {
        "heat_rise": ["discharge_air_temperature", "zone_air_temperature", "heating_valve_position_command"]
    }
    got = grey_box_families(["discharge_air_temperature", "return_air_temperature", "compressor_operating_status"])
    assert got == {"cool_drop": ["discharge_air_temperature", "return_air_temperature", "compressor_operating_status"]}


def test_grey_box_fits_a_furnace_and_flags_a_weak_heat_rise():
    healthy = _furnace()
    det = GreyBox().fit(healthy.iloc[: 4 * 288])
    assert set(det.thresholds_) == {"heat_rise"}
    clean_rate = float(det.flags(healthy.iloc[4 * 288 :]).mean())
    faulty = _furnace(weak_heat_from=4 * 288)
    test = faulty.iloc[4 * 288 :]
    flags = det.flags(test)
    heating = test["heating_valve_position_command"] > 0
    assert clean_rate < 0.03
    assert float(flags[heating].mean()) > 0.9
    assert float(flags[~heating].mean()) < 0.05


def test_grey_box_error_names_the_families():
    frame = _furnace().drop(columns=["heating_valve_position_command"])
    with pytest.raises(ValueError, match="heating valve"):
        GreyBox().fit(frame)


def test_applicability_reports_what_can_run_and_why_not():
    rows = {r["method"]: r for r in applicability(_furnace())}
    assert rows["grey_box"]["can_run"] and rows["grey_box"]["families"] == ["heat_rise"]
    assert rows["pca"]["can_run"] and "zone_air_temperature" in rows["pca"]["roles"]
    bare = _furnace().drop(columns=["heating_valve_position_command"])
    gb = {r["method"]: r for r in applicability(bare)}["grey_box"]
    assert not gb["can_run"] and "heat_rise: lacks heating_valve_position_command" in gb["reason"]
    idle = _furnace().assign(supply_fan_operating_status=0.0)
    unproven = {r["method"]: r for r in applicability(idle)}
    assert not any(r["can_run"] for r in unproven.values())
    assert "no active rows" in unproven["zscore"]["reason"]
    assert set(METHOD_REQUIREMENTS) == set(rows)


def test_methods_command(tmp_path, capsys):
    from open_fdd.ml.cli import main

    assert main(["methods"]) == 0
    text = capsys.readouterr().out
    assert "heat_rise" in text and "feature roles" in text
    frame = _furnace()
    folder = tmp_path / "FURNACE"
    folder.mkdir()
    out = frame.copy()
    out.insert(0, "timestamp_utc", frame.index.strftime("%Y-%m-%dT%H:%M:%SZ"))
    out.to_csv(folder / "history_wide.csv", index=False)
    (folder / "column_map.json").write_text(
        json.dumps({"equipType": "Furnace", "points": {c: c for c in frame.columns}}), encoding="utf-8"
    )
    assert main(["methods", str(folder), "--json"]) == 0
    got = {r["method"]: r for r in json.loads(capsys.readouterr().out)["methods"]}
    assert got["grey_box"]["can_run"] and got["zscore"]["can_run"]


def _ahu_two_modes(n_per_mode=40, seed=1):
    """80 active AHU rows split evenly over two operating modes (min OA and economizer only)."""
    rng = np.random.default_rng(seed)
    n = 2 * n_per_mode
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    damper = np.r_[np.full(n_per_mode, 0.1), np.full(n_per_mode, 0.8)]
    return pd.DataFrame(
        {
            "discharge_air_temperature": 13 + rng.normal(0, 0.3, n),
            "mixed_air_temperature": 18 + rng.normal(0, 0.5, n),
            "return_air_temperature": 22 + rng.normal(0, 0.3, n),
            "outdoor_air_intake_temperature": 10 + rng.normal(0, 1.0, n),
            "outdoor_air_intake_damper_position_command": damper,
            "cooling_valve_position_command": 0.0,
            "supply_fan_operating_status": 1.0,
        },
        index=idx,
    )


def test_mode_gated_needs_50_rows_in_one_mode_like_fit():
    """80 active rows but 40 per mode: applicability agrees with fit (which raises), instead of can_run=True."""
    pytest.importorskip("sklearn")
    from open_fdd.ml.detectors import ModeGated

    frame = _ahu_two_modes()
    with pytest.raises(ValueError, match="50 normal rows"):
        ModeGated(kind="ocsvm").fit(frame)
    row = {r["method"]: r for r in applicability(frame)}["ocsvm"]
    assert not row["can_run"] and "50 normal rows" in row["reason"]
    enough = _ahu_two_modes(n_per_mode=60)
    assert {r["method"]: r for r in applicability(enough)}["ocsvm"]["can_run"]


def test_an_empty_mapped_role_is_ignored_and_applicability_matches_fit():
    """zone-air-temp mapped but all NaN: PCA fits on the roles with data, gray-box uses return-air-temp."""
    from open_fdd.ml.detectors import PCASPE

    frame = _furnace()
    frame["return_air_temperature"] = frame["zone_air_temperature"] + np.random.default_rng(5).normal(0, 0.1, len(frame))
    frame["zone_air_temperature"] = np.nan
    assert grey_box_families(frame.rename(columns={"discharge_air_temperature": "discharge_air_temperature", "zone_air_temperature": "zone_air_temperature",
                                                   "return_air_temperature": "return_air_temperature", "heating_valve_position_command": "heating_valve_position_command"}))[
        "heat_rise"
    ] == ["discharge_air_temperature", "return_air_temperature", "heating_valve_position_command"]
    det = GreyBox().fit(frame)
    assert set(det.thresholds_) == {"heat_rise"}
    assert det.families_["heat_rise"][1] == "return_air_temperature"
    pca = PCASPE().fit(frame)
    assert "zone_air_temperature" not in pca.roles
    rows = {r["method"]: r for r in applicability(frame)}
    assert rows["grey_box"]["can_run"] and "return_air_temperature" in rows["grey_box"]["roles"]
    assert rows["pca"]["can_run"] and "zone_air_temperature" not in rows["pca"]["roles"]
    for method in ("pca", "grey_box"):
        assert rows[method]["can_run"] == (rows[method]["reason"] == "")


def test_an_all_nan_feature_frame_cannot_run():
    frame = _furnace()
    for col in ("discharge_air_temperature", "zone_air_temperature", "heating_valve_position_command", "outdoor_air_intake_temperature"):
        frame[col] = np.nan
    rows = {r["method"]: r for r in applicability(frame)}
    assert not any(rows[m]["can_run"] for m in ("pca", "grey_box", "ocsvm", "zscore", "mad"))
