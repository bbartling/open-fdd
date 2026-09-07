#!/usr/bin/env python3
"""Wave G Lab tuner parity — registry + FC/SV SQL SQL-honest Vibe19 keys."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path("sql_rules")
REG = ROOT / "registry.yaml"


def slider(
    key: str,
    label: str,
    default: float,
    mn: float,
    mx: float,
    step: float,
    unit: str,
    ph: str,
) -> str:
    return (
        f"      {key}:\n"
        f"        label: {label}\n"
        f"        default: {default}\n"
        f"        min: {mn}\n"
        f"        max: {mx}\n"
        f"        step: {step}\n"
        f"        unit: {unit}\n"
        f"        frontend_control: slider\n"
        f"        sql_placeholder: {ph}\n"
    )


P = {
    "eps_mat": slider("eps_mat", "MAT sensor eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_MAT"),
    "eps_oat": slider("eps_oat", "OAT sensor eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_OAT"),
    "eps_rat": slider("eps_rat", "RAT sensor eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_RAT"),
    "eps_sat": slider("eps_sat", "SAT sensor eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_SAT"),
    "fan_on_min": slider("fan_on_min", "Fan-on command min", 0.01, 0.0, 1.0, 0.01, "frac", "FAN_ON_MIN"),
    "mode_delay_min": slider(
        "mode_delay_min", "Mode delay after fan-on", 10.0, 0.0, 60.0, 1.0, "min", "MODE_DELAY_MIN"
    ),
    "econ_full_open": slider(
        "econ_full_open", "Econ damper full-open", 0.9, 0.5, 1.0, 0.05, "frac", "ECON_FULL_OPEN"
    ),
    "supply_tol": slider(
        "supply_tol", "Supply tol (alias eps_sat)", 1.15, 0.0, 10.0, 0.25, "degF", "SUPPLY_TOL"
    ),
    "clg_full_min": slider(
        "clg_full_min", "Cooling valve full min", 0.9, 0.5, 1.0, 0.05, "frac", "CLG_FULL_MIN"
    ),
    "eps_airflow": slider(
        "eps_airflow", "Airflow fraction eps", 0.15, 0.05, 1.0, 0.01, "frac", "EPS_AIRFLOW"
    ),
    "oat_rat_delta_min": slider(
        "oat_rat_delta_min", "Min |OAT-RAT|", 5.0, 0.0, 30.0, 0.5, "degF", "OAT_RAT_DELTA_MIN"
    ),
    "eps_ccet": slider("eps_ccet", "CHW coil entering eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_CCET"),
    "eps_cclt": slider("eps_cclt", "CHW coil leaving eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_CCLT"),
    "eps_hcet": slider("eps_hcet", "HW coil entering eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_HCET"),
    "eps_hclt": slider("eps_hclt", "HW coil leaving eps", 1.15, 0.0, 10.0, 0.25, "degF", "EPS_HCLT"),
    "delta_supply_fan": slider(
        "delta_supply_fan", "Supply-fan delta", 0.55, 0.0, 5.0, 0.05, "degF", "DELTA_SUPPLY_FAN"
    ),
    "clg_inactive_max": slider(
        "clg_inactive_max", "Cooling inactive max", 0.01, 0.0, 0.5, 0.01, "frac", "CLG_INACTIVE_MAX"
    ),
    "htg_on_min": slider("htg_on_min", "Heating on min", 0.01, 0.0, 1.0, 0.01, "frac", "HTG_ON_MIN"),
    "clg_on_min": slider("clg_on_min", "Cooling on min", 0.01, 0.0, 1.0, 0.01, "frac", "CLG_ON_MIN"),
    "econ_min_pos": slider(
        "econ_min_pos", "Econ damper min pos", 0.05, 0.0, 0.5, 0.01, "frac", "ECON_MIN_POS"
    ),
    "require_operational_gate": slider(
        "require_operational_gate",
        "Require operational gate",
        1.0,
        0.0,
        1.0,
        1.0,
        "bool",
        "REQUIRE_OPERATIONAL_GATE",
    ),
    "startup_delay_min": slider(
        "startup_delay_min", "Startup delay", 0.0, 0.0, 60.0, 1.0, "min", "STARTUP_DELAY_MIN"
    ),
    "minimum_active_coverage_pct": slider(
        "minimum_active_coverage_pct",
        "Min active coverage",
        5.0,
        0.0,
        100.0,
        1.0,
        "pct",
        "MINIMUM_ACTIVE_COVERAGE_PCT",
    ),
    "spike_scale_temperature": slider(
        "spike_scale_temperature",
        "Spike scale temperature",
        1.0,
        0.25,
        4.0,
        0.25,
        "x",
        "SPIKE_SCALE_TEMPERATURE",
    ),
    "spike_scale_humidity": slider(
        "spike_scale_humidity",
        "Spike scale humidity",
        1.0,
        0.25,
        4.0,
        0.25,
        "x",
        "SPIKE_SCALE_HUMIDITY",
    ),
    "spike_scale_pressure": slider(
        "spike_scale_pressure",
        "Spike scale pressure",
        1.0,
        0.25,
        4.0,
        0.25,
        "x",
        "SPIKE_SCALE_PRESSURE",
    ),
    "design_flow": slider("design_flow", "Design flow", 1000.0, 100.0, 20000.0, 50.0, "cfm", "DESIGN_FLOW"),
    "max_gap_hours": slider("max_gap_hours", "Max sample gap", 1.0, 0.1, 12.0, 0.1, "h", "MAX_GAP_HOURS"),
    "sensor_span": slider("sensor_span", "Sensor span", 100.0, 1.0, 500.0, 1.0, "unit", "SENSOR_SPAN"),
}

RULE_ADDS = {
    "FC1": ["mode_delay_min", "fan_on_min"],
    "FC2": ["eps_mat", "eps_oat", "eps_rat", "fan_on_min", "mode_delay_min"],
    "FC3": ["eps_mat", "eps_oat", "eps_rat", "mode_delay_min"],
    "FC4": ["mode_delay_min", "fan_on_min"],
    "FC5": ["eps_mat", "eps_sat", "fan_on_min", "mode_delay_min"],
    "FC6": ["eps_airflow", "fan_on_min", "mode_delay_min", "oat_rat_delta_min"],
    "FC7": ["eps_sat", "fan_on_min", "mode_delay_min"],
    "FC8": ["eps_mat", "eps_sat", "supply_tol", "mode_delay_min", "fan_on_min"],
    "FC9": ["eps_oat", "eps_sat", "mode_delay_min", "fan_on_min"],
    "FC10": ["econ_full_open", "eps_mat", "eps_oat", "mode_delay_min", "fan_on_min"],
    "FC11": ["econ_full_open", "eps_oat", "eps_sat", "mode_delay_min", "fan_on_min"],
    "FC12": ["econ_full_open", "eps_mat", "eps_sat", "supply_tol", "mode_delay_min", "fan_on_min"],
    "FC13-SAT-HIGH": [
        "clg_full_min",
        "econ_full_open",
        "econ_min_pos",
        "eps_sat",
        "mode_delay_min",
        "fan_on_min",
    ],
    "FC14": [
        "clg_inactive_max",
        "delta_supply_fan",
        "econ_min_pos",
        "eps_ccet",
        "eps_cclt",
        "htg_on_min",
        "mode_delay_min",
        "fan_on_min",
    ],
    "FC15": [
        "clg_inactive_max",
        "clg_on_min",
        "delta_supply_fan",
        "econ_full_open",
        "econ_min_pos",
        "eps_hcet",
        "eps_hclt",
        "mode_delay_min",
        "fan_on_min",
    ],
    "SV-SPIKE": ["spike_scale_temperature", "spike_scale_humidity", "spike_scale_pressure"],
    "SV-RATE": ["design_flow", "max_gap_hours", "sensor_span"],
}

GATE_RULES = [
    "SV-RANGE",
    "SV-FLATLINE",
    "SV-SPIKE",
    "FC1",
    "FC2",
    "FC3",
    "FC4",
    "FC5",
    "FC6",
    "FC7",
    "FC8",
    "FC9",
    "FC10",
    "FC11",
    "FC12",
    "FC13-SAT-HIGH",
    "FC14",
    "FC15",
    "AHU-SATDEV",
    "AHU-DUCTHI",
    "AHU-SIMUL",
    "ECON-1",
    "ECON-2",
    "ECON-3",
    "ECON-4",
    "ECON-5",
    "ECON-6",
    "ECON-7",
    "VAV-1",
    "VAV-2",
    "VAV-3",
    "VAV-4",
    "VAV-5",
    "VAV-6",
    "VAV-7",
    "VAV-REHEAT",
    "CHW-1",
    "CHW-2",
    "CHW-3",
    "CHW-4",
    "CHW-NOLOAD-1",
    "HP-1",
    "CW-OPT-1",
    "CW-APR-1",
    "CW-FAN-1",
    "TRIM-1",
    "TRIM-3",
    "TRIM-4",
    "RESET-1",
    "OA-1",
    "DMP-1",
    "VLV-1",
    "PID-HUNT-1",
]
GATE_KEYS = [
    "require_operational_gate",
    "startup_delay_min",
    "minimum_active_coverage_pct",
]


def inject_params(block: str, keys: list[str]) -> str:
    if "parameters:" not in block:
        block = block.rstrip() + "\n    parameters:\n"
        for k in keys:
            if k in P:
                block += P[k]
        if not block.endswith("\n"):
            block += "\n"
        return block
    for k in keys:
        if re.search(rf"^\s+{k}:", block, re.M):
            continue
        if k not in P:
            continue
        block = re.sub(r"(    parameters:\n)", r"\1" + P[k], block, count=1)
    return block


def patch_registry() -> None:
    text = REG.read_text()
    parts = re.split(r"(?=^  - rule_id: )", text, flags=re.M)
    new_parts: list[str] = []
    for i, part in enumerate(parts):
        if i == 0 and not part.lstrip().startswith("- rule_id"):
            new_parts.append(part)
            continue
        rid_m = re.search(r"rule_id:\s*(\S+)", part)
        if not rid_m:
            new_parts.append(part)
            continue
        rid = rid_m.group(1)
        keys: list[str] = list(RULE_ADDS.get(rid, []))
        if rid in GATE_RULES:
            for g in GATE_KEYS:
                if g not in keys:
                    keys.append(g)
        if keys:
            part = inject_params(part, keys)
        new_parts.append(part)
    REG.write_text("".join(new_parts))
    print("registry updated")


FAN_ON_REPL = """    CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on"""


def patch_fan_on_block(sql: str) -> str:
    pat = re.compile(
        r"CASE\s*\n\s*WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0\.05 THEN 1 ELSE 0 END\s*\n"
        r"\s*WHEN fan_cmd IS NOT NULL THEN CASE WHEN \(CASE WHEN fan_cmd > 1\.0 THEN fan_cmd / 100\.0 ELSE fan_cmd END\) > 0\.01 THEN 1 ELSE 0 END\s*\n"
        r"\s*ELSE 1\s*\n\s*END AS fan_on",
        re.M,
    )
    sql = pat.sub(FAN_ON_REPL, sql)
    sql = sql.replace(
        "WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END",
        "WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END",
    )
    return sql


def add_mode_stable(sql: str) -> str:
    if "{{MODE_DELAY_ROWS_PRECEDING}}" in sql:
        return sql
    if "AS fan_on" not in sql or "raw_fault" not in sql:
        return sql
    needle = "FROM h\n),"
    if needle not in sql:
        return sql
    wrap = """FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),"""
    sql = sql.replace(needle, wrap, 1)
    if "WHEN COALESCE(fan_on, 1) = 0 THEN 0" in sql and "mode_stable" in sql:
        sql = sql.replace(
            "WHEN COALESCE(fan_on, 1) = 0 THEN 0",
            "WHEN COALESCE(fan_on, 1) = 0 THEN 0\n      WHEN COALESCE(mode_stable, 1) = 0 THEN 0",
            1,
        )
    return sql


def patch_fc2() -> None:
    p = ROOT / "fc2_mat_low.sql"
    s = patch_fan_on_block(p.read_text())
    s = s.replace(
        "AND (mat + {{MIX_TOL}}) < (CASE WHEN rat < oa_t THEN rat ELSE oa_t END) - {{MIX_TOL}}",
        "AND (mat + {{EPS_MAT}}) < (CASE WHEN rat < oa_t THEN rat - {{EPS_RAT}} ELSE oa_t - {{EPS_OAT}} END)",
    )
    s = add_mode_stable(s)
    p.write_text(s)
    print("fc2")


def patch_fc3() -> None:
    p = ROOT / "fc3_mat_high.sql"
    s = patch_fan_on_block(p.read_text())
    s = s.replace(
        "AND (mat - {{MIX_TOL}}) > (CASE WHEN rat > oa_t THEN rat ELSE oa_t END) + {{MIX_TOL}}",
        "AND (mat - {{EPS_MAT}}) > (CASE WHEN rat > oa_t THEN rat + {{EPS_RAT}} ELSE oa_t + {{EPS_OAT}} END)",
    )
    s = add_mode_stable(s)
    p.write_text(s)
    print("fc3")


def patch_sqrt_mix(fname: str) -> None:
    p = ROOT / fname
    if not p.exists():
        return
    s = patch_fan_on_block(p.read_text())
    old = "SQRT(2.0 * {{MIX_TOL}} * {{MIX_TOL}})"
    new = "SQRT({{EPS_SAT}} * {{EPS_SAT}} + {{EPS_MAT}} * {{EPS_MAT}})"
    s = s.replace(old, new)
    # OA_DAMPER_ECON_HIGH -> prefer ECON_FULL_OPEN where used as full open
    s = s.replace("{{OA_DAMPER_ECON_HIGH}}", "{{ECON_FULL_OPEN}}")
    s = add_mode_stable(s)
    p.write_text(s)
    print(fname)


def patch_generic_fc(fname: str, replacements: list[tuple[str, str]]) -> None:
    p = ROOT / fname
    if not p.exists():
        return
    s = patch_fan_on_block(p.read_text())
    for a, b in replacements:
        s = s.replace(a, b)
    s = add_mode_stable(s)
    p.write_text(s)
    print(fname)


def patch_sv_spike() -> None:
    p = ROOT / "sv_spike.sql"
    s = p.read_text()
    # temperatures use SPIKE_SCALE_TEMPERATURE; humidity SPIKE_SCALE_HUMIDITY; duct SPIKE_SCALE_PRESSURE
    temp_roles = [
        "oa_t",
        "mat",
        "zone_t",
        "rat",
        "sat",
        "chw_supply_t",
        "chw_return_t",
        "hw_supply_t",
        "hw_return_t",
    ]
    for role in temp_roles:
        s = s.replace(
            f"* {{{{SPIKE_SCALE}}}} THEN 1\n      WHEN {role}" if False else "",
            "",
        )
    # simpler: replace all SPIKE_SCALE then fix humidity/pressure lines
    s = s.replace("{{SPIKE_SCALE}}", "{{SPIKE_SCALE_TEMPERATURE}}")
    s = s.replace(
        "ABS(oa_h - prev_oa_h) > 25.0 * {{SPIKE_SCALE_TEMPERATURE}}",
        "ABS(oa_h - prev_oa_h) > 25.0 * {{SPIKE_SCALE_HUMIDITY}}",
    )
    s = s.replace(
        "ABS(duct_static - prev_duct_static) > 2.0 * {{SPIKE_SCALE_TEMPERATURE}}",
        "ABS(duct_static - prev_duct_static) > 2.0 * {{SPIKE_SCALE_PRESSURE}}",
    )
    # operational gate on energized
    s = s.replace(
        "WHEN COALESCE(energized, 0) = 0 THEN 0",
        "WHEN {{REQUIRE_OPERATIONAL_GATE}} >= 0.5 AND COALESCE(energized, 0) = 0 THEN 0",
    )
    p.write_text(s)
    print("sv_spike")


def patch_remaining_fan_files() -> None:
    for fname in [
        "fc1_duct_static_low.sql",
        "fc4_os_hunting.sql",
        "fc5_sat_cold_heating.sql",
        "fc6_oa_frac_mismatch.sql",
        "fc7_sat_low_heating.sql",
        "fc9_oa_sat_sp_econ.sql",
        "fc10_mat_oa_clg.sql",
        "fc11_oa_sat_sp_clg.sql",
        "fc14_chw_coil_dt_inactive.sql",
        "fc15_hw_coil_dt_inactive.sql",
        "sat_high_fault.sql",
    ]:
        p = ROOT / fname
        if not p.exists():
            continue
        s = patch_fan_on_block(p.read_text())
        if "MIX_TOL" in s and "EPS_MAT" not in s:
            # leave MIX_TOL but also allow EPS via runner defaults; for FC5 etc replace SAT uses
            s = s.replace("{{MIX_TOL}}", "{{EPS_MAT}}")
        if "SAT_ERR" in s:
            s = s.replace("{{SAT_ERR}}", "{{EPS_SAT}}")
        if "AIRFLOW_ERR" in s:
            s = s.replace("{{AIRFLOW_ERR}}", "{{EPS_AIRFLOW}}")
        if "DELTA_T_MIN" in s:
            s = s.replace("{{DELTA_T_MIN}}", "{{OAT_RAT_DELTA_MIN}}")
        s = s.replace("{{OA_DAMPER_ECON_HIGH}}", "{{ECON_FULL_OPEN}}")
        s = s.replace("fan > 0.01", "fan > {{FAN_ON_MIN}}")
        s = s.replace("fan < 0.05", "fan < {{FAN_ON_MIN}}")
        s = s.replace("fan >= 0.05", "fan >= {{FAN_ON_MIN}}")
        s = s.replace("+ 0.55", "+ {{DELTA_SUPPLY_FAN}}")
        s = s.replace("clg > 0.01", "clg > {{CLG_ON_MIN}}")
        s = s.replace("clg < 0.01", "clg < {{CLG_INACTIVE_MAX}}")
        s = s.replace("htg > 0.01", "htg > {{HTG_ON_MIN}}")
        s = add_mode_stable(s)
        p.write_text(s)
        print(fname)


def main() -> None:
    patch_registry()
    patch_fc2()
    patch_fc3()
    patch_sqrt_mix("fc8_sat_mat_econ.sql")
    patch_sqrt_mix("fc12_sat_mat_clg.sql")
    patch_remaining_fan_files()
    patch_sv_spike()
    print("OK")


if __name__ == "__main__":
    main()
