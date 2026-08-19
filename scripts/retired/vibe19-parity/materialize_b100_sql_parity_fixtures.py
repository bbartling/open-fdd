#!/usr/bin/env python3
"""Executable oracle fixtures for AHU-DUCTHI, ECON-1, ECON-2, CHW-NOLOAD-1."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "crates/fdd_rules/fixtures/oracle"


def ts_rows(n: int, step_s: int = 300) -> list[datetime]:
    t0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    return [t0 + timedelta(seconds=i * step_s) for i in range(n)]


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_case(rule: str, case: str, header: str, lines: list[str], expected: dict, columns: str) -> None:
    d = ORACLE / rule / case
    d.mkdir(parents=True, exist_ok=True)
    (d / "history_wide.csv").write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    (d / "columns.csv").write_text(columns, encoding="utf-8")
    (d / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    (d / "README.md").write_text(
        f"# Fixture — `{rule}` / `{case}`\n\nB100-validated screening fixture.\n",
        encoding="utf-8",
    )


def expected(rule: str, any_fault: bool, *, missing: bool = False, eq_type: str = "AHU") -> dict:
    out = {
        "pandas_rule_id": rule,
        "equipment_id": "EQ_1",
        "equipment_type": eq_type,
        "poll_seconds": 300,
        "any_fault": any_fault,
        "datafusion_compare": "pending",
    }
    if missing:
        out["expect_missing_roles"] = True
        out["any_fault"] = False
        out["expect_status"] = "SKIPPED_MISSING_ROLES"
    return out


def ahu_ducthi() -> None:
    cols = (
        "col,point_role\n"
        "duct_static,duct-static-pressure\n"
        "duct_static_sp,duct-static-pressure-sp\n"
        "fan_status,fan-status\n"
        "fan_cmd,fan-cmd\n"
    )
    header = "timestamp_utc,duct_static,duct_static_sp,fan_status,fan_cmd"
    times = ts_rows(24)
    # Frozen 7" overnight, fan proven off — must not fault.
    write_case(
        "AHU-DUCTHI",
        "equipment_off",
        header,
        [f"{fmt(t)},7.2,1.2,0,0" for t in times],
        expected("AHU-DUCTHI", False),
        cols,
    )
    # Fan on, static above SP+margin.
    write_case(
        "AHU-DUCTHI",
        "fault",
        header,
        [f"{fmt(t)},2.0,1.2,1,1" for t in times],
        expected("AHU-DUCTHI", True),
        cols,
    )
    write_case(
        "AHU-DUCTHI",
        "normal",
        header,
        [f"{fmt(t)},1.25,1.2,1,1" for t in times],
        expected("AHU-DUCTHI", False),
        cols,
    )


def econ2() -> None:
    cols = (
        "col,point_role\n"
        "oa_t,outside-air-temp\n"
        "oa_damper_pct,outside-air-damper\n"
        "fan_status,fan-status\n"
        "fan_cmd,fan-cmd\n"
    )
    header = "timestamp_utc,oa_t,oa_damper_pct,fan_status,fan_cmd"
    times = ts_rows(24)
    # 20% OA (0–100 scale) is not > 0.42 after /100.
    write_case(
        "ECON-2",
        "normal",
        header,
        [f"{fmt(t)},70,20,1,1" for t in times],
        expected("ECON-2", False),
        cols,
    )
    # 50% on 0–1 scale while OAT high.
    write_case(
        "ECON-2",
        "fault",
        header,
        [f"{fmt(t)},70,0.55,1,1" for t in times],
        expected("ECON-2", True),
        cols,
    )
    write_case(
        "ECON-2",
        "equipment_off",
        header,
        [f"{fmt(t)},70,0.55,0,0" for t in times],
        expected("ECON-2", False),
        cols,
    )


def econ1() -> None:
    cols = (
        "col,point_role\n"
        "oa_t,outside-air-temp\n"
        "oa_damper_pct,outside-air-damper\n"
        "fan_status,fan-status\n"
        "fan_cmd,fan-cmd\n"
    )
    header = "timestamp_utc,oa_t,oa_damper_pct,fan_status,fan_cmd"
    times = ts_rows(24)
    # Stuck closed; fan_status on, fan_cmd off (pandas uses status first).
    write_case(
        "ECON-1",
        "fault",
        header,
        [f"{fmt(t)},70,0,1,1" for t in times],
        expected("ECON-1", True),
        cols,
    )
    write_case(
        "ECON-1",
        "normal",
        header,
        [f"{fmt(t)},70,0.4,1,1" for t in times],
        expected("ECON-1", False),
        cols,
    )
    # 0–100 damper still closed.
    write_case(
        "ECON-1",
        "irregular_sampling",
        header,
        [f"{fmt(t)},70,2,1,1" for t in times],
        expected("ECON-1", True),
        cols,
    )


def chw() -> None:
    cols = (
        "col,point_role\n"
        "chiller_status,chiller-status\n"
        "chw_pump_cmd,chw-pump-cmd\n"
        "building_zone_load_satisfied,building-zone-load-satisfied\n"
    )
    header = "timestamp_utc,chiller_status,chw_pump_cmd,building_zone_load_satisfied"
    times = ts_rows(24)
    write_case(
        "CHW-NOLOAD-1",
        "fault",
        header,
        [f"{fmt(t)},1,80,1" for t in times],
        expected("CHW-NOLOAD-1", True, eq_type="CHILLER"),
        cols,
    )
    write_case(
        "CHW-NOLOAD-1",
        "normal",
        header,
        [f"{fmt(t)},1,80,0" for t in times],
        expected("CHW-NOLOAD-1", False, eq_type="CHILLER"),
        cols,
    )
    write_case(
        "CHW-NOLOAD-1",
        "missing_required_role",
        "timestamp_utc,chiller_status,chw_pump_cmd",
        [f"{fmt(t)},1,80" for t in times],
        expected("CHW-NOLOAD-1", False, missing=True, eq_type="CHILLER"),
        "col,point_role\nchiller_status,chiller-status\nchw_pump_cmd,chw-pump-cmd\n",
    )


def main() -> None:
    ahu_ducthi()
    econ2()
    econ1()
    chw()
    print("OK: B100 SQL parity fixtures")


if __name__ == "__main__":
    main()
