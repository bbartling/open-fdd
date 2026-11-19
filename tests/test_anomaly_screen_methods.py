"""Screen defaults run on what is installed (#1654); Isolation Forest is opt-in and labeled (#1658)."""

from __future__ import annotations

import importlib.util
import json
import sys

import numpy as np
import pandas as pd
import pytest

from open_fdd.analytics.anomaly import screen as screen_mod


def _folder(tmp_path, n=3 * 288):
    rng = np.random.default_rng(5)
    idx = pd.date_range("2026-01-05", periods=n, freq="5min", tz="UTC")
    hist = pd.DataFrame(
        {
            "timestamp_utc": idx.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SAT": 13 + rng.normal(0, 0.3, n),
            "FAN": 1.0,
        }
    )
    hist.loc[400, "SAT"] = 25.0
    folder = tmp_path / "AHU_1"
    folder.mkdir()
    hist.to_csv(folder / "history_wide.csv", index=False)
    (folder / "column_map.json").write_text(
        json.dumps({"equipType": "AHU", "points": {"sat": "SAT", "fan_status": "FAN"}}), encoding="utf-8"
    )
    return folder


@pytest.fixture
def no_statsmodels(monkeypatch):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        if name.split(".")[0] == "statsmodels":
            return None
        return real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    for mod in [m for m in sys.modules if m == "statsmodels" or m.startswith("statsmodels.")]:
        monkeypatch.delitem(sys.modules, mod)
    monkeypatch.setitem(sys.modules, "statsmodels", None)  # an import now raises ImportError


def test_default_methods_skip_what_is_not_installed(no_statsmodels):
    run, skipped = screen_mod.default_methods()
    assert run == ["zscore", "mad"]
    assert set(skipped) == {"stl"} and "open-fdd[anomaly]" in skipped["stl"]
    assert "iforest" not in screen_mod.DEFAULT_METHODS


def test_default_screen_runs_on_an_ml_only_install(tmp_path, no_statsmodels):
    pytest.importorskip("matplotlib")
    res = screen_mod.screen_folder(_folder(tmp_path), tmp_path / "s", top_n=0, max_days=0)
    assert set(res.scoreboard["method"]) - {""} == {"zscore", "mad"}
    assert res.methods == ["zscore", "mad"] and set(res.methods_skipped) == {"stl"}
    readme = (tmp_path / "s" / "README.md").read_text(encoding="utf-8")
    assert "| stl | skipped |" in readme and "open-fdd[anomaly]" in readme


def test_explicit_stl_without_the_extra_names_it(tmp_path, no_statsmodels, capsys):
    pytest.importorskip("matplotlib")
    from open_fdd.analytics.anomaly.cli import main

    folder = _folder(tmp_path)
    assert main(["screen", str(folder), "--out", str(tmp_path / "x"), "--methods", "stl", "--top-n", "0"]) == 2
    assert "open-fdd[anomaly]" in capsys.readouterr().err


def test_iforest_is_opt_in_and_labeled(tmp_path):
    pytest.importorskip("matplotlib")
    pytest.importorskip("sklearn")
    folder = _folder(tmp_path)
    res = screen_mod.screen_folder(folder, tmp_path / "a", methods=["zscore", "iforest"], top_n=0, max_days=0)
    sb = res.scoreboard.set_index("method")
    assert sb.loc["iforest", "method_note"] == "fixed_fraction_0.01"
    assert sb.loc["zscore", "method_note"] == ""
    readme = (tmp_path / "a" / "README.md").read_text(encoding="utf-8")
    assert "by construction" in readme
    wide = screen_mod.screen_folder(
        folder, tmp_path / "b", methods=["iforest"], top_n=0, max_days=0, iforest_contamination=0.05
    )
    row = wide.scoreboard.set_index("method").loc["iforest"]
    assert row["method_note"] == "fixed_fraction_0.05"
    assert row["anomaly_minutes"] > 3 * sb.loc["iforest", "anomaly_minutes"]
    with pytest.raises(ValueError, match="contamination"):
        screen_mod.screen_folder(folder, tmp_path / "c", methods=["iforest"], iforest_contamination=0.7)


def test_help_names_the_extra_per_method(capsys):
    from open_fdd.analytics.anomaly.cli import build_parser

    sub = [a for a in build_parser()._actions if a.dest == "command"][0]
    text = sub.choices["screen"].format_help()
    assert "open-fdd[anomaly]" in text and "statsmodels" in text and "opt-in" in text
