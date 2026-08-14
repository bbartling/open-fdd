#!/usr/bin/env python3
"""Materialize VAV-2 / VAV-6 / RESET-1 oracle CSVs (screening-level expected.json)."""
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
    (d / "README.md").write_text(
        f"# Fixture — `{rule}` / `{case}`\n\nExecutable screening fixture (history + expected).\n",
        encoding="utf-8",
    )


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def base_expected(rule: str, any_fault: bool, missing: bool = False) -> dict:
    eq_type = "AHU" if rule == "RESET-1" else "VAV"
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


def vav2() -> None:
    cols = "col,point_role\nzone_t,zone-air-temp\nocc_mode,occupied\n"
    header = "timestamp_utc,zone_t,occ_mode"
    for case in CASES:
        times = ts_rows(24)
        if case == "missing_required_role":
            write_case(
                "VAV-2",
                case,
                "timestamp_utc,occ_mode",
                [f"{fmt(t)},unoccupied" for t in times],
                base_expected("VAV-2", False, missing=True),
                "col,point_role\nocc_mode,occupied\n",
            )
            continue
        lines = []
        for i, t in enumerate(times):
            occ = "unoccupied"
            zt = 72.0
            if case == "normal":
                zt = 62.0
            elif case == "threshold_boundary":
                zt = 68.0
            elif case == "equipment_off":
                occ = "occupied"
                zt = 72.0
            elif case == "startup_delay" and i < 2:
                occ = "occupied"
                zt = 72.0
            elif case == "fault":
                zt = 74.0
            lines.append(f"{fmt(t)},{zt},{occ}")
        if case == "data_gap":
            lines = lines[:8] + lines[16:]
        if case == "duplicate_timestamp":
            lines[5] = lines[4]
        if case == "out_of_order":
            lines[3], lines[10] = lines[10], lines[3]
        if case == "irregular_sampling":
            times_i = ts_rows(24, step_s=180)
            lines = [f"{fmt(t)},74.0,unoccupied" for t in times_i]
        any_fault = case in {"fault", "irregular_sampling", "duplicate_timestamp", "out_of_order", "startup_delay"}
        write_case("VAV-2", case, header, lines, base_expected("VAV-2", any_fault), cols)


def vav6() -> None:
    cols = "col,point_role\noa_t,outside-air-temp\nreheat_valve_pct,reheat-valve\nclg_available,cooling-available\n"
    header = "timestamp_utc,oa_t,reheat_valve_pct,clg_available"
    for case in CASES:
        times = ts_rows(24)
        if case == "missing_required_role":
            write_case(
                "VAV-6",
                case,
                "timestamp_utc,reheat_valve_pct,clg_available",
                [f"{fmt(t)},0.5,1" for t in times],
                base_expected("VAV-6", False, missing=True),
                "col,point_role\nreheat_valve_pct,reheat-valve\nclg_available,cooling-available\n",
            )
            continue
        lines = []
        for i, t in enumerate(times):
            oa, rh, clg = 55.0, 0.10, 1
            if case == "fault":
                rh = 0.50
            elif case == "threshold_boundary":
                rh = 0.25
            elif case == "equipment_off":
                clg = 0
                rh = 0.50
            elif case == "startup_delay" and i < 2:
                rh = 0.10
            elif case == "normal":
                oa, rh = 75.0, 0.50
            lines.append(f"{fmt(t)},{oa},{rh},{clg}")
        if case == "data_gap":
            lines = lines[:8] + lines[16:]
        if case == "duplicate_timestamp":
            lines[5] = lines[4]
        if case == "out_of_order":
            lines[3], lines[10] = lines[10], lines[3]
        if case == "irregular_sampling":
            times_i = ts_rows(24, step_s=180)
            lines = [f"{fmt(t)},55.0,0.50,1" for t in times_i]
        any_fault = case in {"fault", "irregular_sampling", "duplicate_timestamp", "out_of_order", "startup_delay"}
        write_case("VAV-6", case, header, lines, base_expected("VAV-6", any_fault), cols)


def reset1() -> None:
    cols = "col,point_role\nsat_sp,discharge-air-temp-sp\noa_t,outside-air-temp\nfan_status,fan-status\n"
    header = "timestamp_utc,sat_sp,oa_t,fan_status"
    # expected at OAT 65 = 52. At OAT 40, expected = 52 + 0.25*(40-65) = 45.75
    for case in CASES:
        times = ts_rows(24)
        if case == "missing_required_role":
            write_case(
                "RESET-1",
                case,
                "timestamp_utc,oa_t,fan_status",
                [f"{fmt(t)},40,1" for t in times],
                base_expected("RESET-1", False, missing=True),
                "col,point_role\noa_t,outside-air-temp\nfan_status,fan-status\n",
            )
            continue
        lines = []
        for i, t in enumerate(times):
            oat, fan = 40.0, 1
            sat_sp = 45.75  # on curve
            if case == "fault":
                sat_sp = 60.0
            elif case == "threshold_boundary":
                sat_sp = 45.75 + 3.0  # exactly err, predicate is >
            elif case == "equipment_off":
                fan = 0
                sat_sp = 60.0
            elif case == "startup_delay" and i < 2:
                sat_sp = 45.75
            elif case == "normal":
                sat_sp = 45.75
            lines.append(f"{fmt(t)},{sat_sp},{oat},{fan}")
        if case == "data_gap":
            lines = lines[:8] + lines[16:]
        if case == "duplicate_timestamp":
            lines[5] = lines[4]
        if case == "out_of_order":
            lines[3], lines[10] = lines[10], lines[3]
        if case == "irregular_sampling":
            times_i = ts_rows(24, step_s=180)
            lines = [f"{fmt(t)},60.0,40.0,1" for t in times_i]
        any_fault = case in {"fault", "irregular_sampling", "duplicate_timestamp", "out_of_order", "startup_delay"}
        write_case("RESET-1", case, header, lines, base_expected("RESET-1", any_fault), cols)


def main() -> None:
    vav2()
    vav6()
    reset1()
    print("OK materialized VAV-2 VAV-6 RESET-1 oracle fixtures")


if __name__ == "__main__":
    main()
