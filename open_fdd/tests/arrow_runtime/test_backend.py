from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from open_fdd.arrow_runtime.backend import compile_apply_faults_arrow, run_arrow_rule
from open_fdd.arrow_runtime.testing import sample_hvac_table

THRESHOLD_RULE = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
"""


def test_simple_threshold_rule():
    table = sample_hvac_table(50, seed=1)
    cfg = {"max_zone_temp": 75.0}
    result = run_arrow_rule(THRESHOLD_RULE, table, cfg, rule_id="t1")
    assert result.backend == "arrow"
    assert result.row_count == 50
    assert result.true_count >= 0
    assert len(result.fault_mask) == 50


def test_fan_no_airflow_rule():
    code = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    fan_on = pc.greater(table["fan_cmd"], cfg.get("fan_on_threshold", 0.5))
    low = pc.less(table["airflow_cfm"], cfg["min_airflow_cfm"])
    return pc.and_(fan_on, low)
"""
    table = pa.table({"fan_cmd": [1.0, 0.0, 1.0], "airflow_cfm": [100.0, 5000.0, 8000.0]})
    result = run_arrow_rule(code, table, {"min_airflow_cfm": 1000})
    assert result.true_count == 1


def test_invalid_missing_apply_faults_arrow():
    import pytest

    with pytest.raises(ValueError, match="apply_faults_arrow"):
        compile_apply_faults_arrow("def evaluate(row, cfg):\n    return True\n")


def test_invalid_result_type():
    code = """def apply_faults_arrow(table, cfg, context=None):
    return 42
"""
    table = pa.table({"zone_temp": [1.0, 2.0, 3.0]})
    result = run_arrow_rule(code, table, {})
    assert result.errors
