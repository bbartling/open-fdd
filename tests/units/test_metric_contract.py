"""Goldens for sql/contract/metric_units.json (#1284)."""

from __future__ import annotations

import json
from pathlib import Path

from open_fdd.units.convert import (
    admit_temperature_to_pack_f,
    delta_c_to_delta_f,
    delta_f_to_delta_c,
    norm_command,
)
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
GOLDENS = ROOT / "sql/contract/goldens/unit_vectors.json"
METRIC = ROOT / "sql/contract/metric_units.json"


def test_contract_files_exist():
    assert METRIC.is_file()
    assert GOLDENS.is_file()
    body = json.loads(METRIC.read_text(encoding="utf-8"))
    assert body["contract_id"] == "openfdd-metric-units-v1"
    assert body["processing_abi_target"] == "metric-c-v2"


def test_20c_admits_to_68f():
    assert abs(admit_temperature_to_pack_f(20.0, "°C") - 68.0) < 1e-9
    assert abs(admit_temperature_to_pack_f(68.0, "°F") - 68.0) < 1e-9


def test_delta_scale_only():
    assert abs(delta_f_to_delta_c(5.0) - 2.777777777777778) < 1e-12
    assert abs(delta_c_to_delta_f(3.0) - 5.4) < 1e-12


def test_percent_declared_no_magnitude_guess():
    s = pd.Series([0.0, 0.5, 1.0, 1.01, 50.0, 100.0])
    got = norm_command(s, representation="percent").tolist()
    expect = [0.0, 0.005, 0.01, 0.0101, 0.5, 1.0]
    for a, b in zip(got, expect, strict=True):
        assert abs(a - b) < 1e-12


def test_fraction_declared_passthrough():
    s = pd.Series([0.0, 0.5, 1.0])
    got = norm_command(s, representation="fraction").tolist()
    assert got == [0.0, 0.5, 1.0]


def test_auto_is_series_level_not_element_wise():
    # Mixed percent series: max > 1 → entire series /100 (1 → 0.01, not 1.0).
    mixed = norm_command(pd.Series([0.5, 1.0, 50.0]), representation="auto").tolist()
    assert [round(x, 6) for x in mixed] == [0.005, 0.01, 0.5]
    # Pure fraction fixture (max ≤ 1) stays fraction.
    frac = norm_command(pd.Series([0.0, 0.6, 1.0]), representation="auto").tolist()
    assert frac == [0.0, 0.6, 1.0]


def test_goldens_file_matches_helpers():
    cases = {c["id"]: c for c in json.loads(GOLDENS.read_text(encoding="utf-8"))["cases"]}
    c = cases["abs_20C_eq_68F"]
    assert abs(admit_temperature_to_pack_f(c["metric"], "C") - c["imperial"]) < 1e-9
    d = cases["delta_5F_is_2p777C"]
    assert abs(delta_f_to_delta_c(d["imperial"]) - d["metric"]) < 1e-12
    p = cases["percent_declared"]
    got = norm_command(pd.Series(p["values_percent"]), representation="percent").tolist()
    for a, b in zip(got, p["expect_fraction"], strict=True):
        assert abs(a - b) < 1e-12
