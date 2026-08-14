#!/usr/bin/env python3
"""Materialize VAV-7 / VAV-4 / FC7 oracle CSVs (screening-level expected.json)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "crates/fdd_rules/fixtures/oracle"
CASES = (
    "normal",
    "fault",
    "threshold_boundary",
    "missing_required_role",
    "equipment_off",
    "startup_delay",
    "irregular_sampling",
    "data_gap",
    "duplicate_timestamp",
    "out_of_order",
)


def ts_rows(n: int, step_s: int = 300, start: datetime | None = None) -> list[datetime]:
    t0 = start or datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    return [t0 + timedelta(seconds=i * step_s) for i in range(n)]


def write_case(rule: str, case: str, header: str, lines: list[str], expected: dict, columns: str) -> None:
    d = ORACLE / rule / case
    d.mkdir(parents=True, exist_ok=True)
    (d / "history_wide.csv").write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    (d / "columns.csv").write_text(columns, encoding="utf-8")
    (d / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    readme = d / "README.md"
    if readme.is_file():
        txt = readme.read_text(encoding="utf-8")
        if "Wave 0 placeholder" in txt:
            readme.write_text(
                f"# Fixture — `{rule}` / `{case}`\n\nExecutable screening fixture (history + expected).\n",
                encoding="utf-8",
            )


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def vav7() -> None:
    cols = "col,point_role\nzone_flow,zone-airflow\nmin_flow_sp,min-flow-sp\nfan_status,fan-status\n"
    header = "timestamp_utc,zone_flow,min_flow_sp,fan_status"
    for case in CASES:
        times = ts_rows(24)
        fault = case == "fault"
        if case == "missing_required_role":
            header_m = "timestamp_utc,min_flow_sp,fan_status"
            lines = [f"{fmt(t)},200,1" for t in times]
            write_case(
                "VAV-7",
                case,
                header_m,
                lines,
                {
                    "pandas_rule_id": "VAV-7",
                    "equipment_id": "VAV_1",
                    "equipment_type": "VAV",
                    "poll_seconds": 300,
                    "any_fault": False,
                    "expect_status": "SKIPPED_MISSING_ROLES",
                    "datafusion_compare": "pending",
                },
                "col,point_role\nmin_flow_sp,min-flow-sp\nfan_status,fan-status\n",
            )
            continue
        lines = []
        for i, t in enumerate(times):
            if case == "equipment_off":
                flow, fan = 0, 0
            elif case == "fault":
                flow, fan = 40, 1
            elif case == "threshold_boundary":
                flow, fan = 200, 1
            elif case == "startup_delay":
                flow, fan = (40, 1) if i < 4 else (400, 1)
            elif case == "data_gap" and 8 <= i <= 12:
                continue
            else:
                flow, fan = 180 + (i % 8) * 40, 1
            tt = t
            if case == "irregular_sampling":
                tt = times[0] + timedelta(seconds=i * (180 if i % 2 == 0 else 420))
            lines.append(f"{fmt(tt)},{flow},200,{fan}")
        if case == "duplicate_timestamp" and lines:
            lines.append(lines[3])
        if case == "out_of_order":
            lines = list(reversed(lines))
        exp = {
            "pandas_rule_id": "VAV-7",
            "equipment_id": "VAV_1",
            "equipment_type": "VAV",
            "poll_seconds": 300,
            "datafusion_compare": "pending",
            "notes": "screening fixture; duration parity not claimed",
        }
        if fault:
            exp["any_fault"] = True
        write_case(
            "VAV-7",
            case,
            header,
            lines,
            exp,
            cols,
        )


def vav4() -> None:
    cols = "col,point_role\ndamper_pct,damper\nzone_flow,zone-airflow\nfan_status,fan-status\n"
    header = "timestamp_utc,damper_pct,zone_flow,fan_status"
    for case in CASES:
        times = ts_rows(48)
        fault = case == "fault"
        if case == "missing_required_role":
            lines = [f"{fmt(t)},400,1" for t in times]
            write_case(
                "VAV-4",
                case,
                "timestamp_utc,zone_flow,fan_status",
                lines,
                {
                    "pandas_rule_id": "VAV-4",
                    "equipment_id": "VAV_1",
                    "equipment_type": "VAV",
                    "poll_seconds": 300,
                    "any_fault": False,
                    "expect_status": "SKIPPED_MISSING_ROLES",
                    "datafusion_compare": "pending",
                },
                "col,point_role\nzone_flow,zone-airflow\nfan_status,fan-status\n",
            )
            continue
        lines = []
        for i, t in enumerate(times):
            if case == "equipment_off":
                dmp, flow, fan = 0.99, 0, 0
            elif case == "fault":
                dmp, flow, fan = 0.99, 400, 1
            elif case == "threshold_boundary":
                dmp, flow, fan = 0.975, 400, 1
            elif case == "startup_delay":
                dmp, flow, fan = (0.99, 400, 1) if i < 6 else (0.4, 400, 1)
            elif case == "data_gap" and 10 <= i <= 16:
                continue
            else:
                dmp, flow, fan = 0.4, 400, 1
            tt = t
            if case == "irregular_sampling":
                tt = times[0] + timedelta(seconds=i * 240)
            lines.append(f"{fmt(tt)},{dmp},{flow},{fan}")
        if case == "duplicate_timestamp" and lines:
            lines.append(lines[2])
        if case == "out_of_order":
            lines = list(reversed(lines))
        exp = {
            "pandas_rule_id": "VAV-4",
            "equipment_id": "VAV_1",
            "equipment_type": "VAV",
            "poll_seconds": 300,
            "datafusion_compare": "pending",
            "notes": "sequential sustain then confirm; screening expected",
        }
        if fault:
            exp["any_fault"] = True
        write_case(
            "VAV-4",
            case,
            header,
            lines,
            exp,
            cols,
        )


def fc7() -> None:
    cols = "col,point_role\nsat,discharge-air-temp\nsat_sp,discharge-air-temp-sp\nhtg_valve_pct,heating-valve\nfan_status,fan-cmd\n"
    header = "timestamp_utc,sat,sat_sp,htg_valve_pct,fan_status"
    for case in CASES:
        times = ts_rows(24)
        fault = case == "fault"
        if case == "missing_required_role":
            lines = [f"{fmt(t)},55,0.95,1" for t in times]
            write_case(
                "FC7",
                case,
                "timestamp_utc,sat_sp,htg_valve_pct,fan_status",
                lines,
                {
                    "pandas_rule_id": "FC7",
                    "equipment_id": "AHU_1",
                    "equipment_type": "AHU",
                    "poll_seconds": 300,
                    "any_fault": False,
                    "expect_status": "SKIPPED_MISSING_ROLES",
                    "datafusion_compare": "pending",
                },
                "col,point_role\nsat_sp,discharge-air-temp-sp\nhtg_valve_pct,heating-valve\nfan_status,fan-cmd\n",
            )
            continue
        lines = []
        for i, t in enumerate(times):
            if case == "equipment_off":
                sat, htg, fan = 50, 0.99, 0
            elif case == "fault":
                sat, htg, fan = 50, 0.95, 1
            elif case == "threshold_boundary":
                sat, htg, fan = 54, 0.90, 1
            elif case == "startup_delay":
                sat, htg, fan = (50, 0.95, 1) if i < 3 else (55, 0.2, 1)
            elif case == "data_gap" and 6 <= i <= 10:
                continue
            else:
                sat, htg, fan = 55, 0.1, 1
            tt = t
            if case == "irregular_sampling":
                tt = times[0] + timedelta(seconds=i * 330)
            lines.append(f"{fmt(tt)},{sat},55,{htg},{fan}")
        if case == "duplicate_timestamp" and lines:
            lines.append(lines[1])
        if case == "out_of_order":
            lines = list(reversed(lines))
        exp = {
            "pandas_rule_id": "FC7",
            "equipment_id": "AHU_1",
            "equipment_type": "AHU",
            "poll_seconds": 300,
            "datafusion_compare": "pending",
            "notes": "htg_valve_pct >= HTG_FULL_MIN; screening",
        }
        if fault:
            exp["any_fault"] = True
        write_case(
            "FC7",
            case,
            header,
            lines,
            exp,
            cols,
        )


if __name__ == "__main__":
    vav7()
    vav4()
    fc7()
    print("materialized VAV-7 VAV-4 FC7 oracle fixtures")
