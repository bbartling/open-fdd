"""Golden Arrow vs DataFusion SQL parity for paired FDD rules."""

from __future__ import annotations

from datetime import datetime, timezone

import pyarrow as pa
import pytest

from open_fdd.arrow_runtime.backend import run_arrow_rule
from open_fdd.arrow_runtime.datafusion_backend import datafusion_available, run_datafusion_sql_rule
from open_fdd.validation.paired_fdd_contract import (
    OAT_SPREAD_ARROW_CODE,
    ZN_T_BOUNDS_ARROW_CODE,
    oat_spread_sql,
    phase_config,
    zn_t_bounds_sql,
)
from open_fdd.validation.paired_fdd_parity import compare_fault_masks, mask_value_counts


def _ts_table(rows: list[dict]) -> pa.Table:
    return pa.table(
        {
            "timestamp": [r["timestamp"] for r in rows],
            "equipment": [r.get("equipment", "AHU-1") for r in rows],
            "stat_zn-t": [r.get("stat_zn-t") for r in rows],
            "oa-t": [r.get("oa-t") for r in rows],
            "web-oat-t": [r.get("web-oat-t") for r in rows],
        }
    )


def _run_pair(*, table: pa.Table, arrow_code: str, sql: str, cfg: dict, rule_id: str = "test"):
    arrow_res = run_arrow_rule(arrow_code, table, cfg, rule_id=rule_id)
    assert not arrow_res.errors, arrow_res.errors
    if not datafusion_available():
        pytest.skip("datafusion not installed")
    sql_res = run_datafusion_sql_rule(sql, table, cfg, rule_id=rule_id)
    assert not sql_res.errors, sql_res.errors
    return arrow_res.fault_mask, sql_res.fault_mask


@pytest.mark.parametrize(
    "rows,phase",
    [
        (
            [
                {"timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "stat_zn-t": 70.0},
                {"timestamp": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc), "stat_zn-t": 72.0},
            ],
            "normal",
        ),
        (
            [
                {"timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc), "stat_zn-t": 99.5},
                {"timestamp": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc), "stat_zn-t": 100.0},
            ],
            "blatant",
        ),
    ],
)
def test_zn_t_bounds_arrow_sql_row_parity(rows, phase):
    table = _ts_table(rows)
    cfg = phase_config("bench", phase)
    sql = zn_t_bounds_sql(float(cfg["low"]), float(cfg["high"]))
    arrow_mask, sql_mask = _run_pair(table=table, arrow_code=ZN_T_BOUNDS_ARROW_CODE, sql=sql, cfg=cfg)
    result = compare_fault_masks(arrow_mask, sql_mask, table=table)
    assert result["pass"], result["issues"]


def test_zn_t_null_and_missing_column():
    table = pa.table(
        {
            "timestamp": [datetime(2026, 1, 1, tzinfo=timezone.utc)],
            "equipment": ["AHU-1"],
            "stat_zn-t": [None],
        }
    )
    cfg = phase_config("bench", "normal")
    sql = zn_t_bounds_sql(float(cfg["low"]), float(cfg["high"]))
    arrow_mask, sql_mask = _run_pair(table=table, arrow_code=ZN_T_BOUNDS_ARROW_CODE, sql=sql, cfg=cfg)
    assert compare_fault_masks(arrow_mask, sql_mask)["pass"]
    counts = mask_value_counts(arrow_mask)
    assert counts["row_count"] == 1
    assert counts["true_count"] == 0
    assert counts["false_count"] == 1


def test_oat_spread_parity_with_nulls():
    table = pa.table(
        {
            "timestamp": [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)],
            "equipment": ["SITE", "SITE"],
            "oa-t": [32.0, None],
            "web-oat-t": [32.1, 40.0],
        }
    )
    cfg = phase_config("acme", "normal")
    sql = oat_spread_sql(float(cfg["max_spread_f"]), str(cfg["local_oat_column"]), str(cfg["web_oat_column"]))
    arrow_mask, sql_mask = _run_pair(table=table, arrow_code=OAT_SPREAD_ARROW_CODE, sql=sql, cfg=cfg)
    assert compare_fault_masks(arrow_mask, sql_mask, table=table)["pass"]


def test_duplicate_timestamps_same_mask():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    table = _ts_table(
        [
            {"timestamp": ts, "stat_zn-t": 80.0, "equipment": "AHU-1"},
            {"timestamp": ts, "stat_zn-t": 80.0, "equipment": "AHU-2"},
        ]
    )
    cfg = phase_config("bench", "normal")
    sql = zn_t_bounds_sql(float(cfg["low"]), float(cfg["high"]))
    arrow_mask, sql_mask = _run_pair(table=table, arrow_code=ZN_T_BOUNDS_ARROW_CODE, sql=sql, cfg=cfg)
    assert compare_fault_masks(arrow_mask, sql_mask)["pass"]
