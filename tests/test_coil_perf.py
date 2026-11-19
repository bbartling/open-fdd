"""#1641 COIL-PERF in pandas: the same cases as nf-app/tests/coil-perf.test.mjs (PGlite, SQLite) give the same answer."""

import json
from pathlib import Path

import pandas as pd
import pytest

from open_fdd.parity.pandas_ref import pandas_rule_result

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/coil_perf_cases.json").read_text(encoding="utf-8"))["cases"]
ROLE_MAP = json.loads((ROOT / "sql/fdd/role_map.json").read_text(encoding="utf-8"))


def _frame(row):
    idx = pd.date_range("2026-01-01", periods=49, freq="5min", tz="UTC")
    d = pd.DataFrame({ROLE_MAP[k]: float(v) for k, v in row.items()}, index=idx)
    d.attrs.update({"equipment_id": "ahu-1", "site_id": "s", "run_proof_resolved": True})
    return d


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_coil_perf_pandas_matches_the_sql_cases(case):
    hours, status, res = pandas_rule_result("COIL-PERF", _frame(case["row"]), None, 300.0)
    if isinstance(case["expect"], str):
        assert status == f"NOT_ASSESSED_{case['expect'].upper()}", (status, res.notes if res else None)
        assert hours is None
    else:
        assert status in ("FAULT", "PASS"), status
        assert hours == pytest.approx(case["expect"], abs=1e-5)
