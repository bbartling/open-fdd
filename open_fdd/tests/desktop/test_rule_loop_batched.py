from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.testing import assert_series_equal
import yaml

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


def test_rule_loop_batched_matches_full(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    _write_rule(rules_dir)
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=1000, freq="1min"), "sat": [60.0] * 900 + [80.0] * 100})
    cfg_full = RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=10_000)
    cfg_chunk = RuleLoopConfig(rules_path=str(rules_dir), chunk_rows=200)
    out_full = run_rule_loop_batched(frame, cfg_full)
    out_chunk = run_rule_loop_batched(frame, cfg_chunk)
    assert_series_equal(out_full["sat_flag"], out_chunk["sat_flag"])

