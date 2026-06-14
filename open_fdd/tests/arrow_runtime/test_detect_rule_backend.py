from __future__ import annotations

import pytest

from open_fdd.arrow_runtime.datafusion_backend import lint_datafusion_sql_rule
from open_fdd.arrow_runtime.rules import detect_rule_backend, legacy_row_allowed


def test_legacy_row_still_gated():
    code = "def evaluate(row, cfg):\n    return True\n"
    assert detect_rule_backend(code, {}) == "legacy_row"
    assert not legacy_row_allowed({})


def test_detect_backends_matrix():
    assert detect_rule_backend("", {"backend": "arrow"}) == "arrow"
    assert detect_rule_backend("", {"backend": "datafusion_sql", "sql": "SELECT 1 AS fault FROM telemetry"}) == "datafusion_sql"
    assert detect_rule_backend("", {"mode": "script"}) == "script"
