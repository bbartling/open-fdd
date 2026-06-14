from __future__ import annotations

import pytest

from open_fdd.arrow_runtime.datafusion_backend import lint_datafusion_sql_rule

GOOD_SQL = """SELECT
  *,
  zone_temp > 75.0 AS fault
FROM telemetry"""


def test_rules_lab_lint_sql_endpoint_shape():
    lint = lint_datafusion_sql_rule(GOOD_SQL)
    assert lint["ok"] is True


def test_rules_lab_lint_rejects_insert():
    lint = lint_datafusion_sql_rule("INSERT INTO telemetry VALUES (1)")
    assert lint["ok"] is False
