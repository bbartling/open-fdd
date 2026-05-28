from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.playground import (  # noqa: E402
    lint_python,
    run_dataframe_script,
    sweep_rule,
)


def test_lint_valid_rule():
    code = "def evaluate(row, cfg, prev_row=None, rows=None):\n    return False\n"
    assert lint_python(code)["ok"] is True


def test_lint_syntax_error():
    assert lint_python("def evaluate(:\n")["ok"] is False


def test_sweep_flags_high_sat():
    rows = [
        {"timestamp": "2025-01-01T00:00:00Z", "SAT": 70.0, "temp": 70.0},
        {"timestamp": "2025-01-01T00:05:00Z", "SAT": 85.0, "temp": 85.0},
    ]
    code = """def evaluate(row, cfg, prev_row=None, rows=None):
    return float(row.get("SAT", 0)) > float(cfg.get("high", 75))
"""
    flags, events = sweep_rule(code, {"high": 75}, rows, capture_print=False)
    assert flags == [False, True]
    assert any(e.get("type") == "summary" for e in events)


def test_run_script_adds_flag_column():
    df = pd.DataFrame({"SAT": [70.0, 85.0]})
    code = """
df = df.copy()
df["custom_flag"] = (df["SAT"] > 75).astype(int)
out = {"df": df, "events": [{"type": "done"}]}
"""
    result = run_dataframe_script(code, df)
    assert result["ok"] is True
    assert "custom_flag" in result["flag_columns"]
