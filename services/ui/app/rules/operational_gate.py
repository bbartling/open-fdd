"""Equipment-specific operational gates for the 50-rule pandas cookbook.

Do not use one universal motor filter. Prefer status/proof roles over command.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from app.rules.cookbook_catalog import as_bool, norm_cmd

GateKind = Literal[
    "always",
    "fan_running",
    "hydronic_flow",
    "compressor",
    "conditional",
    "control_loop",
    "equipment_energized",  # fan proof, else plant pump, else compressor
]


@dataclass(frozen=True)
class GateSpec:
    kind: GateKind
    startup_delay_seconds: float = 0.0
    # Default 5%: skip only when essentially off. Raise via UI to require more coverage.
    minimum_active_coverage_pct: float = 5.0
    command_fallback_allowed: bool = True


# Registry: every canonical rule id → gate (PID-HUNT-1 replaced SV-4).
# Mechanical FDD: fan_running (air) or hydronic_flow (plant). Sensor sweeps use
# equipment_energized (fan → pump → compressor). Exceptions that must see off
# samples: SCHED-1 (unoccupied fan runtime), CMD-1 (cmd/status mismatch),
# OAT-METEO / WX-1 (weather, not equipment-energized faults).
RULE_GATES: dict[str, GateSpec] = {
    "SV-RANGE": GateSpec("equipment_energized", startup_delay_seconds=0),
    "SV-FLATLINE": GateSpec("conditional", startup_delay_seconds=0),
    "SV-SPIKE": GateSpec("equipment_energized", startup_delay_seconds=0),
    "SV-STALE": GateSpec("always"),  # dead feed must be visible even when motors are off
    "SV-RATE": GateSpec("always"),  # state is classified inside the rule; need off/transient samples
    "PID-HUNT-1": GateSpec("control_loop", startup_delay_seconds=300),
    "FC1": GateSpec("fan_running", startup_delay_seconds=300),
    "FC2": GateSpec("fan_running", startup_delay_seconds=600),
    "FC3": GateSpec("fan_running", startup_delay_seconds=600),
    "FC4": GateSpec("control_loop", startup_delay_seconds=300),
    "FC5": GateSpec("fan_running", startup_delay_seconds=600),
    "FC6": GateSpec("fan_running", startup_delay_seconds=600),
    "FC7": GateSpec("fan_running", startup_delay_seconds=600),
    "FC8": GateSpec("fan_running", startup_delay_seconds=600),
    "FC9": GateSpec("fan_running", startup_delay_seconds=600),
    "FC10": GateSpec("fan_running", startup_delay_seconds=600),
    "FC11": GateSpec("fan_running", startup_delay_seconds=600),
    "FC12": GateSpec("fan_running", startup_delay_seconds=600),
    "FC13": GateSpec("fan_running", startup_delay_seconds=600),
    "FC14": GateSpec("fan_running", startup_delay_seconds=600),
    "FC15": GateSpec("fan_running", startup_delay_seconds=600),
    "AHU-SATDEV": GateSpec("fan_running", startup_delay_seconds=600),
    "AHU-DUCTHI": GateSpec("conditional", startup_delay_seconds=0),
    "AHU-SIMUL": GateSpec("fan_running", startup_delay_seconds=300),
    "OAT-METEO": GateSpec("always"),
    "ECON-1": GateSpec("fan_running", startup_delay_seconds=600),
    "ECON-2": GateSpec("fan_running", startup_delay_seconds=300),
    "ECON-3": GateSpec("fan_running", startup_delay_seconds=600),
    "ECON-4": GateSpec("fan_running", startup_delay_seconds=600),
    "ECON-5": GateSpec("fan_running", startup_delay_seconds=600),
    "ECON-6": GateSpec("fan_running", startup_delay_seconds=600),
    "ECON-7": GateSpec("fan_running", startup_delay_seconds=600),
    "MECH-OAT-1": GateSpec("always"),  # needs cold-weather samples even if proof drops
    "CHW-NOLOAD-1": GateSpec("always"),  # confirmation delay is 30 min; do not pre-filter offs
    "VAV-1": GateSpec("conditional"),
    "VAV-3": GateSpec("fan_running", startup_delay_seconds=300),
    "VAV-4": GateSpec("control_loop", startup_delay_seconds=300),
    "VAV-5": GateSpec("fan_running", startup_delay_seconds=300),
    "VAV-REHEAT": GateSpec("fan_running", startup_delay_seconds=600),
    "VAV-AHU-LEAVE": GateSpec("fan_running", startup_delay_seconds=600),
    "VAV-7": GateSpec("fan_running", startup_delay_seconds=300),
    "CHW-1": GateSpec("hydronic_flow", startup_delay_seconds=900),
    "CHW-2": GateSpec("hydronic_flow", startup_delay_seconds=300),
    "CHW-3": GateSpec("hydronic_flow", startup_delay_seconds=600),
    "CHW-4": GateSpec("hydronic_flow", startup_delay_seconds=300),
    "HP-1": GateSpec("compressor", startup_delay_seconds=600),
    "WX-1": GateSpec("always"),
    "CW-OPT-1": GateSpec("hydronic_flow", startup_delay_seconds=600),
    "CW-APR-1": GateSpec("hydronic_flow", startup_delay_seconds=600),
    "CW-FAN-1": GateSpec("hydronic_flow", startup_delay_seconds=600),
    "TRIM-1": GateSpec("fan_running", startup_delay_seconds=300),
    "TRIM-3": GateSpec("hydronic_flow", startup_delay_seconds=600),
    "TRIM-4": GateSpec("hydronic_flow", startup_delay_seconds=600),
    "SCHED-1": GateSpec("always"),
    "SCHED-247": GateSpec("always"),  # always-on detection must see the full window
    "CMD-1": GateSpec("always"),
    "OA-1": GateSpec("fan_running", startup_delay_seconds=600),
    "DMP-1": GateSpec("conditional", startup_delay_seconds=300),
    "VLV-1": GateSpec("conditional", startup_delay_seconds=300),
}


FAN_PROOF_ROLES = (
    "fan-status",
    "fan-speed-feedback",
    "fan-current",
    "fan-power",
    "airflow-proof",
)
FAN_CMD_FALLBACK = ("fan-cmd",)

PUMP_PROOF_ROLES = (
    "pump-status",
    "chw-pump-status",
    "hw-pump-status",
    "chw-pump-cmd",  # often used as status-like cmd in this demo
    "pump-speed-feedback",
    "pump-current",
    "chw-flow",
    "water-flow",
)
PUMP_CMD_FALLBACK = ("pump-cmd", "chw-pump-cmd", "hw-pump-cmd")

COMPRESSOR_ROLES = ("compressor-status", "equipment-enable", "fan-status", "fan-cmd")


def _series_on(series: pd.Series, *, threshold: float = 0.05) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce")
    if num.notna().any():
        scaled = num.where(num <= 1.5, num / 100.0)
        return scaled.fillna(0) > threshold
    return as_bool(series)


def _first_present_on(
    df: pd.DataFrame,
    roles: tuple[str, ...],
    *,
    threshold: float = 0.05,
) -> tuple[pd.Series | None, str | None]:
    for role in roles:
        if role in df.columns and df[role].notna().any():
            return _series_on(df[role], threshold=threshold), role
    return None, None


def resolve_fan_running(df: pd.DataFrame, *, command_fallback: bool = True) -> tuple[pd.Series, str]:
    """Prefer proof/status over command. Returns (mask, source_role_or_note)."""
    mask, role = _first_present_on(df, FAN_PROOF_ROLES)
    if mask is not None and role is not None:
        return mask.fillna(False), role
    if command_fallback:
        mask, role = _first_present_on(df, FAN_CMD_FALLBACK)
        if mask is not None and role is not None:
            return mask.fillna(False), f"{role} (cmd fallback)"
    # VAV airflow proxy
    if "zone-airflow" in df.columns and df["zone-airflow"].notna().any():
        flow = pd.to_numeric(df["zone-airflow"], errors="coerce").fillna(0)
        return (flow > 50.0), "zone-airflow"
    return pd.Series(True, index=df.index), "ungated_no_proof_roles"


def resolve_hydronic_running(df: pd.DataFrame, *, command_fallback: bool = True) -> tuple[pd.Series, str]:
    mask, role = _first_present_on(df, PUMP_PROOF_ROLES, threshold=0.05)
    if mask is not None and role is not None:
        # chw_pump_cmd in proof list — treat like speed/cmd
        return mask.fillna(False), role
    if command_fallback:
        mask, role = _first_present_on(df, PUMP_CMD_FALLBACK)
        if mask is not None and role is not None:
            return mask.fillna(False), f"{role} (cmd fallback)"
    return pd.Series(True, index=df.index), "ungated_no_proof_roles"


def resolve_compressor_running(df: pd.DataFrame, *, command_fallback: bool = True) -> tuple[pd.Series, str]:
    for role in COMPRESSOR_ROLES:
        if role in df.columns and df[role].notna().any():
            if role == "fan-cmd" and not command_fallback:
                continue
            return _series_on(df[role]).fillna(False), role
    return pd.Series(True, index=df.index), "ungated_no_proof_roles"


def resolve_equipment_energized(df: pd.DataFrame, *, command_fallback: bool = True) -> tuple[pd.Series, str]:
    """Prefer fan proof, else plant pump/hydronic, else compressor — for mixed-kind rules."""
    fan, src = resolve_fan_running(df, command_fallback=command_fallback)
    if not src.startswith("ungated"):
        return fan, src
    pump, src = resolve_hydronic_running(df, command_fallback=command_fallback)
    if not src.startswith("ungated"):
        return pump, src
    comp, src = resolve_compressor_running(df, command_fallback=command_fallback)
    if not src.startswith("ungated"):
        return comp, src
    return pd.Series(True, index=df.index), "ungated_no_proof_roles"


def resolve_conditional(
    df: pd.DataFrame,
    rule_id: str,
    params: dict | None = None,
) -> tuple[pd.Series, str]:
    """Point/context-aware gates for CONDITIONAL rules."""
    params = params or {}
    if rule_id == "VAV-1":
        # Occupied band when schedule exists; also require air moving when fan/flow proof exists.
        if "occupied" in df.columns and df["occupied"].notna().any():
            occ = df["occupied"].astype(str).str.lower().isin({"occupied", "1", "true", "on"})
            fan, src = resolve_fan_running(df)
            if src.startswith("ungated"):
                return occ.fillna(False), "occupied"
            return (occ & fan).fillna(False), f"occ_and_{src}"
        fan, src = resolve_fan_running(df)
        if src.startswith("ungated"):
            return pd.Series(True, index=df.index), "ungated_no_occ"
        return fan, src
    if rule_id == "DMP-1":
        fan, src = resolve_fan_running(df)
        if "outside-air-damper" in df.columns:
            cmd = norm_cmd(df["outside-air-damper"]).fillna(0) > 0.01
            return (fan | cmd).fillna(False), f"damper_or_{src}"
        return fan, src
    if rule_id == "VLV-1":
        # Leakage detection already requires a closed valve in the rule compute.
        # Gate only on fan proof — the old (valve>0.01)|(valve<=0.05) cover was a tautology.
        fan, src = resolve_fan_running(df)
        return fan, f"fan_{src}"
    if rule_id == "AHU-DUCTHI":
        # Evaluate when fan is proven on OR duct static itself shows live pressure.
        # This catches high static while fan-status falsely reports off.
        fan, src = resolve_fan_running(df)
        try:
            thr = float(params.get("pressure_on_min", 0.20) or 0.20)
        except (TypeError, ValueError):
            thr = 0.20
        if "duct-static-pressure" in df.columns and df["duct-static-pressure"].notna().any():
            press = pd.to_numeric(df["duct-static-pressure"], errors="coerce").fillna(0).abs() > thr
            if src.startswith("ungated"):
                return press.fillna(False), "duct_static_pressure"
            return (fan | press).fillna(False), f"fan_or_duct_static:{src}"
        return fan, src
    if rule_id == "SV-FLATLINE":
        # Prefer energized periods (fan → pump) to reduce off-period stuck false positives.
        return resolve_equipment_energized(df)
    return pd.Series(True, index=df.index), "conditional_default"


def apply_startup_delay(active: pd.Series, poll_seconds: float, delay_seconds: float) -> pd.Series:
    """Require continuous run for delay_seconds before samples count as active."""
    if delay_seconds <= 0:
        return active.fillna(False)
    rows = max(1, int(np.ceil(delay_seconds / max(poll_seconds, 1.0))))
    on = active.fillna(False).astype(bool)
    groups = (on != on.shift()).cumsum()
    streak = on.groupby(groups).cumcount() + 1
    return on & (streak >= rows)


def resolve_operational_mask(
    df: pd.DataFrame,
    rule_id: str,
    *,
    poll_seconds: float,
    params: dict | None = None,
    gate_enabled: bool = True,
) -> tuple[pd.Series, dict]:
    """
    Return (active_mask, meta).

    When gate_enabled is False or kind is always → all True.
    When no proof roles exist → ungated (all True) with meta note (cannot prove off).
    """
    params = params or {}
    spec = RULE_GATES.get(rule_id, GateSpec("always"))
    meta: dict = {
        "gate_kind": spec.kind,
        "gate_applied": False,
        "gate_source": "always",
        "active_sample_count": int(len(df)),
        "active_coverage_pct": 100.0,
    }

    require = bool(int(float(params.get("require_operational_gate", 1 if spec.kind != "always" else 0))))
    if not gate_enabled or spec.kind == "always" or not require:
        active = pd.Series(True, index=df.index)
        meta["gate_source"] = "disabled" if not gate_enabled or not require else "always"
        return active, meta

    if spec.kind == "fan_running":
        active, src = resolve_fan_running(df, command_fallback=spec.command_fallback_allowed)
    elif spec.kind == "hydronic_flow":
        active, src = resolve_hydronic_running(df, command_fallback=spec.command_fallback_allowed)
    elif spec.kind == "compressor":
        active, src = resolve_compressor_running(df, command_fallback=spec.command_fallback_allowed)
    elif spec.kind == "equipment_energized":
        active, src = resolve_equipment_energized(df, command_fallback=spec.command_fallback_allowed)
    elif spec.kind == "control_loop":
        active, src = resolve_fan_running(df, command_fallback=spec.command_fallback_allowed)
        if "loop-enabled" in df.columns:
            active = active & _series_on(df["loop-enabled"])
            src = f"{src}+loop_enabled"
    elif spec.kind == "conditional":
        active, src = resolve_conditional(df, rule_id, params=params)
    else:
        active, src = pd.Series(True, index=df.index), "always"

    if src.startswith("ungated"):
        meta["gate_source"] = src
        return pd.Series(True, index=df.index), meta

    delay = float(params.get("startup_delay_min", spec.startup_delay_seconds / 60.0)) * 60.0
    active = apply_startup_delay(active, poll_seconds, delay)
    n_active = int(active.sum())
    cov = 100.0 * n_active / max(len(df), 1)
    meta.update(
        {
            "gate_applied": True,
            "gate_source": src,
            "active_sample_count": n_active,
            "active_coverage_pct": round(cov, 1),
            "startup_delay_seconds": delay,
        }
    )
    return active.fillna(False), meta


def should_skip_equipment_off(meta: dict, params: dict | None = None, spec: GateSpec | None = None) -> bool:
    """True when gate applied but active coverage is below the configured minimum."""
    params = params or {}
    if not meta.get("gate_applied"):
        return False
    min_cov = float(
        params.get(
            "minimum_active_coverage_pct",
            (spec.minimum_active_coverage_pct if spec else 5.0),
        )
    )
    if int(meta.get("active_sample_count", 0)) == 0:
        return True
    # Honor the user/catalog value directly (default 5% = essentially-off floor).
    return float(meta.get("active_coverage_pct", 100)) < min_cov
