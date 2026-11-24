"""Fault-confidence screen on synthetic data with planted real faults, false positives and a mis-tuned rule."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from open_fdd.ml.confidence import (
    ConfidenceConfig,
    build_episodes,
    normalize_flags,
    screen,
    summarize,
)


def _fixture(seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """Six generic units, 4 days at 15 min. Planted cases:

    * EQ-1: real supply-temperature fault: large, persistent excursion, abnormal inputs, a second rule co-faults.
    * EQ-2: false positive: the sensor goes stale during the episode and the unit is not running.
    * all units: rule R-TIGHT has a threshold inside normal noise, so it fires everywhere (tuning).
    """
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-01-01", periods=4 * 96, freq="15min", tz="UTC")
    flags, hist = [], []
    truth: dict[str, str] = {}
    for u in range(1, 7):
        eq = f"EQ-{u}"
        sat = 13.0 + rng.normal(0, 0.4, ts.size)
        running = np.ones(ts.size, dtype=int)
        if u == 1:
            sat[150:190] += 6.0
        if u == 2:
            sat[200:216] = sat[199]
            sat[200:216] += 2.5
            running[200:216] = 0
        for i, t in enumerate(ts):
            hist.append((t, eq, "supply_air_temp", sat[i]))
            hist.append((t, eq, "fan_status", float(running[i])))
            flags.append((t, eq, "R-SAT-HIGH", int(sat[i] > 15.0), sat[i], 15.0, "above", running[i]))
            flags.append((t, eq, "R-TIGHT", int(sat[i] > 13.2), sat[i], 13.2, "above", running[i]))
            flags.append((t, eq, "R-COIL", int(u == 1 and 150 <= i < 190), np.nan, np.nan, "", running[i]))
    fl = pd.DataFrame(flags, columns=["timestamp", "equipment_id", "rule_id", "flag", "value", "threshold", "direction", "running"])
    hs = pd.DataFrame(hist, columns=["timestamp", "equipment_id", "point_id", "value"])
    truth["EQ-1"] = "likely_real"
    truth["EQ-2"] = "likely_false_positive"
    return fl, hs, truth


def test_episodes_merge_small_gaps():
    ts = pd.date_range("2026-01-01", periods=8, freq="15min", tz="UTC")
    fl = normalize_flags(pd.DataFrame({"timestamp": ts, "equipment_id": "A", "rule_id": "R", "flag": [0, 1, 1, 0, 1, 0, 0, 1]}))
    ep = build_episodes(fl, ConfidenceConfig(gap_samples=1))
    assert len(ep) == 2
    assert ep.iloc[0]["n_samples"] == 4


def test_flag_text_and_bool_inputs():
    ts = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    fl = normalize_flags(pd.DataFrame({"timestamp": ts, "equipment_id": "A", "rule_id": "R", "flag": ["FAULT", "PASS", "true"]}))
    assert fl["flag"].tolist() == [1, 0, 1]


def test_missing_columns_raise():
    with pytest.raises(ValueError, match="missing"):
        screen(pd.DataFrame({"timestamp": [], "rule_id": []}))


def test_scoring_separates_planted_cases():
    fl, hs, _ = _fixture()
    res = screen(fl, hs)
    ep = res["episodes"]
    real = ep[(ep["equipment_id"] == "EQ-1") & (ep["rule_id"] == "R-SAT-HIGH")].sort_values("duration_h").iloc[-1]
    fp = ep[(ep["equipment_id"] == "EQ-2") & (ep["rule_id"] == "R-SAT-HIGH")].sort_values("duration_h").iloc[-1]
    assert real["label"] == "likely_real", real["reason"]
    assert fp["label"] == "likely_false_positive", fp["reason"]
    assert real["p_real"] > fp["p_real"] + 0.3
    tight = ep[ep["rule_id"] == "R-TIGHT"]
    assert (tight["label"] == "tuning_suggested").mean() >= 0.6
    rules = res["rules"].set_index("rule_id")
    assert rules.loc["R-TIGHT", "suggestion"] == "review threshold or applicability"
    eqh = res["equipment"].set_index("equipment_id")
    assert eqh.loc["EQ-1", "rules_likely_real"] >= 1
    assert eqh.loc["EQ-1", "likely_real"] > eqh.loc["EQ-3", "likely_real"]


def test_probabilities_sum_to_one_and_reasons_present():
    fl, hs, _ = _fixture(seed=11)
    ep = screen(fl, hs)["episodes"]
    total = ep[["p_real", "p_false_positive", "p_tuning"]].sum(axis=1)
    assert np.allclose(total, 1.0, atol=0.01)
    assert ep["reason"].str.len().min() > 0


def test_works_without_history_or_optional_columns():
    fl, _, _ = _fixture()
    res = screen(fl[["timestamp", "equipment_id", "rule_id", "flag"]])
    assert len(res["episodes"]) > 0
    s = summarize(res)
    assert s["episodes"] == len(res["episodes"])
    assert set(s["labels"]) == {"likely_real", "likely_false_positive", "tuning_suggested", "uncertain"}


def test_screen_does_not_mutate_inputs():
    fl, hs, _ = _fixture()
    before = fl.copy()
    screen(fl, hs)
    pd.testing.assert_frame_equal(fl, before)


def test_cli_writes_outputs(tmp_path):
    from open_fdd.ml.confidence import main

    fl, hs, _ = _fixture()
    fl.to_csv(tmp_path / "flags.csv", index=False)
    hs.to_csv(tmp_path / "history.csv", index=False)
    assert main(["--flags", str(tmp_path / "flags.csv"), "--history", str(tmp_path / "history.csv"), "--out-dir", str(tmp_path / "out")]) == 0
    for name in ("episodes.csv", "equipment.csv", "rules.csv", "summary.json"):
        assert (tmp_path / "out" / name).is_file()


def test_data_quality_rule_is_confirmed_by_stale_inputs():
    fl, hs, _ = _fixture()
    stale = (fl["equipment_id"] == "EQ-2") & (fl["rule_id"] == "R-SAT-HIGH")
    dq = fl[stale].copy()
    dq["rule_id"] = "DQ-STALE"
    dq["flag"] = 0
    dq.loc[dq.index[200:216], "flag"] = 1
    dq = dq.drop(columns=["value", "threshold", "direction"])
    fl2 = pd.concat([fl, dq], ignore_index=True)
    ep = screen(fl2, hs, ConfidenceConfig(data_quality_rules=("DQ-",)))["episodes"]
    row = ep[ep["rule_id"] == "DQ-STALE"].iloc[0]
    assert row["label"] == "likely_real", row["reason"]
    assert "data-quality rule confirmed" in row["reason"]


def test_data_rule_rollup_is_not_an_equipment_issue():
    fl, hs, _ = _fixture()
    fl = fl[fl["rule_id"] != "R-TIGHT"]
    dq = fl[fl["rule_id"] == "R-SAT-HIGH"].copy()
    dq["rule_id"] = "DQ-STALE"
    dq["flag"] = 0
    eq2 = dq.index[dq["equipment_id"] == "EQ-2"]
    dq.loc[eq2[200:216], "flag"] = 1
    res = screen(pd.concat([fl, dq.drop(columns=["value", "threshold", "direction"])], ignore_index=True), hs,
                 ConfidenceConfig(data_quality_rules=("DQ-",)))
    eqh = res["equipment"].set_index("equipment_id")
    assert eqh.loc["EQ-2", "health"] == "sensor or data issue"
    assert eqh.loc["EQ-1", "health"] in {"equipment issue likely", "check equipment"}
