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
            "sat": zone + rise,
            "zone_t": zone,
            "htg_valve_pct": heat,
            "oa_t": 2 + rng.normal(0, 1.0, n),
            "fan_status": 1.0,
        },
        index=idx,
    )


def test_ahu_keeps_only_mixed_air_families():
    cols = ["mixed-air-temp", "return-air-temp", "outside-air-temp", "outside-air-damper",
            "discharge-air-temp", "cooling-valve", "zone-air-temp", "heating-valve"]
    assert sorted(grey_box_families(cols)) == ["coil_delta_t", "oa_fraction"]


def test_single_zone_families_pick_zone_then_return():
    assert grey_box_families(["discharge-air-temp", "zone-air-temp", "return-air-temp", "heating-valve"]) == {
        "heat_rise": ["discharge-air-temp", "zone-air-temp", "heating-valve"]
    }
    got = grey_box_families(["discharge-air-temp", "return-air-temp", "compressor-status"])
    assert got == {"cool_drop": ["discharge-air-temp", "return-air-temp", "compressor-status"]}


def test_grey_box_fits_a_furnace_and_flags_a_weak_heat_rise():
    healthy = _furnace()
    det = GreyBox().fit(healthy.iloc[: 4 * 288])
    assert set(det.thresholds_) == {"heat_rise"}
    clean_rate = float(det.flags(healthy.iloc[4 * 288 :]).mean())
    faulty = _furnace(weak_heat_from=4 * 288)
    test = faulty.iloc[4 * 288 :]
    flags = det.flags(test)
    heating = test["htg_valve_pct"] > 0
    assert clean_rate < 0.03
    assert float(flags[heating].mean()) > 0.9
    assert float(flags[~heating].mean()) < 0.05


def test_grey_box_error_names_the_families():
    frame = _furnace().drop(columns=["htg_valve_pct"])
    with pytest.raises(ValueError, match="heating valve"):
        GreyBox().fit(frame)


def test_applicability_reports_what_can_run_and_why_not():
    rows = {r["method"]: r for r in applicability(_furnace())}
    assert rows["grey_box"]["can_run"] and rows["grey_box"]["families"] == ["heat_rise"]
    assert rows["pca"]["can_run"] and "zone-air-temp" in rows["pca"]["roles"]
    bare = _furnace().drop(columns=["htg_valve_pct"])
    gb = {r["method"]: r for r in applicability(bare)}["grey_box"]
    assert not gb["can_run"] and "heat_rise: lacks heating-valve" in gb["reason"]
    idle = _furnace().assign(fan_status=0.0)
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
