#!/usr/bin/env python3
"""Register bench PyArrow + DataFusion SQL FDD rules for device 5007 sensors."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
sys.path.insert(0, str(API))
os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))

from openfdd_bridge.playground import lint_python  # noqa: E402
from openfdd_bridge.rule_store import RuleStore  # noqa: E402
from open_fdd.arrow_runtime.datafusion_backend import lint_datafusion_sql_rule  # noqa: E402

RULES_PY = REPO / "workspace" / "data" / "rules_py"
OA_POINT = "5007-analog-input-1173"
SQL = """
SELECT
  *,
  "oa-t" > 85.0 AS fault
FROM telemetry
"""


def main() -> None:
    store = RuleStore()
    arrow_code = (RULES_PY / "bench_oa_temp_high_arrow.py").read_text(encoding="utf-8")
    lint = lint_python(arrow_code)
    if not lint["ok"]:
        raise SystemExit(f"Arrow lint failed: {lint}")
    store.upsert(
        {
            "id": "bench-oa-temp-high-arrow",
            "name": "Bench OA-T high (PyArrow)",
            "short_description": "Outside air temperature above threshold on bench device 5007.",
            "mode": "rule",
            "backend": "arrow",
            "code": arrow_code,
            "config": {"high": 85.0},
            "bindings": {"point_ids": [OA_POINT], "equipment_ids": [], "brick_types": []},
            "severity": "warning",
            "enabled": True,
        },
        saved_by="register_bench_sql_arrow_rules",
    )
    sql_lint = lint_datafusion_sql_rule(SQL)
    if not sql_lint["ok"]:
        raise SystemExit(f"SQL lint failed: {sql_lint}")
    store.upsert(
        {
            "id": "bench-oa-temp-high-sql",
            "name": "Bench OA-T high (DataFusion SQL)",
            "short_description": "SQL threshold on oa-t historian column.",
            "mode": "rule",
            "backend": "datafusion_sql",
            "code": "# datafusion_sql rule — see sql field",
            "sql": SQL.strip(),
            "fault_column": "fault",
            "config": {},
            "bindings": {"point_ids": [OA_POINT], "equipment_ids": [], "brick_types": []},
            "severity": "warning",
            "enabled": True,
        },
        saved_by="register_bench_sql_arrow_rules",
    )
    print("Registered bench-oa-temp-high-arrow and bench-oa-temp-high-sql")


if __name__ == "__main__":
    main()
