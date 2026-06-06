from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa

API_ROOT = Path(__file__).resolve().parents[2] / "workspace" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from openfdd_bridge.playground import lint_python, run_arrow_script, run_arrow_table  # noqa: E402

ARROW_RULE = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(pc.cast(table["SAT"], pa.float64()), float(cfg.get("high", 75)))
"""


def test_lint_valid_rule():
    assert lint_python(ARROW_RULE)["ok"] is True


def test_lint_syntax_error():
    assert lint_python("def apply_faults_arrow(:\n")["ok"] is False


def test_lint_indentation_error():
    bad = "def apply_faults_arrow(table, cfg, context=None):\nreturn False\n"
    result = lint_python(bad)
    assert result["ok"] is False


def test_lint_requires_arrow_rule():
    assert lint_python("x = 1\n")["ok"] is False


def test_run_arrow_table_flags_high_sat():
    table = pa.table(
        {
            "timestamp": pa.array(["2025-01-01T00:00:00Z", "2025-01-01T00:05:00Z"]),
            "SAT": pa.array([70.0, 85.0], type=pa.float64()),
        }
    )
    result = run_arrow_table(ARROW_RULE, table, {"high": 75})
    assert result["ok"] is True
    assert result["flagged"] == 1


def test_run_arrow_script_metrics():
    table = pa.table(
        {
            "timestamp": pa.array(["2025-01-01T00:00:00Z", "2025-01-01T01:00:00Z"]),
            "supply-fan-speed-command": pa.array([10.0, 0.0], type=pa.float64()),
        }
    )
    code = """
out = {"events": [{"type": "metrics", "metrics": {"sample_rows": table.num_rows}}], "metrics": {"sample_rows": table.num_rows}}
"""
    result = run_arrow_script(code, table, cfg={})
    assert result["ok"] is True
    assert result["metrics"]["sample_rows"] == 2
