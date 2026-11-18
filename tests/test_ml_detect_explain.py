"""detect reports the roles it used, and flags.csv explains each flag (#1660)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from open_fdd.ml import lbnl
from open_fdd.ml.cli import main

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lbnl_sdahu"
NORMAL_CSV = FIXTURE / "AHU_annual_2018-07-03_10.csv"
FAULT_CSV = FIXTURE / "coi_stuck_050_annual_2018-07-03_10.csv"


def _folder(frame, path, drop=()):
    frame = frame.drop(columns=list(drop))
    path.mkdir(parents=True)
    out = frame.copy()
    out.columns = [c.replace("-", "_") for c in frame.columns]
    out.insert(0, "timestamp_utc", frame.index.strftime("%Y-%m-%dT%H:%M:%SZ"))
    out.to_csv(path / "history_wide.csv", index=False)
    (path / "column_map.json").write_text(
        json.dumps({"equipType": "AHU", "points": {c: c.replace("-", "_") for c in frame.columns}}), encoding="utf-8"
    )
    return path


def _run(argv, out):
    assert main(argv + ["--out", str(out)]) == 0
    return json.loads((out / "summary.json").read_text(encoding="utf-8")), pd.read_csv(out / "flags.csv")


def test_zscore_reports_used_and_missing_roles_and_flagged_roles(tmp_path):
    frame = lbnl.load_sdahu_csv(NORMAL_CSV)
    on = frame.index[(frame["fan-status"] > 0.5) & (frame["occupied"] > 0.5)]
    frame.loc[on[300], "discharge-air-temp"] = 70.0  # one clear SAT spike on a running row, a day in
    folder = _folder(frame, tmp_path / "A", drop=["mixed-air-temp"])
    summary, flags = _run(["detect", str(folder), "--method", "zscore"], tmp_path / "z")
    assert "mixed-air-temp" not in summary["roles"] and "mixed-air-temp" not in summary["roles_used"]
    assert "mixed-air-temp" in summary["roles_configured"] and "mixed-air-temp" in summary["roles_missing"]
    assert set(summary["roles_used"]) <= set(summary["roles_configured"])
    hit = flags[flags["flag"] == 1]
    assert len(hit) and hit["flagged_roles"].fillna("").str.len().gt(0).all()
    assert flags.loc[flags["flag"] == 0, "flagged_roles"].fillna("").eq("").all()
    for names in hit["flagged_roles"]:
        assert set(names.split(";")) <= set(summary["roles_used"])
    spike = flags[flags["timestamp_utc"].str.startswith(str(on[300])[:19])]
    assert "discharge-air-temp" in spike["flagged_roles"].iloc[0].split(";")


def test_pca_and_grey_box_explain_each_flag(tmp_path):
    normal = lbnl.load_sdahu_csv(NORMAL_CSV)
    fault = lbnl.load_sdahu_csv(FAULT_CSV)
    train = _folder(normal, tmp_path / "N")
    target = _folder(fault, tmp_path / "F")
    summary, flags = _run(["detect", str(target), "--method", "pca", "--train", str(train)], tmp_path / "p")
    hit = flags[flags["flag"] == 1]
    assert len(hit) and hit["top_role"].isin(summary["roles_used"]).all() and hit["top_share"].between(0, 1).all()
    assert summary["contribution_population"]["rows"] == int(((flags["flag"] == 1) & (flags["phase"] == "evaluation")).sum())
    summary, flags = _run(["detect", str(target), "--method", "grey_box", "--train", str(train)], tmp_path / "g")
    assert summary["residuals_used"] and set(summary["roles_used"]) <= set(summary["roles_configured"])
    hit = flags[flags["flag"] == 1]
    assert len(hit) and hit["top_residual"].isin(summary["residuals_used"]).all()
    assert any(c.startswith("ratio_") for c in flags.columns)


def test_zero_flags_contribution_plot_is_explicit(tmp_path):
    pytest.importorskip("matplotlib")
    from open_fdd.ml.detectors import plot_contributions

    idx = pd.date_range("2026-01-05", periods=10, freq="5min", tz="UTC")
    contrib = pd.DataFrame({"a": np.full(10, 0.7), "b": np.full(10, 0.3)}, index=idx)
    path = plot_contributions(contrib, pd.Series(False, index=idx), tmp_path / "c.png")
    assert Path(path).exists()
    import matplotlib.pyplot as plt

    # the zero-alarm figure carries no bars: re-render and inspect the axes the function would draw
    from unittest import mock

    with mock.patch.object(plt, "close"):
        plot_contributions(contrib, pd.Series(False, index=idx), tmp_path / "d.png")
        ax = plt.gcf().axes[0]
        assert not ax.patches and "No flagged samples" in ax.texts[0].get_text()
        plt.close("all")
