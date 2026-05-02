from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.testing import assert_series_equal
import yaml

import pytest

from open_fdd.desktop.rules.rule_loop import RuleLoopConfig, run_rule_loop_batched


def _write_rule(rules_dir: Path) -> None:
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule = {
        "name": "sat_bounds",
        "type": "bounds",
        "inputs": {"sat": {"column": "sat", "bounds": [50, 65]}},
        "flag": "sat_flag",
    }
    (rules_dir / "sat.yaml").write_text(yaml.safe_dump(rule), encoding="utf-8")


def test_rule_loop_batched_rule_files_filters_which_yaml_loads(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules_pick"
    rules_dir.mkdir(parents=True, exist_ok=True)
    ok_rule = {
        "name": "sat_bounds",
        "type": "bounds",
        "inputs": {"sat": {"column": "sat", "bounds": [50, 65]}},
        "flag": "sat_flag",
    }
    bad_rule = {
        "name": "needs_missing",
        "type": "expression",
        "inputs": {"x": {"column": "no_such_column"}},
        "expression": "x > 0",
        "flag": "missing_flag",
    }
    (rules_dir / "sat.yaml").write_text(yaml.safe_dump(ok_rule), encoding="utf-8")
    (rules_dir / "bad.yaml").write_text(yaml.safe_dump(bad_rule), encoding="utf-8")
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=5, freq="1min"), "sat": [60.0] * 5})
    out_one = run_rule_loop_batched(
        frame,
        RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=10_000, rule_files=["sat.yaml"]),
    )
    assert "sat_flag" in out_one.columns
    assert "missing_flag" not in out_one.columns


def test_rule_loop_single_file_rule_files_must_match_exactly(tmp_path: Path) -> None:
    rules_dir = tmp_path / "one_rule.yaml"
    rule = {"name": "sat_bounds", "type": "bounds", "inputs": {"sat": {"column": "sat", "bounds": [50, 65]}}, "flag": "sat_flag"}
    rules_dir.write_text(yaml.safe_dump(rule), encoding="utf-8")
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=3, freq="1min"), "sat": [60.0] * 3})
    with pytest.raises(RuntimeError, match="rule_files filter does not match"):
        run_rule_loop_batched(
            frame,
            RuleLoopConfig(
                rules_path=str(rules_dir),
                chunk_rows=10_000,
                rule_files=["one_rule.yaml", "other.yaml"],
            ),
        )


def test_rule_loop_batched_rule_files_missing_name_raises(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules_missing"
    _write_rule(rules_dir)
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=3, freq="1min"), "sat": [60.0] * 3})
    with pytest.raises(RuntimeError, match="not found"):
        run_rule_loop_batched(
            frame,
            RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=10_000, rule_files=["nope.yaml"]),
        )


def test_rule_loop_batched_skip_missing_columns(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules_skip"
    rules_dir.mkdir(parents=True, exist_ok=True)
    ok_rule = {
        "name": "sat_bounds",
        "type": "bounds",
        "inputs": {"sat": {"column": "sat", "bounds": [50, 65]}},
        "flag": "sat_flag",
    }
    bad_rule = {
        "name": "needs_missing",
        "type": "expression",
        "inputs": {"x": {"column": "no_such_column"}},
        "expression": "x > 0",
        "flag": "missing_flag",
    }
    (rules_dir / "sat.yaml").write_text(yaml.safe_dump(ok_rule), encoding="utf-8")
    (rules_dir / "bad.yaml").write_text(yaml.safe_dump(bad_rule), encoding="utf-8")
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=5, freq="1min"), "sat": [60.0] * 5})
    out = run_rule_loop_batched(
        frame,
        RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=10_000, skip_missing_columns=True),
    )
    assert "sat_flag" in out.columns
    assert "missing_flag" not in out.columns


def test_rule_loop_batched_matches_full(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    _write_rule(rules_dir)
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=1000, freq="1min"), "sat": [60.0] * 900 + [80.0] * 100})
    cfg_full = RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=10_000)
    cfg_chunk = RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=200)
    out_full = run_rule_loop_batched(frame, cfg_full)
    out_chunk = run_rule_loop_batched(frame, cfg_chunk)
    assert_series_equal(out_full["sat_flag"], out_chunk["sat_flag"])


def test_rule_loop_batched_rolling_window_needs_overlap(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules_roll"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule = {
        "name": "rolling_test",
        "type": "expression",
        "inputs": {"sat": {"column": "sat"}},
        "params": {"window": 50},
        "expression": "(sat.rolling(window=window).mean() > 0.5)",
        "flag": "rolling_test_flag",
    }
    (rules_dir / "rolling_test.yaml").write_text(yaml.safe_dump(rule), encoding="utf-8")

    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=400, freq="1min"),
            "sat": ([0.0] * 199) + ([1.0] * 201),
        }
    )
    out_large = run_rule_loop_batched(frame, RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=10_000))
    out_small = run_rule_loop_batched(frame, RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=100))

    # Current chunking has no overlap; rolling windows near boundaries can diverge.
    assert out_large.index.equals(out_small.index)
    assert len(out_large.index) == len(out_small.index)
    assert out_large["rolling_test_flag"].dtype == out_small["rolling_test_flag"].dtype
    boundary_slice = slice(220, 280)
    assert not out_large["rolling_test_flag"].iloc[boundary_slice].equals(
        out_small["rolling_test_flag"].iloc[boundary_slice]
    )

