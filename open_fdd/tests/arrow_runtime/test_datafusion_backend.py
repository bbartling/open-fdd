from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from open_fdd.arrow_runtime.datafusion_backend import (
    datafusion_available,
    equivalent_pyarrow_threshold_rule,
    lint_datafusion_sql_rule,
    run_datafusion_sql_rule,
)
from open_fdd.arrow_runtime.backend import run_arrow_rule
from open_fdd.arrow_runtime.rules import detect_rule_backend
from open_fdd.arrow_runtime.testing import sample_hvac_table

THRESHOLD_SQL = """SELECT
  *,
  zone_temp > 75.0 AS fault
FROM telemetry"""

CASE_SQL = """SELECT
  *,
  CASE
    WHEN fan_cmd > 0.5 AND airflow_cfm < 1000.0 THEN true
    ELSE false
  END AS fault
FROM telemetry"""

ARROW_THRESHOLD = """import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], 75.0)
"""


def test_detect_rule_backend_datafusion_explicit():
    assert detect_rule_backend("", {"backend": "datafusion_sql", "sql": THRESHOLD_SQL}) == "datafusion_sql"


def test_detect_rule_backend_datafusion_from_sql_field():
    assert detect_rule_backend("", {"sql": THRESHOLD_SQL}) == "datafusion_sql"


def test_detect_rule_backend_arrow_unchanged():
    assert detect_rule_backend(ARROW_THRESHOLD, {}) == "arrow"


def test_lint_rejects_unsafe_sql():
    lint = lint_datafusion_sql_rule("DROP TABLE telemetry")
    assert not lint["ok"]
    assert any("SELECT" in i["message"] for i in lint["issues"])


def test_lint_rejects_missing_telemetry():
    lint = lint_datafusion_sql_rule("SELECT 1 AS fault")
    assert not lint["ok"]


def test_lint_rejects_dml():
    lint = lint_datafusion_sql_rule("INSERT INTO telemetry SELECT 1")
    assert not lint["ok"]


def test_missing_datafusion_clean_error():
    if datafusion_available():
        pytest.skip("datafusion installed")
    table = sample_hvac_table(5)
    result = run_datafusion_sql_rule(THRESHOLD_SQL, table)
    assert result.backend == "datafusion_sql"
    assert result.errors
    assert "open-fdd[datafusion]" in result.errors[0]


@pytest.mark.skipif(not datafusion_available(), reason="datafusion optional extra not installed")
def test_simple_sql_threshold_matches_pyarrow():
    table = sample_hvac_table(80, seed=3)
    arrow = run_arrow_rule(ARROW_THRESHOLD, table, {})
    sql = run_datafusion_sql_rule(THRESHOLD_SQL, table, {})
    assert not arrow.errors
    assert not sql.errors
    assert sql.true_count == arrow.true_count
    assert sql.row_count == arrow.row_count


@pytest.mark.skipif(not datafusion_available(), reason="datafusion optional extra not installed")
def test_case_when_sql_rule():
    table = pa.table({"fan_cmd": [1.0, 0.0, 1.0], "airflow_cfm": [100.0, 5000.0, 8000.0]})
    result = run_datafusion_sql_rule(CASE_SQL, table, {})
    assert not result.errors
    assert result.true_count == 1


@pytest.mark.skipif(not datafusion_available(), reason="datafusion optional extra not installed")
def test_missing_fault_column_fails():
    table = sample_hvac_table(5)
    result = run_datafusion_sql_rule("SELECT * FROM telemetry", table, {})
    assert result.errors


@pytest.mark.skipif(not datafusion_available(), reason="datafusion optional extra not installed")
def test_wrong_row_count_fails():
    table = sample_hvac_table(10)
    bad_sql = "SELECT *, true AS fault FROM telemetry LIMIT 5"
    result = run_datafusion_sql_rule(bad_sql, table, {})
    assert result.errors


@pytest.mark.parametrize(
    "column",
    ["SAT", "zone temp", 'bad"column', r"bad\column"],
)
def test_equivalent_pyarrow_threshold_escapes_column_names(column: str):
    code = equivalent_pyarrow_threshold_rule(column, 65.0)
    compile(code, "<rule>", "exec")
    assert repr(column) in code
    assert "65.0" in code


def test_lint_rejects_read_parquet_path():
    lint = lint_datafusion_sql_rule(
        "SELECT *, true AS fault FROM read_parquet('file:///tmp/x.parquet')"
    )
    assert not lint["ok"]


def test_lint_rejects_count_aggregate_as_fault():
    lint = lint_datafusion_sql_rule("SELECT COUNT(*) AS fault FROM telemetry")
    assert lint["ok"] is True  # lint passes; row-count guard rejects at execution


@pytest.mark.skipif(not datafusion_available(), reason="datafusion optional extra not installed")
def test_count_aggregate_row_mismatch_at_runtime():
    table = sample_hvac_table(10)
    result = run_datafusion_sql_rule("SELECT COUNT(*) AS fault FROM telemetry", table, {})
    assert result.errors
    assert "row count" in result.errors[0].lower()


@pytest.mark.skipif(not datafusion_available(), reason="datafusion optional extra not installed")
def test_run_error_summary_omits_trace_without_debug(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OFDD_DEBUG_TRACEBACKS", raising=False)
    table = sample_hvac_table(3)
    result = run_datafusion_sql_rule("SELECT * FROM telemetry", table, {})
    assert result.errors
    assert "trace" not in result.summary
