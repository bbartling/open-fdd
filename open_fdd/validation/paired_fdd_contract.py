"""Hardcoded paired FDD smoke contract — bensserver bench 5007 + Acme OAT/web.

Do not change rule IDs or phase thresholds without updating docs and harness reports.
"""

from __future__ import annotations

from typing import Any

PHASE_NORMAL = "normal"
PHASE_BLATANT = "blatant"

CONFIRMATION_CFG: dict[str, Any] = {
    "min_elapsed_minutes": 5,
    "min_true_rows": 5,
    "poll_interval_s": 60,
    "timestamp_column": "timestamp",
}

# Bench stat_zn-t — BACnet 5007 + Niagara bench9065
BENCH_SITE_ID = "demo"
BENCH_BACNET_POINT_ID = "5007-analog-input-10014"
BENCH_NIAGARA_POINT_ID = "niagara-bench9065-fa1b48f7f0"
BENCH_VALUE_COLUMN = "stat_zn-t"

BENCH_BOUNDS: dict[str, dict[str, float | str]] = {
    PHASE_NORMAL: {"low": 65.0, "high": 75.0, "value_column": BENCH_VALUE_COLUMN},
    PHASE_BLATANT: {"low": 99.0, "high": 100.0, "value_column": BENCH_VALUE_COLUMN},
}

# Acme local OAT vs OpenWeather web-oat-t
ACME_SITE_ID = "acme"
ACME_SPREAD_CFG: dict[str, dict[str, float | str]] = {
    PHASE_NORMAL: {
        "local_oat_column": "oa-t",
        "web_oat_column": "web-oat-t",
        "max_spread_f": 10.0,
    },
    PHASE_BLATANT: {
        "local_oat_column": "oa-t",
        "web_oat_column": "web-oat-t",
        "max_spread_f": 0.001,
    },
}

RULE_BENCH_BACNET_SQL = "smoke-paired-zn-t-bacnet-sql"
RULE_BENCH_BACNET_ARROW = "smoke-paired-zn-t-bacnet-arrow"
RULE_BENCH_NIAGARA_ARROW = "smoke-paired-zn-t-niagara-arrow"
RULE_BENCH_NIAGARA_SQL = "smoke-paired-zn-t-niagara-sql"
RULE_ACME_OAT_ARROW = "smoke-paired-oat-spread-arrow"
RULE_ACME_OAT_SQL = "smoke-paired-oat-spread-sql"

SMOKE_RULE_IDS = (
    RULE_BENCH_BACNET_SQL,
    RULE_BENCH_BACNET_ARROW,
    RULE_BENCH_NIAGARA_ARROW,
    RULE_BENCH_NIAGARA_SQL,
    RULE_ACME_OAT_ARROW,
    RULE_ACME_OAT_SQL,
)

MODES: dict[str, dict[str, int]] = {
    "tryout": {"duration_minutes": 6, "toggle_interval_minutes": 3},
    "short": {"duration_minutes": 30, "toggle_interval_minutes": 15},
    "standard": {"duration_minutes": 120, "toggle_interval_minutes": 15},
    "overnight": {"duration_minutes": 720, "toggle_interval_minutes": 15},
}

ZN_T_BOUNDS_ARROW_CODE = '''import pyarrow as pa
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    col = str(cfg.get("value_column") or "stat_zn-t")
    low = float(cfg.get("low", 65))
    high = float(cfg.get("high", 75))
    if col not in table.column_names:
        return pa.array([False] * table.num_rows, type=pa.bool_())
    v = pc.cast(table[col], pa.float64())
    return pc.or_(pc.less(v, low), pc.greater(v, high))
'''

OAT_SPREAD_ARROW_CODE = '''import pyarrow as pa
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    local = str(cfg.get("local_oat_column") or "oa-t")
    web = str(cfg.get("web_oat_column") or "web-oat-t")
    spread = float(cfg.get("max_spread_f") or 8.0)
    if local not in table.column_names or web not in table.column_names:
        return pa.array([False] * table.num_rows, type=pa.bool_())
    a = pc.cast(table[local], pa.float64())
    b = pc.cast(table[web], pa.float64())
    return pc.greater(pc.abs(pc.subtract(a, b)), spread)
'''


def _sql_quote(col: str) -> str:
    return '"' + str(col).replace('"', '""') + '"'


