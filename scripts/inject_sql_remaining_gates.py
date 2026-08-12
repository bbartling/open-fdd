#!/usr/bin/env python3
"""Inject remaining operational gates into screening SQL (idempotent)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "sql_rules"

ENERGIZED = (
    "    CASE\n"
    "      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END\n"
    "      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END\n"
    "      ELSE 1\n"
    "    END AS energized"
)

HYDRONIC = (
    "    CASE\n"
    "      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END\n"
    "      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END\n"
    "      ELSE 0\n"
    "    END AS proof_on"
)

FAN_ON = (
    "    CASE\n"
    "      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END\n"
    "      ELSE 1\n"
    "    END AS fan_on"
)

COMPRESSOR = (
    "    CASE\n"
    "      WHEN compressor_status IS NOT NULL THEN CASE WHEN compressor_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END\n"
    "      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.05 THEN 1 ELSE 0 END\n"
    "      ELSE 1\n"
    "    END AS proof_on"
)

SV_TARGETS = ["sv_flatline.sql", "sv_range.sql", "sv_spike.sql"]
HYDRONIC_TARGETS = [
    "cw_opt_1.sql",
    "cw_apr_1.sql",
    "cw_fan_1.sql",
    "trim3_hwst.sql",
    "trim4_chw_reset.sql",
]
FAN_TARGETS = [
    "vav3_excessive_reheat.sql",
    "vav4_damper_full_open.sql",
    "vav5_airflow_bias.sql",
    "vav_reheat.sql",
    "vav_ahu_leave.sql",
    "vav7_min_airflow.sql",
    "pid_hunt_1.sql",
]
HP_TARGETS = ["hp1_discharge_cold.sql"]


def _insert_expr(text: str, expr: str, already: str, extra_cols: list[str], gate: str) -> str:
    if already in text:
        return text
    marker = "  FROM history"
    idx = text.find(marker)
    if idx < 0:
        return text
    select = text[:idx]
    extra = ""
    for col in extra_cols:
        if col not in select:
            extra += f"    {col},\n"
    extra += expr + "\n"
    insert_at = select.rfind("\n")
    if not select.rstrip().endswith(","):
        select = select[:insert_at] + ",\n" + extra + select[insert_at:]
    else:
        select = select[:insert_at] + extra + select[insert_at:]
    rest = text[idx:]
    rest2 = rest.replace(
        "CAST(CASE\n",
        f"CAST(CASE\n      WHEN COALESCE({gate}, 0) = 0 THEN 0\n",
        1,
    )
    return select + rest2


def main() -> None:
    changed = []
    for name in SV_TARGETS:
        path = ROOT / name
        new = _insert_expr(
            path.read_text(),
            ENERGIZED,
            "AS energized",
            ["fan_cmd", "fan_status", "pump_status", "chw_pump_cmd", "chiller_status"],
            "energized",
        )
        if new != path.read_text():
            path.write_text(new)
            changed.append(name)
    for name in HYDRONIC_TARGETS:
        path = ROOT / name
        new = _insert_expr(
            path.read_text(),
            HYDRONIC,
            "AS proof_on",
            ["pump_status", "chiller_status", "chw_flow", "chw_pump_cmd"],
            "proof_on",
        )
        if new != path.read_text():
            path.write_text(new)
            changed.append(name)
    for name in FAN_TARGETS:
        path = ROOT / name
        new = _insert_expr(
            path.read_text(),
            FAN_ON,
            "AS fan_on",
            ["fan_cmd", "fan_status"],
            "fan_on",
        )
        if new != path.read_text():
            path.write_text(new)
            changed.append(name)
    for name in HP_TARGETS:
        path = ROOT / name
        new = _insert_expr(
            path.read_text(),
            COMPRESSOR,
            "AS proof_on",
            ["compressor_status", "fan_status", "fan_cmd"],
            "proof_on",
        )
        if new != path.read_text():
            path.write_text(new)
            changed.append(name)
    print("patched", len(changed), "files")
    for n in changed:
        print(" ", n)


if __name__ == "__main__":
    main()
