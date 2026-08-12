#!/usr/bin/env python3
"""Inject ranked fan_status > fan_cmd proof into screening SQL files.

Idempotent: skips files that already define fan_on.
Does not use a DataFusion UDF — copies the CHW-1 / SCHED-247 CTE pattern.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "sql_rules"

FAN_ON = (
    "    CASE\n"
    "      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END\n"
    "      ELSE 1\n"
    "    END AS fan_on"
)

TARGETS = [
    "ahu_satdev.sql",
    "ahu_simul.sql",
    "ahu_ducthi.sql",
    "economizer_fault.sql",
    "econ1_stuck_closed.sql",
    "econ3_mech_without_econ.sql",
    "econ4_low_oa_frac.sql",
    "econ5_preheat_over.sql",
    "econ6_econ_freezing.sql",
    "econ7_ok_not_economizing.sql",
    "fc1_duct_static_low.sql",
    "fc2_mat_low.sql",
    "fc3_mat_high.sql",
    "fc5_sat_cold_heating.sql",
    "fc6_oa_frac_mismatch.sql",
    "fc8_sat_mat_econ.sql",
    "fc9_oa_sat_sp_econ.sql",
    "fc10_mat_oa_clg.sql",
    "fc11_oa_sat_sp_clg.sql",
    "fc12_sat_mat_clg.sql",
    "sat_high_fault.sql",
    "fc14_chw_coil_dt_inactive.sql",
    "fc15_hw_coil_dt_inactive.sql",
    "oa1_low_oa_frac.sql",
    "dmp1_oa_damper_leak.sql",
    "vlv1_clg_valve_leak.sql",
    "trim1_duct_static.sql",
]


def inject(text: str) -> str:
    if "AS fan_on" in text or " as fan_on" in text:
        return text
    # Add fan_on into the first SELECT ... FROM history block.
    marker = "  FROM history"
    idx = text.find(marker)
    if idx < 0:
        marker = "\nFROM history"
        idx = text.find(marker)
    if idx < 0:
        return text
    select = text[:idx]
    # Ensure fan_status/fan_cmd are selected if missing
    head = select
    if "fan_status" not in head.split("FROM")[0] and "fan_cmd" not in head.split("FROM")[0]:
        # insert before last comma-less line of the select list
        insert_at = select.rfind("\n")
        extra = ""
        if "fan_cmd" not in select:
            extra += "    fan_cmd,\n"
        if "fan_status" not in select:
            extra += "    fan_status,\n"
        extra += FAN_ON + "\n"
        select = select[:insert_at] + ",\n" + extra + select[insert_at:]
    else:
        insert_at = select.rfind("\n")
        select = select[:insert_at] + ",\n" + FAN_ON + "\n" + select[insert_at:]
    rest = text[idx:]
    # Gate raw_fault
    rest2 = rest.replace(
        "CAST(CASE\n",
        "CAST(CASE\n      WHEN COALESCE(fan_on, 1) = 0 THEN 0\n",
        1,
    )
    if rest2 == rest:
        rest2 = rest.replace(
            "CAST(CASE\r\n",
            "CAST(CASE\r\n      WHEN COALESCE(fan_on, 1) = 0 THEN 0\r\n",
            1,
        )
    return select + rest2


def main() -> None:
    changed = []
    for name in TARGETS:
        path = ROOT / name
        if not path.is_file():
            print("missing", name)
            continue
        old = path.read_text()
        new = inject(old)
        if new != old:
            path.write_text(new)
            changed.append(name)
        else:
            print("unchanged", name)
    print("patched", len(changed), "files")
    for n in changed:
        print(" ", n)


if __name__ == "__main__":
    main()