def zn_t_bounds_sql(low: float, high: float, column: str = BENCH_VALUE_COLUMN) -> str:
    c = _sql_quote(column)
    return f"SELECT *, ({c} < {float(low)} OR {c} > {float(high)}) AS fault FROM telemetry"


def oat_spread_sql(max_spread_f: float, local: str = "oa-t", web: str = "web-oat-t") -> str:
    return (
        f"SELECT *, abs({_sql_quote(local)} - {_sql_quote(web)}) > {float(max_spread_f)} AS fault "
        "FROM telemetry"
    )


def phase_config(site: str, phase: str) -> dict[str, Any]:
    base = dict(CONFIRMATION_CFG)
    if site == "bench":
        base.update(BENCH_BOUNDS[phase])
    else:
        base.update(ACME_SPREAD_CFG[phase])
    return base


def bench_rules_for_phase(phase: str) -> list[dict[str, Any]]:
    cfg = phase_config("bench", phase)
    sql = zn_t_bounds_sql(float(cfg["low"]), float(cfg["high"]))
    return [
        {
            "id": RULE_BENCH_BACNET_SQL,
            "name": "Smoke paired ZN-T bounds (BACnet SQL)",
            "short_description": "Zone temp out of bounds — BACnet DataFusion SQL",
            "backend": "datafusion_sql",
            "sql": sql,
            "fault_column": "fault",
            "code": ZN_T_BOUNDS_ARROW_CODE,
            "config": cfg,
            "bindings": {"point_ids": [BENCH_BACNET_POINT_ID]},
            "severity": "warning",
            "enabled": True,
        },
        {
            "id": RULE_BENCH_BACNET_ARROW,
            "name": "Smoke paired ZN-T bounds (BACnet PyArrow)",
            "short_description": "Zone temp out of bounds — BACnet PyArrow parity",
            "backend": "arrow",
            "code": ZN_T_BOUNDS_ARROW_CODE,
            "config": cfg,
            "bindings": {"point_ids": [BENCH_BACNET_POINT_ID]},
            "severity": "warning",
            "enabled": True,
        },
        {
            "id": RULE_BENCH_NIAGARA_ARROW,
            "name": "Smoke paired ZN-T bounds (Niagara PyArrow)",
            "short_description": "Zone temp out of bounds — Niagara PyArrow",
            "backend": "arrow",
            "code": ZN_T_BOUNDS_ARROW_CODE,
            "config": cfg,
            "bindings": {"point_ids": [BENCH_NIAGARA_POINT_ID]},
            "severity": "warning",
            "enabled": True,
        },
        {
            "id": RULE_BENCH_NIAGARA_SQL,
            "name": "Smoke paired ZN-T bounds (Niagara SQL)",
            "short_description": "Zone temp out of bounds — Niagara DataFusion parity",
            "backend": "datafusion_sql",
            "sql": sql,
            "fault_column": "fault",
            "code": ZN_T_BOUNDS_ARROW_CODE,
            "config": cfg,
            "bindings": {"point_ids": [BENCH_NIAGARA_POINT_ID]},
            "severity": "warning",
            "enabled": True,
        },
    ]


def acme_rules_for_phase(phase: str) -> list[dict[str, Any]]:
    cfg = phase_config("acme", phase)
    spread = float(cfg["max_spread_f"])
    local = str(cfg["local_oat_column"])
    web = str(cfg["web_oat_column"])
    sql = oat_spread_sql(spread, local=local, web=web)
    return [
        {
            "id": RULE_ACME_OAT_ARROW,
            "name": "Smoke paired OAT vs web (PyArrow)",
            "short_description": "Local OAT vs OpenWeather spread — PyArrow",
            "backend": "arrow",
            "code": OAT_SPREAD_ARROW_CODE,
            "config": cfg,
            "bindings": {"brick_types": ["Outside_Air_Temperature_Sensor"]},
            "severity": "warning",
            "enabled": True,
        },
        {
            "id": RULE_ACME_OAT_SQL,
            "name": "Smoke paired OAT vs web (DataFusion SQL)",
            "short_description": "Local OAT vs OpenWeather spread — DataFusion SQL",
            "backend": "datafusion_sql",
            "sql": sql,
            "fault_column": "fault",
            "code": OAT_SPREAD_ARROW_CODE,
            "config": cfg,
            "bindings": {"brick_types": ["Outside_Air_Temperature_Sensor"]},
            "severity": "warning",
            "enabled": True,
        },
    ]
