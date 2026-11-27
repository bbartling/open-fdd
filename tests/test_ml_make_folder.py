"""open-fdd-ml make-folder and the device-folder format (#1652)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from open_fdd.ml.cli import main

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lbnl_sdahu" / "AHU_annual_2018-07-03_10.csv"


def _trend_csv(tmp_path):
    idx = pd.date_range("2026-01-05 00:00", periods=3 * 288, freq="5min")  # naive local stamps
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"Time": idx.strftime("%m/%d/%Y %H:%M"), "SAT": 13 + rng.normal(0, 0.3, len(idx)),
                       "OAT": 4 + rng.normal(0, 1, len(idx)), "SF_S": 1.0, "Note": "x"})
    path = tmp_path / "trend.csv"
    df.to_csv(path, index=False)
    return path


def test_make_folder_from_a_csv_then_detect(tmp_path, capsys):
    out = tmp_path / "AHU_1"
    rc = main(["make-folder", str(_trend_csv(tmp_path)), "--out", str(out), "--time-col", "Time",
               "--tz", "America/Chicago", "--map", "discharge-air-temp=SAT", "--map", "oa_t=OAT",
               "--map", "fan-status=SF_S", "--from", "2026-01-05", "--to", "2026-01-06"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["folder"] == str(out)
    cmap = json.loads((out / "column_map.json").read_text(encoding="utf-8"))
    assert cmap == {"equipType": "AHU", "points": {"discharge-air-temp": "SAT", "oa_t": "OAT", "fan-status": "SF_S"}}
    hist = pd.read_csv(out / "history_wide.csv")
    assert list(hist.columns) == ["timestamp_utc", "SAT", "OAT", "SF_S"]
    assert hist["timestamp_utc"].iloc[0] == "2026-01-05T06:00:00Z"  # midnight Chicago = 06:00 UTC
    assert hist["timestamp_utc"].iloc[-1] < "2026-01-07T00:00:00Z"
    assert main(["detect", str(out), "--method", "zscore", "--out", str(tmp_path / "z")]) == 0


def test_make_folder_errors_and_warnings(tmp_path, capsys):
    csv = _trend_csv(tmp_path)
    assert main(["make-folder", str(csv), "--out", str(tmp_path / "a"), "--map", "sat=SAT"]) == 2
    assert "no time column 'timestamp_utc'" in capsys.readouterr().err
    assert main(["make-folder", str(csv), "--out", str(tmp_path / "b"), "--time-col", "Time", "--map", "sat"]) == 2
    assert "ROLE=COLUMN" in capsys.readouterr().err
    assert main(["make-folder", str(csv), "--out", str(tmp_path / "c"), "--time-col", "Time", "--map", "sat=NOPE"]) == 2
    assert "NOPE" in capsys.readouterr().err
    assert main(["make-folder", str(csv), "--out", str(tmp_path / "d"), "--time-col", "Time", "--map", "satt=SAT"]) == 0
    assert "unknown role 'satt'" in capsys.readouterr().err
    assert main(["make-folder", "--example", str(csv), "--out", str(tmp_path / "e")]) == 2
    assert "exactly one source" in capsys.readouterr().err


def test_make_folder_from_lbnl_and_example(tmp_path, capsys):
    out = tmp_path / "LB"
    assert main(["make-folder", "--from-lbnl", str(FIXTURE), "--out", str(out)]) == 0
    cmap = json.loads((out / "column_map.json").read_text(encoding="utf-8"))
    assert cmap["points"]["discharge-air-temp"] == "discharge_air_temp" and cmap["equipType"] == "AHU"
    from open_fdd.ml.cli import role_frame_from_folder

    assert "fan-status" in role_frame_from_folder(out).columns
    ex = tmp_path / "EX"
    assert main(["make-folder", "--example", "--out", str(ex)]) == 0
    assert main(["methods", str(ex), "--json"]) == 0
    capsys.readouterr()
    assert main(["make-folder", "--list-roles"]) == 0
    roles = capsys.readouterr().out
    assert "sat" in roles and "discharge_air_temperature" in roles


def test_help_describes_the_folder_format(capsys):
    assert main(["make-folder", "--help"]) == 0
    text = capsys.readouterr().out
    assert "column_map.json" in text and "timestamp_utc" in text and "degC" in text
