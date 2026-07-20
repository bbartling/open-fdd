"""Dataset analytics: date span, motor hours, mech-cooling OAT bins."""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from app.role_map import apply_role_map
from app.runtime_intervals import hours_under_mask, interval_durations
from app.site_model import normalize_equipment_type, resolve_equipment_type

# Plant groups for weekly motor charts.
PLANT_AIR = "air"
PLANT_BOILER = "boiler"
PLANT_CHILLER = "chiller"
PLANT_GROUPS: tuple[str, ...] = (PLANT_AIR, PLANT_BOILER, PLANT_CHILLER)

# Logical roles treated as motor / fan / pump runtime signals (0–100% or bool).
MOTOR_SIGNAL_ROLES: tuple[str, ...] = (
    "fan-cmd",
    "fan-status",
    "chw-pump-status",
    "chw-pump-cmd",
    "hw-pump-cmd",
    "pump-cmd",
    "pump-status",
)
MAPPED_FAN_ROLES: tuple[str, ...] = ("fan-status", "fan-cmd")
MAPPED_PUMP_ROLES: tuple[str, ...] = (
    "chw-pump-status",
    "chw-pump-cmd",
    "hw-pump-cmd",
    "pump-status",
    "pump-cmd",
)

# Mechanical cooling proof — compressor/chiller evidence only.
# Pumps and cooling valves remain motor/load evidence, never compressor proof.
CHILLER_STATUS_ROLES: tuple[str, ...] = (
    "chiller-status",
    "compressor-status",
)
CHILLER_RUN_ROLES: tuple[str, ...] = CHILLER_STATUS_ROLES
COMPRESSOR_STAGE_ROLES: tuple[str, ...] = (
    "compressor-stage-1",
    "compressor-stage-2",
    "cool-stage",
    "dx-stage",
)
COMPRESSOR_CMD_ROLES: tuple[str, ...] = ("compressor-cmd", "dx-cool-cmd")
HEAT_PUMP_COOLING_MODE_ROLES: tuple[str, ...] = (
    "heat-pump-cooling-status",
    "unit-cooling-status",
)
DX_RUN_ROLES: tuple[str, ...] = (
    "compressor-status",
    "compressor-cmd",
    "dx-cool-cmd",
    "dx-cooling",
    "unit-cooling-status",
    "compressor-stage-1",
    "compressor-stage-2",
    "cool-stage",
    "dx-stage",
)
VRF_RUN_ROLES: tuple[str, ...] = ("vrf-outdoor-compressor-status", "compressor-status")
MECH_COOL_SERIES_KINDS = (
    "individual_device",
    "aggregate_device_hours",
    "aggregate_active_hours",
)


def _is_on(series: pd.Series) -> pd.Series:
    """True when a command/status indicates the motor is running."""
    num = pd.to_numeric(series, errors="coerce")
    if num.notna().any():
        scaled = num.where(num <= 1.5, num / 100.0)
        return scaled.fillna(0) > 0.05
    return series.fillna(False).astype(bool)


def _above_threshold(series: pd.Series, thr: float) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce")
    return num.notna() & (num > float(thr))


def dataset_time_span(frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for df in frames.values():
        if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
            continue
        starts.append(df.index.min())
        ends.append(df.index.max())
    if not starts:
        return {"start": None, "end": None, "span_hours": 0.0}
    start = min(starts)
    end = max(ends)
    span_h = float((end - start).total_seconds() / 3600.0) if end > start else 0.0
    return {"start": start, "end": end, "span_hours": span_h}


def motor_run_hours_for_frame(
    df: pd.DataFrame,
    *,
    poll_seconds: float,
    equipment_id: str = "",
) -> list[dict[str, Any]]:
    """Accumulate on-hours for each motor-like role present on one equipment frame."""
    poll = max(float(poll_seconds), 1.0)
    rows: list[dict[str, Any]] = []
    for role in MOTOR_SIGNAL_ROLES:
        if role not in df.columns or df[role].notna().sum() == 0:
            continue
        on = _is_on(df[role])
        hours = float(on.sum() * poll / 3600.0)
        kind = "fan" if "fan" in role else "pump"
        rows.append(
            {
                "equipment_id": equipment_id,
                "signal": role,
                "motor_kind": kind,
                "run_hours": round(hours, 2),
                "on_samples": int(on.sum()),
                "samples": int(len(df)),
            }
        )
    return rows


def motor_run_hours_table(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
) -> pd.DataFrame:
    """Build a per-equipment motor run-hours table across the loaded dataset."""
    from app.data_loader import infer_poll_seconds

    rows: list[dict[str, Any]] = []
    for eq_id, raw in frames.items():
        mapped = apply_role_map(raw, eq_id, role_map)
        poll = float(raw.attrs.get("poll_seconds") or infer_poll_seconds(raw))
        rows.extend(motor_run_hours_for_frame(mapped, poll_seconds=poll, equipment_id=eq_id))
    if not rows:
        return pd.DataFrame(
            columns=["equipment_id", "signal", "motor_kind", "run_hours", "on_samples", "samples"]
        )
    return pd.DataFrame(rows).sort_values(["motor_kind", "equipment_id", "signal"])


def motor_run_hours_totals(table: pd.DataFrame) -> dict[str, float]:
    if table is None or table.empty:
        return {"fan_hours": 0.0, "pump_hours": 0.0, "total_hours": 0.0}
    prefer = table.copy()
    drop_idx: list = []
    for _eq, grp in prefer.groupby("equipment_id"):
        signals = set(grp["signal"])
        # Prefer proven status over command when both exist
        if "fan-status" in signals and "fan-cmd" in signals:
            drop_idx.extend(grp.index[grp["signal"] == "fan-cmd"].tolist())
        if "pump-status" in signals and any(s in signals for s in ("pump-cmd", "hw-pump-cmd", "chw-pump-cmd")):
            drop_idx.extend(
                grp.index[grp["signal"].isin(["pump-cmd", "hw-pump-cmd", "chw-pump-cmd"])].tolist()
            )
    prefer = prefer.drop(index=drop_idx)
    fan = float(prefer.loc[prefer["motor_kind"] == "fan", "run_hours"].sum())
    pump = float(prefer.loc[prefer["motor_kind"] == "pump", "run_hours"].sum())
    return {
        "fan_hours": round(fan, 1),
        "pump_hours": round(pump, 1),
        "total_hours": round(fan + pump, 1),
    }


def _preferred_motor_roles(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return (role, motor_kind) pairs, preferring status over command."""
    present = [r for r in MOTOR_SIGNAL_ROLES if r in df.columns and df[r].notna().any()]
    fans = [r for r in present if "fan" in r]
    pumps = [r for r in present if "fan" not in r]
    out: list[tuple[str, str]] = []
    if "fan-status" in fans:
        out.append(("fan-status", "fan"))
    elif "fan-cmd" in fans:
        out.append(("fan-cmd", "fan"))
    if "pump-status" in pumps:
        out.append(("pump-status", "pump"))
    elif "chw-pump-status" in pumps:
        out.append(("chw-pump-status", "pump"))
    else:
        for r in ("chw-pump-cmd", "hw-pump-cmd", "pump-cmd"):
            if r in pumps:
                out.append((r, "pump"))
                break
    return out


def _normalize_plant_group(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lower()
    aliases = {
        "air": PLANT_AIR,
        "ahu": PLANT_AIR,
        "boiler": PLANT_BOILER,
        "hw": PLANT_BOILER,
        "chiller": PLANT_CHILLER,
        "chw": PLANT_CHILLER,
        "chw_plant": PLANT_CHILLER,
    }
    return aliases.get(s) if s in aliases else (s if s in PLANT_GROUPS else None)


def _equipment_plant_group(
    equipment_id: str,
    equipment_type: str,
    *,
    df: pd.DataFrame | None = None,
    role_map: dict | None = None,
) -> str | None:
    """Plant chart group: attrs/role_map plant_group → typed equip → id fallback."""
    if df is not None:
        pg = _normalize_plant_group(df.attrs.get("plant_group"))
        if pg:
            return pg
    eq_roles = (role_map or {}).get(equipment_id) if role_map else None
    if isinstance(eq_roles, dict):
        pg = _normalize_plant_group(eq_roles.get("plant_group"))
        if pg:
            return pg

    et = normalize_equipment_type(equipment_type) or resolve_equipment_type(
        equipment_id, df=df, role_map=role_map
    )
    if et == "VAV":
        return None
    if et in {"AHU", "HP"}:
        return PLANT_AIR
    if et in {"CHW_PLANT", "CHILLER"}:
        return PLANT_CHILLER
    if et == "BOILER":
        return PLANT_BOILER
    if et in {"WEATHER", "METER"}:
        return None

    # Id fallback only when type is unknown / untyped
    eq = (equipment_id or "").upper().replace("\\", "/")
    if "/VAV" in eq or eq.startswith("VAV"):
        return None
    if eq.startswith("AHU") or "/AHU" in eq or "RTU" in eq:
        return PLANT_AIR
    if "TOWER" in eq or re.search(r"(^|/)CT\d", eq) or eq.startswith("CT_"):
        return PLANT_CHILLER
    if "CHILLER" in eq or eq.startswith("CHW"):
        return PLANT_CHILLER
    if "BOILER" in eq:
        return PLANT_BOILER
    if "CWP" in eq or "CHW_PUMP" in eq or ("PUMP" in eq and ("CHW" in eq or "CW" in eq)):
        return PLANT_CHILLER
    if "PUMP" in eq and "HEAT" not in eq:
        return PLANT_BOILER
    return None


def _has_mapped_roles(mapped: pd.DataFrame, roles: tuple[str, ...]) -> bool:
    return any(r in mapped.columns and mapped[r].notna().any() for r in roles)


def _explicit_role_keys(eq_roles: dict | None, roles: tuple[str, ...]) -> bool:
    """True when role_map explicitly maps one of the logical motor roles."""
    if not eq_roles:
        return False
    skip = {"chw_pump_equipment", "notes", "equipment_type", "equipType", "plant_group"}
    return any(
        r in roles and r not in skip and eq_roles.get(r)
        for r in roles
    )


_RE_HWP = re.compile(r"(?:^|_)(hwp)(\d+)[_ ]?([sc]|status|cmd|command)?(?:_|$)", re.I)
_RE_CWP = re.compile(
    r"(?:^|_)(cwp|chw_?pump|cw_?pump)(\d*)[_ ]?([sc]|status|cmd|command)?(?:_|$)",
    re.I,
)
_RE_TOWER = re.compile(
    r"(tower_?fan|ct_?fan|cooling_?tower|ctf\d*|tower_?motor|ct_?motor)",
    re.I,
)


def _col_signal_kind(col: str, suffix: str | None) -> str:
    cl = col.lower()
    suf = (suffix or "").lower()
    if suf in {"s", "status"} or "status" in cl or cl.endswith("_s"):
        return "status"
    if suf in {"c", "cmd", "command"} or "cmd" in cl or "command" in cl or cl.endswith("_c"):
        return "cmd"
    # bare names (e.g. tower_fan) — treat as status-like proof
    return "status"


def _skip_motor_column(col: str) -> bool:
    cl = col.lower()
    return any(
        x in cl
        for x in (
            "alarm",
            "lead",
            "setpoint",
            "setpt",
            "reset",
            "override",
            "enable_setpoint",
            "timestamp",
        )
    )


def _discover_named_pumps_and_towers(
    raw: pd.DataFrame,
    *,
    equipment_id: str,
    default_plant: str | None,
) -> list[dict[str, Any]]:
    """One series per physical pump / tower motor (status preferred over cmd)."""
    # key -> {status_col, cmd_col, plant, motor_kind, short}
    buckets: dict[str, dict[str, Any]] = {}

    for col in raw.columns:
        if col == "timestamp_utc" or _skip_motor_column(str(col)):
            continue
        cl = str(col).lower()
        series = pd.to_numeric(raw[col], errors="coerce")
        if series.notna().sum() == 0:
            continue

        m_hwp = _RE_HWP.search(cl)
        if m_hwp:
            key = f"hwp{m_hwp.group(2)}"
            kind = _col_signal_kind(cl, m_hwp.group(3))
            b = buckets.setdefault(
                key,
                {"plant": PLANT_BOILER, "motor_kind": "pump", "short": key.upper()},
            )
            b[kind] = col
            continue

        m_cwp = _RE_CWP.search(cl)
        if m_cwp and "hwp" not in cl:
            num = m_cwp.group(2) or "1"
            prefix = m_cwp.group(1).replace("_", "")
            key = f"{prefix}{num}"
            kind = _col_signal_kind(cl, m_cwp.group(3))
            b = buckets.setdefault(
                key,
                {"plant": PLANT_CHILLER, "motor_kind": "pump", "short": key.upper()},
            )
            b[kind] = col
            continue

        if _RE_TOWER.search(cl) and "temp" not in cl and "set" not in cl:
            key = f"tower:{col}"
            kind = _col_signal_kind(cl, None)
            b = buckets.setdefault(
                key,
                {
                    "plant": PLANT_CHILLER,
                    "motor_kind": "tower",
                    "short": str(col),
                },
            )
            b[kind] = col
            continue

    out: list[dict[str, Any]] = []
    for key, b in sorted(buckets.items()):
        col = b.get("status") or b.get("cmd")
        if col is None:
            continue
        signal = "pump-status" if b.get("status") else "pump-cmd"
        if b["motor_kind"] == "tower":
            signal = "tower_status" if b.get("status") else "tower_cmd"
        plant = b["plant"] if b["plant"] else default_plant
        if plant is None:
            continue
        out.append(
            {
                "equipment_id": equipment_id,
                "signal": signal,
                "column": col,
                "motor_kind": b["motor_kind"],
                "plant_group": plant,
                "label": f"{equipment_id} · {b['short']}",
                "series": raw[col],
            }
        )
    return out


def _discover_air_supply_fan(
    mapped: pd.DataFrame,
    raw: pd.DataFrame,
    *,
    equipment_id: str,
    allow_heuristics: bool = True,
) -> list[dict[str, Any]]:
    """Supply fan only (never return fan). Prefer mapped/heuristic status over command.

    When fan roles are empty: optional column-name heuristics (``suggest_roles``)
    only if ``allow_heuristics``. Never invent a series from raw ``supply_*``
    columns alone — omit when roles stay empty.
    """
    from app.role_map import suggest_roles

    work = mapped.copy()
    # Drop raw columns that collide with logical role names unless heuristics/map filled them
    # Prefer logical roles only (after suggest merge).
    logical: dict[str, pd.Series] = {}
    if allow_heuristics:
        suggested = suggest_roles(raw)
        for role in MAPPED_FAN_ROLES:
            col = suggested.get(role)
            if col and col in raw.columns and "return" not in str(col).lower():
                logical[role] = pd.to_numeric(raw[col], errors="coerce")
    # Explicit mapped logical roles win (apply_role_map already set them when in role_map)
    for role in MAPPED_FAN_ROLES:
        if role in mapped.columns and mapped[role].notna().any():
            # Only treat as logical if role_map applied it OR name equals role after suggest
            # Heuristic: if suggest points elsewhere and raw also has role-named col, prefer suggest status
            if role not in logical:
                logical[role] = pd.to_numeric(mapped[role], errors="coerce")

    if "fan-status" in logical and logical["fan-status"].notna().any():
        role, kind, ser = "fan-status", "fan", logical["fan-status"]
    elif "fan-cmd" in logical and logical["fan-cmd"].notna().any():
        role, kind, ser = "fan-cmd", "fan", logical["fan-cmd"]
    else:
        return []
    return [
        {
            "equipment_id": equipment_id,
            "signal": role,
            "column": role,
            "motor_kind": kind,
            "plant_group": PLANT_AIR,
            "label": f"{equipment_id} · {role}",
            "series": ser,
        }
    ]


def _resolve_linked_pump_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    equipment_id: str,
) -> tuple[pd.Series | None, str, str]:
    """Resolve designated CHW pump from role_map (same frame or linked equipment).

    Data-model keys on the chiller's role_map entry:
      - chw_pump_status / chw_pump_cmd → column name
      - chw_pump_equipment (optional meta) → other equipment_id that owns that column
    """
    eq_roles = role_map.get(equipment_id) or {}
    link_eq = str(eq_roles.get("chw_pump_equipment") or "").strip()
    src_id = link_eq if link_eq and link_eq in frames else equipment_id
    src = frames.get(src_id)
    if src is None or src.empty:
        return None, "", ""

    for role in ("chw-pump-status", "chw-pump-cmd"):
        col = eq_roles.get(role)
        if not col or not isinstance(col, str):
            continue
        if col in src.columns and pd.to_numeric(src[col], errors="coerce").notna().any():
            return src[col], role, f"{src_id}:{col}"
    return None, "", ""


def _discover_chiller_on(
    mapped: pd.DataFrame,
    raw: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    equipment_id: str,
    chw_leave_max_f: float = 48.0,
) -> list[dict[str, Any]]:
    """Chiller plant runtime: prefer mapped/heuristic **pump**, else status proof.

    Order: designated linked pump → chw_pump_status/cmd → named CWP → 
    ``chiller_status`` / ``compressor_status`` / ``equipment_enable``.
    Never invent runtime from CHW leave/supply temp.
    """
    del chw_leave_max_f  # kept for call-site compat; leave-temp never drives this chart
    # 1) Role-map designated pump (possibly on linked equipment)
    linked, link_role, link_label = _resolve_linked_pump_series(
        frames, role_map, equipment_id=equipment_id
    )
    if linked is not None:
        on = _is_on(linked)
        if bool(on.any()):
            return [
                {
                    "equipment_id": equipment_id,
                    "signal": link_role or "chw-pump-status",
                    "column": link_label,
                    "motor_kind": "chiller",
                    "plant_group": PLANT_CHILLER,
                    "label": f"{equipment_id} · {link_role or 'chw-pump-status'}",
                    "series_on": on.astype(float),
                }
            ]

    # 2) Mapped logical roles on this chiller frame
    for role in ("chw-pump-status", "pump-status"):
        if role in mapped.columns and mapped[role].notna().any():
            on = _is_on(mapped[role])
            if bool(on.any()):
                return [
                    {
                        "equipment_id": equipment_id,
                        "signal": role,
                        "column": role,
                        "motor_kind": "chiller",
                        "plant_group": PLANT_CHILLER,
                        "label": f"{equipment_id} · {role}",
                        "series_on": on.astype(float),
                    }
                ]
    for role in ("chw-pump-cmd", "pump-cmd"):
        if role in mapped.columns and mapped[role].notna().any():
            on = _is_on(mapped[role])
            if bool(on.any()):
                return [
                    {
                        "equipment_id": equipment_id,
                        "signal": role,
                        "column": role,
                        "motor_kind": "chiller",
                        "plant_group": PLANT_CHILLER,
                        "label": f"{equipment_id} · {role}",
                        "series_on": on.astype(float),
                    }
                ]

    # 3) Heuristic CWP columns on this frame (status over cmd)
    named = _discover_named_pumps_and_towers(
        raw, equipment_id=equipment_id, default_plant=PLANT_CHILLER
    )
    pumps = [p for p in named if p.get("motor_kind") == "pump"]
    status_pumps = [p for p in pumps if p.get("signal") == "pump-status"]
    pick = (status_pumps or pumps)
    if pick:
        p0 = pick[0]
        on = _is_on(p0["series"])
        if bool(on.any()):
            return [
                {
                    "equipment_id": equipment_id,
                    "signal": p0["signal"],
                    "column": p0.get("column", p0["signal"]),
                    "motor_kind": "chiller",
                    "plant_group": PLANT_CHILLER,
                    "label": f"{equipment_id} · {p0['signal']}",
                    "series_on": on.astype(float),
                }
            ]

    # 4) Fallback: chiller / compressor / equipment enable proof (never leave temp)
    for role in ("chiller-status", "compressor-status", "equipment-enable"):
        src = mapped if role in mapped.columns and mapped[role].notna().any() else None
        if src is None and role in raw.columns and raw[role].notna().any():
            src = raw
        if src is None:
            continue
        on = _is_on(src[role])
        if bool(on.any()):
            return [
                {
                    "equipment_id": equipment_id,
                    "signal": role,
                    "column": role,
                    "motor_kind": "chiller",
                    "plant_group": PLANT_CHILLER,
                    "label": f"{equipment_id} · {role}",
                    "series_on": on.astype(float),
                }
            ]

    # No pump and no status proof → no chiller run-hours series
    return []


def discover_plant_motor_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    chw_leave_max_f: float = 48.0,
) -> list[dict[str, Any]]:
    """Discover per-motor series for air / boiler / chiller weekly charts.

    Prefers mapped fan/pump roles. Named-pump regex runs only when pump roles are
    empty; tower motors still discovered. Do not invent supply fans from raw
    columns when fan roles stay empty (agent maps prefer omit over invent).
    """
    found: list[dict[str, Any]] = []
    for eq_id, raw in frames.items():
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        plant = _equipment_plant_group(eq_id, et, df=raw, role_map=role_map)
        mapped = apply_role_map(raw, eq_id, role_map)
        if not isinstance(mapped.index, pd.DatetimeIndex) and not isinstance(
            raw.index, pd.DatetimeIndex
        ):
            continue

        eq_roles = role_map.get(eq_id) or {}
        has_explicit = bool(eq_roles)
        # Explicit role_map keys only — raw CSVs may already have columns named fan_cmd
        has_mapped_fan = _explicit_role_keys(eq_roles, MAPPED_FAN_ROLES)
        has_mapped_pump = _explicit_role_keys(eq_roles, MAPPED_PUMP_ROLES)
        # Agent/explicit map: never invent fans from column names when fan roles empty
        allow_fan_heuristics = not has_explicit
        allow_pump_heuristics = (not has_explicit) or (not has_mapped_pump)

        # Named pumps only when no mapped pump roles; always keep tower motors
        if allow_pump_heuristics and not has_mapped_pump:
            found.extend(
                _discover_named_pumps_and_towers(raw, equipment_id=eq_id, default_plant=plant)
            )
        else:
            towers = [
                s
                for s in _discover_named_pumps_and_towers(
                    raw, equipment_id=eq_id, default_plant=plant
                )
                if s.get("motor_kind") == "tower"
            ]
            found.extend(towers)

        if plant == PLANT_AIR:
            found.extend(
                _discover_air_supply_fan(
                    mapped,
                    raw,
                    equipment_id=eq_id,
                    allow_heuristics=allow_fan_heuristics and not has_mapped_fan,
                )
            )
        elif plant == PLANT_CHILLER and et in {"CHW_PLANT", "CHILLER"}:
            found.extend(
                _discover_chiller_on(
                    mapped,
                    raw,
                    frames,
                    role_map,
                    equipment_id=eq_id,
                    chw_leave_max_f=chw_leave_max_f,
                )
            )
        elif plant == PLANT_CHILLER:
            if not any(s["equipment_id"] == eq_id and s["motor_kind"] == "pump" for s in found):
                work = mapped
                if allow_pump_heuristics and not has_mapped_pump:
                    from app.role_map import suggest_roles

                    suggested = suggest_roles(raw)
                    for role, col in suggested.items():
                        if (
                            role in MAPPED_PUMP_ROLES
                            and role not in work.columns
                            and col in raw.columns
                        ):
                            work = work.copy()
                            work[role] = pd.to_numeric(raw[col], errors="coerce")
                for role, kind in _preferred_motor_roles(work):
                    if "fan" in role:
                        continue
                    found.append(
                        {
                            "equipment_id": eq_id,
                            "signal": role,
                            "column": role,
                            "motor_kind": kind,
                            "plant_group": PLANT_CHILLER,
                            "label": f"{eq_id} · {role}",
                            "series": work[role],
                        }
                    )
        elif plant == PLANT_BOILER:
            if not any(s["equipment_id"] == eq_id and s["motor_kind"] == "pump" for s in found):
                work = mapped
                if allow_pump_heuristics and not has_mapped_pump:
                    from app.role_map import suggest_roles

                    suggested = suggest_roles(raw)
                    for role, col in suggested.items():
                        if (
                            role in MAPPED_PUMP_ROLES
                            and role not in work.columns
                            and col in raw.columns
                        ):
                            work = work.copy()
                            work[role] = pd.to_numeric(raw[col], errors="coerce")
                for role, kind in _preferred_motor_roles(work):
                    if "fan" in role:
                        continue
                    found.append(
                        {
                            "equipment_id": eq_id,
                            "signal": role,
                            "column": role,
                            "motor_kind": kind,
                            "plant_group": PLANT_BOILER,
                            "label": f"{eq_id} · {role}",
                            "series": work[role],
                        }
                    )
    return found


def motor_run_hours_weekly(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    chw_leave_max_f: float = 48.0,
    weather: pd.DataFrame | None = None,
    prefer_web_oat: bool = True,
) -> pd.DataFrame:
    """Weekly on-hours per motor, split by plant_group (air / boiler / chiller).

    Columns: week_start, week_label, equipment_id, signal, motor_kind, plant_group,
    label, hours, avg_oat_f (mean OAT while that motor was on in the week).
    """
    from app.data_loader import infer_poll_seconds

    rows: list[dict[str, Any]] = []
    series_list = discover_plant_motor_series(
        frames, role_map, chw_leave_max_f=chw_leave_max_f
    )
    poll_by_eq: dict[str, float] = {}
    oat_by_eq: dict[str, pd.Series] = {}
    for eq_id, raw in frames.items():
        poll_by_eq[eq_id] = float(raw.attrs.get("poll_seconds") or infer_poll_seconds(raw))
        mapped = apply_role_map(raw, eq_id, role_map)
        oat = _oat_series(mapped, weather, prefer_web=prefer_web_oat)
        if oat is not None:
            oat_by_eq[eq_id] = pd.to_numeric(oat, errors="coerce")

    for spec in series_list:
        eq_id = spec["equipment_id"]
        raw = frames.get(eq_id)
        if raw is None:
            continue
        poll = poll_by_eq.get(eq_id, 300.0)
        if "series_on" in spec:
            on = spec["series_on"].astype(float)
            idx = on.index
        else:
            ser = spec["series"]
            if not isinstance(ser.index, pd.DatetimeIndex):
                ser = pd.Series(ser.to_numpy(), index=raw.index)
            if not isinstance(ser.index, pd.DatetimeIndex) or ser.empty:
                continue
            on = _is_on(ser).astype(float)
            idx = on.index
        if not isinstance(idx, pd.DatetimeIndex) or len(on) == 0:
            continue
        hours = on * (poll / 3600.0)
        hours.index = idx
        weekly = hours.resample("W-MON", label="left", closed="left").sum()
        oat = oat_by_eq.get(eq_id)
        oat_on = None
        if oat is not None:
            oat_aligned = oat.reindex(idx)
            oat_on = oat_aligned.where(on > 0.05)
        weekly_oat = (
            oat_on.resample("W-MON", label="left", closed="left").mean()
            if oat_on is not None
            else None
        )
        for ts, h in weekly.items():
            if pd.isna(h) or float(h) <= 0:
                continue
            week = pd.Timestamp(ts)
            if week.tzinfo is not None:
                week = week.tz_convert("UTC").tz_localize(None)
            avg_oat = None
            if weekly_oat is not None and ts in weekly_oat.index and pd.notna(weekly_oat.loc[ts]):
                avg_oat = round(float(weekly_oat.loc[ts]), 1)
            rows.append(
                {
                    "week_start": week.normalize(),
                    "week_label": week.strftime("%Y-%m-%d"),
                    "equipment_id": eq_id,
                    "signal": spec["signal"],
                    "motor_kind": spec["motor_kind"],
                    "plant_group": spec["plant_group"],
                    "label": spec["label"],
                    "hours": round(float(h), 2),
                    "avg_oat_f": avg_oat,
                }
            )
    cols = [
        "week_start",
        "week_label",
        "equipment_id",
        "signal",
        "motor_kind",
        "plant_group",
        "label",
        "hours",
        "avg_oat_f",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows).sort_values(
        ["plant_group", "week_start", "motor_kind", "equipment_id", "signal"]
    )


def _first_on_mask(df: pd.DataFrame, roles: tuple[str, ...]) -> pd.Series | None:
    """Return on-mask for the first mapped role with data (even if never ON)."""
    for role in roles:
        if role in df.columns and df[role].notna().any():
            return _is_on(df[role])
    return None


def _or_on_mask(df: pd.DataFrame, roles: tuple[str, ...]) -> pd.Series | None:
    """OR on-masks across mapped roles (unit-active / multi-stage)."""
    masks: list[pd.Series] = []
    for role in roles:
        if role in df.columns and df[role].notna().any():
            masks.append(_is_on(df[role]).fillna(False).astype(bool))
    if not masks:
        return None
    out = masks[0]
    for m in masks[1:]:
        out = out | m.reindex(out.index).fillna(False)
    return out


def _mapped_role(df: pd.DataFrame, roles: tuple[str, ...]) -> str | None:
    for role in roles:
        if role in df.columns and df[role].notna().any():
            return role
    return None


def _oat_series(
    df: pd.DataFrame,
    weather: pd.DataFrame | None,
    *,
    prefer_web: bool = True,
) -> pd.Series | None:
    from app.weather_psychrometrics import prefer_web_oat

    return prefer_web_oat(df, weather, prefer_web=prefer_web)


def _chw_temp_proof(df: pd.DataFrame, leave_max_f: float) -> pd.Series | None:
    """True when chilled-water leave/supply is colder than threshold (plant producing cold water)."""
    for role in ("chilled-water-supply-temp", "chw_leave_t", "chws_t"):
        if role in df.columns and df[role].notna().any():
            t = pd.to_numeric(df[role], errors="coerce")
            # Ignore long zero/null sensor dropouts common in historians
            return t.notna() & (t > 32.0) & (t < float(leave_max_f))
    return None


def _chiller_on_mask(
    df: pd.DataFrame,
    *,
    chw_leave_max_f: float,
    chiller_amps_min: float = 5.0,
    chiller_power_kw_min: float = 1.0,
) -> tuple[pd.Series | None, str]:
    """Chiller ON: cmd/status → amps → power → CHW leave vs slider (no pumps)."""
    run = _first_on_mask(df, ("chiller-status", "compressor-status", "equipment-enable"))
    if run is not None:
        return run, "chiller-status"
    if "chiller-amps" in df.columns and df["chiller-amps"].notna().any():
        return _above_threshold(df["chiller-amps"], chiller_amps_min), "chiller-amps"
    if "chiller-power" in df.columns and df["chiller-power"].notna().any():
        return _above_threshold(df["chiller-power"], chiller_power_kw_min), "chiller_power"
    temp = _chw_temp_proof(df, chw_leave_max_f)
    if temp is not None:
        return temp, "chw_leave_temp"
    return None, ""


def _valve_open_mask(df: pd.DataFrame, role: str, thr_pct: float) -> pd.Series | None:
    if role not in df.columns or df[role].notna().sum() == 0:
        return None
    num = pd.to_numeric(df[role], errors="coerce")
    scaled = num.where(num <= 1.5, num / 100.0)
    return scaled.fillna(0) > (float(thr_pct) / 100.0)


def _mech_cooling_type(equipment_type: str, equipment_id: str = "") -> str:
    """Canonical cooling-dispatch type — **data model only**, never ad-hoc names.

    Normalizes aliases (``CHILLER``→``CHW_PLANT``, ``HEATPUMP``→``HP``,
    ``RTU``→``AHU``). When no type is supplied at all, defers to the central
    resolver's documented last resort (``equipment_type_from_id``) so headless
    callers that only have an id keep working — that heuristic lives in one
    place (`app/site_model.py`), not here.
    """
    et = normalize_equipment_type(equipment_type)
    if (not et or et == "UNKNOWN") and equipment_id:
        from app.site_model import equipment_type_from_id

        et = equipment_type_from_id(equipment_id)
    return et


def _cooling_technology(et: str, *, compressor_based: bool) -> str:
    if et == "CHW_PLANT":
        return "chilled_water_plant"
    if et == "HP":
        return "heat_pump"
    if et == "VRF":
        return "vrf"
    if et == "AHU":
        return "dx" if compressor_based else "chilled_water_coil"
    return "unknown"


def _analog_threshold_mask(
    df: pd.DataFrame,
    role: str,
    thr: float,
) -> tuple[pd.Series, str, float] | None:
    if role not in df.columns or not df[role].notna().any():
        return None
    return _above_threshold(df[role], thr), role, float(thr)


def _select_mech_cooling_proof(
    df: pd.DataFrame,
    *,
    equipment_type: str,
    equipment_id: str = "",
    chw_leave_max_f: float = 48.0,
    chiller_amps_min: float = 5.0,
    chiller_power_kw_min: float = 1.0,
    use_status_proof: bool = True,
    _cooling_mode: pd.Series | None = None,
) -> dict[str, Any]:
    """Deterministic proof selection. Mask may be all-False when proof is valid but idle."""
    empty = {
        "mask": None,
        "proof_role": "",
        "proof_column": "",
        "proof_threshold": None,
        "proof_quality": "",
        "legacy_proof": "",
    }
    et = _mech_cooling_type(equipment_type, equipment_id)

    def _direct(
        mask: pd.Series,
        role: str,
        legacy: str,
        *,
        column: str | None = None,
    ) -> dict[str, Any]:
        return {
            "mask": mask.fillna(False).astype(bool),
            "proof_role": role,
            "proof_column": column or role,
            "proof_threshold": None,
            "proof_quality": "direct",
            "legacy_proof": legacy,
        }

    def _choose(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """First active proof wins; otherwise retain highest-priority mapped proof."""
        if _cooling_mode is not None:
            gated: list[dict[str, Any]] = []
            for candidate in candidates:
                candidate = dict(candidate)
                candidate["mask"] = candidate["mask"] & _cooling_mode.reindex(
                    candidate["mask"].index
                ).fillna(False)
                gated.append(candidate)
            candidates = gated
        for candidate in candidates:
            if bool(candidate["mask"].any()):
                return candidate
        return candidates[0] if candidates else empty

    def _analog(mask: pd.Series, role: str, thr: float, legacy: str) -> dict[str, Any]:
        return {
            "mask": mask.fillna(False).astype(bool),
            "proof_role": role,
            "proof_column": role,
            "proof_threshold": float(thr),
            "proof_quality": "analog",
            "legacy_proof": legacy,
        }

    if et == "CHW_PLANT":
        if not use_status_proof:
            temp = _chw_temp_proof(df, chw_leave_max_f)
            if temp is None:
                return empty
            return {
                "mask": temp.fillna(False).astype(bool),
                "proof_role": "chilled-water-supply-temp",
                "proof_column": _mapped_role(
                    df, ("chilled-water-supply-temp", "chw_leave_t", "chws_t")
                )
                or "chilled-water-supply-temp",
                "proof_threshold": float(chw_leave_max_f),
                "proof_quality": "inferred",
                "legacy_proof": "inferred: chw_leave_temp",
            }
        candidates: list[dict[str, Any]] = []
        run = _first_on_mask(df, CHILLER_STATUS_ROLES)
        if run is not None:
            role = _mapped_role(df, CHILLER_STATUS_ROLES) or "chiller-status"
            candidates.append(_direct(run, role, "chiller-status"))
        run = _first_on_mask(df, COMPRESSOR_CMD_ROLES)
        if run is not None:
            role = _mapped_role(df, COMPRESSOR_CMD_ROLES) or "compressor-cmd"
            candidates.append(_direct(run, role, "chiller-status"))
        amps = _analog_threshold_mask(df, "chiller-amps", chiller_amps_min)
        if amps is not None:
            mask, role, thr = amps
            candidates.append(_analog(mask, role, thr, "chiller-amps"))
        for role, thr, legacy in (
            ("chiller-power", chiller_power_kw_min, "chiller_power"),
            ("compressor-power", chiller_power_kw_min, "chiller_power"),
            ("compressor-current", chiller_amps_min, "chiller-amps"),
        ):
            hit = _analog_threshold_mask(df, role, thr)
            if hit is not None:
                mask, role_n, thr_n = hit
                candidates.append(_analog(mask, role_n, thr_n, legacy))
        return _choose(candidates)

    if et in {"AHU", "RTU"}:
        candidates = []
        run = _first_on_mask(df, ("compressor-status",))
        if run is not None:
            candidates.append(_direct(run, "compressor-status", "ahu_dx"))
        run = _first_on_mask(df, COMPRESSOR_CMD_ROLES)
        if run is not None:
            role = _mapped_role(df, COMPRESSOR_CMD_ROLES) or "compressor-cmd"
            candidates.append(_direct(run, role, "ahu_dx"))
        stages = _or_on_mask(df, COMPRESSOR_STAGE_ROLES)
        if stages is not None:
            stage_roles = [
                role
                for role in COMPRESSOR_STAGE_ROLES
                if role in df.columns and df[role].notna().any()
            ]
            candidates.append(
                _direct(
                    stages,
                    "compressor-stage",
                    "ahu_dx",
                    column=", ".join(stage_roles),
                )
            )
        run = _first_on_mask(df, ("dx-cooling", "unit-cooling-status"))
        if run is not None:
            role = _mapped_role(df, ("dx-cooling", "unit-cooling-status")) or "dx-cooling"
            candidates.append(_direct(run, role, "ahu_dx"))
        for role, thr in (
            ("compressor-power", chiller_power_kw_min),
            ("compressor-current", chiller_amps_min),
        ):
            hit = _analog_threshold_mask(df, role, thr)
            if hit is not None:
                mask, role_n, thr_n = hit
                candidates.append(_analog(mask, role_n, thr_n, "ahu_dx"))
        return _choose(candidates)

    if et == "HP":
        mode = _or_on_mask(df, HEAT_PUMP_COOLING_MODE_ROLES)
        if mode is None:
            return empty
        base = _select_mech_cooling_proof(
            df,
            equipment_type="AHU",
            equipment_id=equipment_id,
            chw_leave_max_f=chw_leave_max_f,
            chiller_amps_min=chiller_amps_min,
            chiller_power_kw_min=chiller_power_kw_min,
            use_status_proof=True,
            _cooling_mode=mode,
        )
        if base["mask"] is None:
            return empty
        base["legacy_proof"] = "heatpump"
        return base

    if et == "VRF":
        candidates = []
        for role in VRF_RUN_ROLES:
            run = _first_on_mask(df, (role,))
            if run is not None:
                candidates.append(_direct(run, role, "vrf-outdoor-compressor-status"))
        return _choose(candidates)

    return empty


def mech_cooling_run_mask(
    df: pd.DataFrame,
    *,
    equipment_type: str,
    equipment_id: str = "",
    chw_leave_max_f: float = 48.0,
    include_ahu_chw_valve: bool = False,
    clg_valve_thr_pct: float = 5.0,
    chiller_amps_min: float = 5.0,
    chiller_power_kw_min: float = 1.0,
    use_status_proof: bool = True,
) -> tuple[pd.Series | None, str]:
    """
    Mechanical-cooling proof for OAT-bin charts (compressor / plant only).

    Dispatch is on the **resolved equipment type** (column_map ``equipType`` /
    attrs / role_map) — never the equipment name.

    Returns a boolean mask even when a valid mapped proof stays off. Only
    absence/invalid proof returns ``(None, "")``. Cooling valves never prove
    compressor operation. Heat pumps require cooling-mode evidence.
    """
    del include_ahu_chw_valve, clg_valve_thr_pct  # never valve on this chart
    selected = _select_mech_cooling_proof(
        df,
        equipment_type=equipment_type,
        equipment_id=equipment_id,
        chw_leave_max_f=chw_leave_max_f,
        chiller_amps_min=chiller_amps_min,
        chiller_power_kw_min=chiller_power_kw_min,
        use_status_proof=use_status_proof,
    )
    return selected["mask"], selected["legacy_proof"] or selected["proof_role"]


def _mech_cooling_candidate_roles(
    df: pd.DataFrame,
    *,
    equipment_type: str,
    equipment_id: str = "",
    use_status_proof: bool = True,
) -> tuple[bool, list[str]]:
    """(is a cooling-proof candidate, mapped run-proof roles present with data).

    Mirrors the role lookups in :func:`mech_cooling_run_mask` so coverage
    reporting can say *which* mapped columns were checked for run proof.
    Dispatch is type-only (see :func:`_mech_cooling_type`).
    """
    et = _mech_cooling_type(equipment_type, equipment_id)
    if et == "CHW_PLANT":
        if use_status_proof:
            roles = list(CHILLER_STATUS_ROLES + COMPRESSOR_CMD_ROLES) + [
                "chiller-amps",
                "chiller-power",
                "compressor-power",
                "compressor-current",
            ]
        else:
            roles = ["chilled-water-supply-temp", "chw_leave_t", "chws_t"]
    elif et in {"AHU", "RTU"}:
        roles = list(DX_RUN_ROLES) + ["compressor-power", "compressor-current"]
    elif et == "HP":
        roles = list(DX_RUN_ROLES) + list(HEAT_PUMP_COOLING_MODE_ROLES) + [
            "compressor-power",
            "compressor-current",
        ]
    elif et == "VRF":
        roles = list(VRF_RUN_ROLES)
    else:
        return False, []
    present = [r for r in roles if r in df.columns and df[r].notna().any()]
    return True, present


MECH_COOL_TOTAL_ID = "ALL"
MECH_COOL_TOTAL_LABEL = "All mech cooling (total)"

_OAT_BIN_COLUMNS = [
    "equipment_id",
    "source",
    "source_kind",
    "series_kind",
    "series_id",
    "bin_start",
    "bin_label",
    "hours",
    "runtime_hours",
    "valid_elapsed_hours",
    "coverage_pct",
    "equipment_type",
    "cooling_technology",
    "proof_role",
    "proof_quality",
    "device_count",
]


def _mechanical_cooling_devices(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    weather: pd.DataFrame | None = None,
    prefer_web_oat: bool = True,
    chw_leave_max_f: float = 48.0,
    use_status_proof: bool = True,
    chiller_amps_min: float = 5.0,
    chiller_power_kw_min: float = 1.0,
) -> list[dict[str, Any]]:
    """Normalized mechanical-cooling device records with proof masks."""
    from app.data_loader import infer_poll_seconds

    devices: list[dict[str, Any]] = []
    for eq_id, raw in frames.items():
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        mapped = apply_role_map(raw, eq_id, role_map)
        is_candidate, checked = _mech_cooling_candidate_roles(
            mapped,
            equipment_type=et,
            equipment_id=eq_id,
            use_status_proof=use_status_proof,
        )
        if not is_candidate:
            continue

        poll = float(raw.attrs.get("poll_seconds") or infer_poll_seconds(raw) or 3600.0)
        oat = _oat_series(mapped, weather, prefer_web=prefer_web_oat)
        base: dict[str, Any] = {
            "equipment_id": eq_id,
            "equipment_type": et,
            "checked_roles": ", ".join(checked) if checked else "—",
            "mapped": mapped,
            "poll_seconds": poll,
            "oat": oat,
            "run_mask": None,
            "cooling_technology": "unknown",
            "compressor_based": False,
            "included": False,
            "eligibility_state": "excluded_missing_proof",
            "activity_state": "none",
            "proof_quality": "",
            "proof_role": "",
            "proof_column": "",
            "proof_threshold": None,
            "runtime_hours": 0.0,
            "valid_elapsed_hours": 0.0,
            "coverage_pct": 0.0,
            "exclusion_reason": "",
            "status": "excluded",
            "proof": "",
            "reason": "",
        }

        if not checked and et in {"AHU", "HP", "RTU"}:
            has_clg_valve = (
                "cooling-valve" in mapped.columns and mapped["cooling-valve"].notna().any()
            )
            if not has_clg_valve:
                continue
            base["checked_roles"] = "cooling-valve (informational)"
            base["cooling_technology"] = "chilled_water_coil"
            base["compressor_based"] = False
            base["eligibility_state"] = "excluded_non_compressor"
            base["exclusion_reason"] = (
                "CHW-coil unit — cooling valve is never used as compressor proof; "
                "its cooling hours are carried by the plant chillers"
            )
            base["reason"] = base["exclusion_reason"]
            devices.append(base)
            continue

        if not checked:
            base["exclusion_reason"] = (
                "no CHW leaving-temperature role mapped"
                if et == "CHW_PLANT" and not use_status_proof
                else "no compressor/chiller status, command, power, or current proof mapped"
            )
            base["reason"] = base["exclusion_reason"]
            base["cooling_technology"] = _cooling_technology(et, compressor_based=True)
            base["compressor_based"] = et in {"CHW_PLANT", "AHU", "RTU", "HP", "VRF"}
            devices.append(base)
            continue

        if et == "HP" and _mapped_role(mapped, HEAT_PUMP_COOLING_MODE_ROLES) is None:
            base["cooling_technology"] = "heat_pump"
            base["compressor_based"] = True
            base["exclusion_reason"] = (
                "heat pump missing cooling-mode proof "
                "(map heat-pump-cooling-status or unit-cooling-status)"
            )
            base["reason"] = base["exclusion_reason"]
            devices.append(base)
            continue

        selected = _select_mech_cooling_proof(
            mapped,
            equipment_type=et,
            equipment_id=eq_id,
            chw_leave_max_f=chw_leave_max_f,
            chiller_amps_min=chiller_amps_min,
            chiller_power_kw_min=chiller_power_kw_min,
            use_status_proof=use_status_proof,
        )
        run = selected["mask"]
        if run is None:
            base["cooling_technology"] = _cooling_technology(et, compressor_based=True)
            base["compressor_based"] = True
            base["exclusion_reason"] = (
                "no compressor/chiller status, command, power, or current proof mapped"
            )
            base["reason"] = base["exclusion_reason"]
            devices.append(base)
            continue

        durations = interval_durations(run.index, nominal_seconds=poll)
        valid_elapsed = float(durations.sum() / 3600.0)
        runtime = hours_under_mask(run, nominal_seconds=poll)
        compressor_based = True
        tech = _cooling_technology(et, compressor_based=True)
        included = True
        eligibility = "eligible_with_runtime" if runtime > 1e-12 else "eligible_no_runtime"
        activity = "active" if runtime > 1e-12 else "inactive"
        reason = ""
        if selected["legacy_proof"] == "inferred: chw_leave_temp":
            reason = (
                "Inferred from CHW leaving temperature; cold water can flow through "
                "an idle chiller."
            )

        span_hours = 0.0
        if isinstance(run.index, pd.DatetimeIndex) and len(run.index) > 1:
            span_hours = float(
                (run.index.max() - run.index.min()).total_seconds() / 3600.0
            )
        coverage_pct = (
            round(100.0 * valid_elapsed / span_hours, 2) if span_hours > 0 else 0.0
        )

        base.update(
            {
                "run_mask": run.fillna(False).astype(bool),
                "cooling_technology": tech,
                "compressor_based": compressor_based,
                "included": included,
                "eligibility_state": eligibility,
                "activity_state": activity,
                "proof_quality": selected["proof_quality"],
                "proof_role": selected["proof_role"],
                "proof_column": selected["proof_column"],
                "proof_threshold": selected["proof_threshold"],
                "runtime_hours": round(float(runtime), 2),
                "valid_elapsed_hours": round(valid_elapsed, 2),
                "coverage_pct": coverage_pct,
                "exclusion_reason": "",
                "status": "included",
                "proof": selected["legacy_proof"] or selected["proof_role"],
                "reason": reason,
            }
        )
        devices.append(base)
    return devices


def mech_cooling_coverage(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    weather: pd.DataFrame | None = None,
    prefer_web_oat: bool = True,
    chw_leave_max_f: float = 48.0,
    use_status_proof: bool = True,
) -> pd.DataFrame:
    """Per-device inclusion/exclusion report for the mech-cooling OAT-bin chart.

    One row per cooling-capable device **per the data model**: chillers / CHW
    plants, AHUs or heat pumps with DX/compressor roles, VRF outdoor units, and
    CHW-coil AHUs/HPs (cooling valve mapped, no compressor) as informational
    exclusions. Eligible devices with valid mapped proof that never run are
    ``eligible_no_runtime`` (included), not excluded.
    """
    devices = _mechanical_cooling_devices(
        frames,
        role_map,
        weather=weather,
        prefer_web_oat=prefer_web_oat,
        chw_leave_max_f=chw_leave_max_f,
        use_status_proof=use_status_proof,
    )
    cols = [
        "equipment_id",
        "equipment_type",
        "cooling_technology",
        "compressor_based",
        "included",
        "eligibility_state",
        "activity_state",
        "proof_quality",
        "proof_role",
        "proof_column",
        "proof_threshold",
        "runtime_hours",
        "valid_elapsed_hours",
        "coverage_pct",
        "exclusion_reason",
        "status",
        "proof",
        "reason",
        "checked_roles",
    ]
    if not devices:
        return pd.DataFrame(columns=cols)
    rows = [{k: d.get(k) for k in cols} for d in devices]
    return (
        pd.DataFrame(rows)[cols]
        .sort_values(["status", "equipment_id"])
        .reset_index(drop=True)
    )


def _bin_runtime_rows(
    *,
    equipment_id: str,
    source: str,
    source_kind: str,
    series_kind: str,
    series_id: str,
    oat: pd.Series,
    mask: pd.Series,
    nominal_seconds: float,
    bin_width_f: float,
    equipment_type: str = "",
    cooling_technology: str = "",
    proof_role: str = "",
    proof_quality: str = "",
    device_count: int = 1,
) -> list[dict[str, Any]]:
    """Attribute interval durations under mask into OAT bins."""
    aligned_mask = mask.groupby(level=0).max().sort_index().fillna(False).astype(bool)
    durations = interval_durations(aligned_mask.index, nominal_seconds=nominal_seconds)
    oat_aligned = (
        oat.groupby(level=0).max().sort_index().reindex(durations.index)
        if isinstance(oat.index, pd.DatetimeIndex)
        else oat.reindex(durations.index)
    )
    on = aligned_mask.reindex(durations.index).fillna(False).astype(bool)
    usable = on & oat_aligned.notna() & (durations > 0)
    if not bool(usable.any()):
        return []
    idx = durations.index[usable.to_numpy()]
    clamped = oat_aligned.reindex(idx).clip(40, 110)
    bin_start = (
        np.floor(clamped.to_numpy(dtype=float) / float(bin_width_f)) * float(bin_width_f)
    ).astype(int)
    tmp = pd.DataFrame(
        {
            "bin_start": bin_start,
            "seconds": durations.reindex(idx).to_numpy(dtype=float),
        },
        index=idx,
    )
    valid_elapsed = float(durations.sum() / 3600.0)
    span = 0.0
    if len(durations.index) > 1:
        span = float(
            (durations.index.max() - durations.index.min()).total_seconds() / 3600.0
        )
    coverage_pct = round(100.0 * valid_elapsed / span, 2) if span > 0 else 0.0
    rows: list[dict[str, Any]] = []
    for b, g in tmp.groupby("bin_start"):
        if pd.isna(b):
            continue
        b_i = int(b)
        hours = float(g["seconds"].sum() / 3600.0)
        rows.append(
            {
                "equipment_id": equipment_id,
                "source": source,
                "source_kind": source_kind,
                "series_kind": series_kind,
                "series_id": series_id,
                "bin_start": b_i,
                "bin_label": f"{b_i}–{b_i + int(bin_width_f)}",
                "hours": round(hours, 2),
                "runtime_hours": round(hours, 2),
                "valid_elapsed_hours": round(valid_elapsed, 2),
                "coverage_pct": coverage_pct,
                "equipment_type": equipment_type,
                "cooling_technology": cooling_technology,
                "proof_role": proof_role,
                "proof_quality": proof_quality,
                "device_count": int(device_count),
            }
        )
    return rows


def mech_cooling_oat_bins(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    weather: pd.DataFrame | None = None,
    bin_width_f: float = 5.0,
    prefer_web_oat: bool = True,
    chw_leave_max_f: float = 48.0,
    include_ahu_chw_valve: bool = False,
    clg_valve_thr_pct: float = 5.0,
    include_total: bool = False,
    use_status_proof: bool = True,
) -> pd.DataFrame:
    """
    Mechanical cooling run hours binned by OAT (default: web/Open-Meteo dry bulb).

    Emits ``individual_device`` rows plus, when ``include_total=True``,
    ``aggregate_device_hours`` (``equipment_id="ALL"``, ``source_kind="total"``)
    and ``aggregate_active_hours`` (``series_id="aggregate_active_hours"``).
    Never bins CHW cooling-valve open time.
    """
    del include_ahu_chw_valve, clg_valve_thr_pct
    devices = _mechanical_cooling_devices(
        frames,
        role_map,
        weather=weather,
        prefer_web_oat=prefer_web_oat,
        chw_leave_max_f=chw_leave_max_f,
        use_status_proof=use_status_proof,
    )
    rows: list[dict[str, Any]] = []
    active_parts: list[tuple[pd.Series, pd.Series, float]] = []

    for d in devices:
        if not d["included"] or d["run_mask"] is None:
            continue
        oat = d["oat"]
        if oat is None:
            continue
        run = d["run_mask"]
        if not bool(run.any()):
            continue
        proof = d["proof"] or d["proof_role"]
        rows.extend(
            _bin_runtime_rows(
                equipment_id=d["equipment_id"],
                source=f"{d['equipment_id']} ({proof})",
                source_kind=proof,
                series_kind="individual_device",
                series_id=d["equipment_id"],
                oat=oat,
                mask=run,
                nominal_seconds=d["poll_seconds"],
                bin_width_f=bin_width_f,
                equipment_type=d["equipment_type"],
                cooling_technology=d["cooling_technology"],
                proof_role=d["proof_role"],
                proof_quality=d["proof_quality"],
                device_count=1,
            )
        )
        active_parts.append((run, oat, float(d["poll_seconds"])))

    if not rows:
        return pd.DataFrame(columns=_OAT_BIN_COLUMNS)

    if include_total:
        per_dev = pd.DataFrame(rows)
        n_devices = int(per_dev["equipment_id"].nunique())
        for (b_i, b_label), g in per_dev.groupby(["bin_start", "bin_label"]):
            hours = float(g["runtime_hours"].sum())
            rows.append(
                {
                    "equipment_id": MECH_COOL_TOTAL_ID,
                    "source": f"{MECH_COOL_TOTAL_LABEL} — {n_devices} device(s)",
                    "source_kind": "total",
                    "series_kind": "aggregate_device_hours",
                    "series_id": "aggregate_device_hours",
                    "bin_start": int(b_i),
                    "bin_label": str(b_label),
                    "hours": round(hours, 2),
                    "runtime_hours": round(hours, 2),
                    "valid_elapsed_hours": round(float(g["valid_elapsed_hours"].max()), 2),
                    "coverage_pct": round(float(g["coverage_pct"].max()), 2),
                    "equipment_type": "",
                    "cooling_technology": "",
                    "proof_role": "",
                    "proof_quality": "",
                    "device_count": n_devices,
                }
            )

        # Any-active hours: OR masks on the union timeline, then bin by OAT.
        if active_parts:
            indexes = [
                p[0].groupby(level=0).max().sort_index().index for p in active_parts
            ]
            union_idx = indexes[0]
            for ix in indexes[1:]:
                union_idx = union_idx.union(ix)
            union_idx = pd.DatetimeIndex(union_idx).drop_duplicates().sort_values()
            any_active = pd.Series(False, index=union_idx)
            oat_pieces: list[pd.Series] = []
            # The shortest source cadence gives the conservative 3x gap cap.
            # A median cadence can over-credit a sparse union interval when a
            # fast device's last active sample precedes a slow device timestamp.
            nominal = float(min(p[2] for p in active_parts))
            for run, oat, _poll in active_parts:
                r = run.groupby(level=0).max().sort_index()
                any_active = any_active | r.astype(bool).reindex(
                    union_idx, fill_value=False
                )
                o = oat.groupby(level=0).max().sort_index().reindex(union_idx)
                oat_pieces.append(o)
            oat_union = oat_pieces[0]
            for o in oat_pieces[1:]:
                oat_union = oat_union.fillna(o)
            rows.extend(
                _bin_runtime_rows(
                    equipment_id="ACTIVE",
                    source="Any compressor active",
                    source_kind="active",
                    series_kind="aggregate_active_hours",
                    series_id="aggregate_active_hours",
                    oat=oat_union,
                    mask=any_active,
                    nominal_seconds=nominal,
                    bin_width_f=bin_width_f,
                    device_count=n_devices,
                )
            )

    out = pd.DataFrame(rows)
    for col in _OAT_BIN_COLUMNS:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[_OAT_BIN_COLUMNS].sort_values(["bin_start", "series_kind", "source"])
    return out.reset_index(drop=True)


def sensor_type_for_role(role: str) -> str:
    """HVAC quantity bucket — local copy so analytics does not import cookbook at module load."""
    r = (role or "").lower()
    if "humid" in r:
        return "Humidity"
    if "pressure" in r or "static" in r or r.endswith("-dp"):
        return "Pressure"
    if "flow" in r or "cfm" in r or "gpm" in r:
        return "Flow"
    if "temp" in r or "wetbulb" in r or "dewpoint" in r:
        return "Temperature"
    return "Other"


def sensor_fault_summary(
    df: pd.DataFrame,
    results: list,
    *,
    equipment_id: str,
    poll_seconds: float = 300.0,
) -> pd.DataFrame:
    """Per-sensor summary for sensor-validation rules (including SV-RATE).

    Uses per-role confirmed masks / evidence so healthy sensors do not inherit
    another sensor's fault window.
    """
    del poll_seconds  # hours come from evidence / confirmed role masks
    rows: list[dict] = []
    sweep_rules = {"SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE"}
    for r in results:
        if getattr(r, "equipment_id", None) != equipment_id:
            continue
        rid = getattr(r, "rule_id", "")
        metrics = getattr(r, "metrics", None) or {}
        series_map = getattr(r, "plot_series", None) or {}

        if rid in sweep_rules:
            evidence = list(metrics.get("sv_sweep_evidence") or [])
            role_masks = metrics.get("sv_sweep_confirmed_roles") or {}
            # Prefer evidence (even PASS); fall back to plot_series only for FAULT legacy
            if evidence:
                for ev in evidence:
                    if not ev.get("faulted") and getattr(r, "status", "") != "FAULT":
                        # Still list checked sensors with 0 hours when rule FAULTed for others
                        pass
                    role = str(ev.get("role") or "")
                    if not role:
                        continue
                    if not ev.get("faulted"):
                        continue  # only sensors that actually fired
                    num = pd.to_numeric(series_map.get(role, pd.Series(dtype=float)), errors="coerce")
                    mask = role_masks.get(role)
                    if isinstance(mask, pd.Series):
                        m = mask.reindex(num.index).fillna(0).astype(bool) if len(num) else mask.fillna(False).astype(bool)
                    else:
                        m = None
                    fault_vals = num[m] if m is not None and len(num) and m.any() else num.iloc[0:0]
                    rows.append(
                        {
                            "equipment_id": equipment_id,
                            "rule_id": rid,
                            "sensor": role,
                            "sensor_type": ev.get("sensor_type") or sensor_type_for_role(role),
                            "fault_hours": ev.get("fault_hours"),
                            "n": int(num.notna().sum()) if len(num) else 0,
                            "n_fault_samples": int(ev.get("fault_samples") or 0),
                            "mean": round(float(num.mean()), 3) if num.notna().any() else None,
                            "std": round(float(num.std(ddof=0)), 3) if num.notna().sum() > 1 else 0.0,
                            "min": round(float(num.min()), 3) if num.notna().any() else None,
                            "p50": round(float(num.quantile(0.5)), 3) if num.notna().any() else None,
                            "max": round(float(num.max()), 3) if num.notna().any() else None,
                            "fault_mean": round(float(fault_vals.mean()), 3) if len(fault_vals) and fault_vals.notna().any() else None,
                            "fault_min": round(float(fault_vals.min()), 3) if len(fault_vals) and fault_vals.notna().any() else None,
                            "fault_max": round(float(fault_vals.max()), 3) if len(fault_vals) and fault_vals.notna().any() else None,
                            "first_fault_timestamp": ev.get("first_fault_timestamp"),
                            "last_fault_timestamp": ev.get("last_fault_timestamp"),
                        }
                    )
            elif getattr(r, "status", "") == "FAULT":
                # Legacy fallback (no evidence) — do not invent per-sensor guilt
                continue
        elif rid in {"SV-RATE", "SV-SLEW"}:
            for ev in list(metrics.get("sv_rate_evidence") or []):
                role = str(ev.get("role") or "")
                if not role:
                    continue
                viol_min = float(ev.get("violation_minutes") or 0.0)
                fault_h = float(ev.get("fault_hours_raw") or (viol_min / 60.0) or 0.0)
                if fault_h <= 0 and int(ev.get("violation_count") or 0) <= 0:
                    continue
                rows.append(
                    {
                        "equipment_id": equipment_id,
                        "rule_id": "SV-RATE",
                        "sensor": role,
                        "sensor_type": sensor_type_for_role(role),
                        "fault_hours": round(fault_h, 3),
                        "n": int(ev.get("sample_count") or 0),
                        "n_fault_samples": int(ev.get("violation_count") or 0),
                        "mean": None,
                        "std": None,
                        "min": None,
                        "p50": None,
                        "max": round(float(ev["maximum_rate"]), 3) if ev.get("maximum_rate") is not None else None,
                        "fault_mean": None,
                        "fault_min": None,
                        "fault_max": None,
                        "first_fault_timestamp": ev.get("first_violation_timestamp"),
                        "last_fault_timestamp": ev.get("last_violation_timestamp"),
                        "diagnostic": ev.get("diagnostic_message"),
                    }
                )

    cols = [
        "equipment_id",
        "rule_id",
        "sensor",
        "sensor_type",
        "fault_hours",
        "n",
        "n_fault_samples",
        "mean",
        "std",
        "min",
        "p50",
        "max",
        "fault_mean",
        "fault_min",
        "fault_max",
        "first_fault_timestamp",
        "last_fault_timestamp",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    for c in cols:
        if c not in out.columns:
            out[c] = None
    return out[cols].sort_values(["sensor_type", "sensor", "rule_id"]).reset_index(drop=True)


def sensor_health_matrix(
    df: pd.DataFrame,
    results: list,
    *,
    equipment_id: str,
) -> pd.DataFrame:
    """Wide table: one row per sensor, columns per SV rule with fault hours or OK."""
    summary = sensor_fault_summary(df, results, equipment_id=equipment_id)
    # Also include all mapped sensors present on the frame even if OK
    from app.rules.cookbook_catalog import SWEEP_SENSOR_ROLES, sensor_type_for_role as _stype

    present = [r for r in SWEEP_SENSOR_ROLES if r in df.columns and df[r].notna().any()]
    # RATEABLE roles from SV-RATE
    for r in results:
        if getattr(r, "equipment_id", None) != equipment_id:
            continue
        if getattr(r, "rule_id", "") in {"SV-RATE", "SV-SLEW"}:
            for role in (getattr(r, "metrics", {}) or {}).get("sensors_checked") or []:
                if role not in present:
                    present.append(role)

    rule_cols = ["SV-RANGE", "SV-SPIKE", "SV-FLATLINE", "SV-STALE", "SV-RATE"]
    rows = []
    for role in present:
        row: dict[str, Any] = {
            "equipment_id": equipment_id,
            "sensor": role,
            "sensor_type": _stype(role),
        }
        for rid in rule_cols:
            row[rid] = "OK"
        rows.append(row)
    by_sensor = {r["sensor"]: r for r in rows}
    if not summary.empty:
        for _, srow in summary.iterrows():
            role = str(srow["sensor"])
            rid = str(srow["rule_id"])
            if role not in by_sensor:
                by_sensor[role] = {
                    "equipment_id": equipment_id,
                    "sensor": role,
                    "sensor_type": srow.get("sensor_type") or _stype(role),
                    **{c: "OK" for c in rule_cols},
                }
            hrs = srow.get("fault_hours")
            label = f"{float(hrs):.2f}h" if hrs is not None and float(hrs) > 0 else "FAULT"
            if rid in rule_cols:
                by_sensor[role][rid] = label
    if not by_sensor:
        return pd.DataFrame(columns=["equipment_id", "sensor", "sensor_type", *rule_cols])
    out = pd.DataFrame(list(by_sensor.values()))
    return out.sort_values(["sensor_type", "sensor"]).reset_index(drop=True)


def plant_gated_summary_tables(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], str, str]:
    """Fan-gated air-side + pump-gated plant leave-temp summary tables for analytics DOCX.

    Returns (fan_tables, pump_tables, fan_caption, pump_caption).
    """
    from app.rcx_plots import fan_mode_summary_bundle, pump_mode_summary_bundle

    fan_tables, fan_cap = fan_mode_summary_bundle(
        frames,
        role_map,
        role="discharge-air-temp",
        equipment_types=("AHU", "RTU"),
    )
    # Merge chw + hw leave into one pump-mode caption; prefer chw_supply_t then hw_supply_t
    pump_tables, pump_cap = pump_mode_summary_bundle(
        frames,
        role_map,
        role="chilled-water-supply-temp",
        equipment_types=("CHILLER", "CHW_PLANT", "AHU"),
    )
    if all(t.empty for t in pump_tables.values()):
        pump_tables, pump_cap = pump_mode_summary_bundle(
            frames,
            role_map,
            role="hot-water-supply-temp",
            equipment_types=("BOILER", "HW_PLANT", "AHU"),
        )
    return fan_tables, pump_tables, fan_cap, pump_cap


def _mask_hours_from_index(mask: pd.Series) -> float:
    """Accumulate hours under a boolean mask using actual timestamp deltas."""
    if mask is None or len(mask) == 0:
        return 0.0
    idx = mask.index
    if not isinstance(idx, pd.DatetimeIndex):
        return 0.0
    m = mask.reindex(idx).fillna(False).astype(bool)
    if len(idx) == 1:
        return 0.0
    # Duration for sample i is time until next sample; last uses median delta.
    deltas_h = idx.to_series().diff().dt.total_seconds().shift(-1) / 3600.0
    med = float(deltas_h.dropna().median()) if deltas_h.notna().any() else 0.0
    if not np.isfinite(med) or med < 0:
        med = 0.0
    deltas_h = deltas_h.fillna(med).clip(lower=0.0)
    return float((m.astype(float) * deltas_h).sum())


def economizer_weather_summary(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    weather: pd.DataFrame | None = None,
    damper_hi: float = 0.90,
    damper_winter_max: float = 0.25,
    db_min: float = 60.0,
    db_max: float = 72.0,
    dp_max: float = 60.0,
    cold_oat_f: float = 60.0,
    freeze_oat_f: float = 25.0,
) -> pd.DataFrame:
    """Per-equipment economizer opportunity / compliance / prohibited-cooling hours.

    Uses strict web dry-bulb + dewpoint (or Magnus from web RH) and actual timestamp
    deltas — never fixed-interval assumptions and never BAS OAT fallback.
    """
    from app.rules.cookbook_catalog import norm_cmd
    from app.rules.economizer_weather import (
        free_cool_opportunity_mask,
        mechanical_proof_mask,
        resolve_web_drybulb_dewpoint,
    )
    from app.rules.runner import merge_weather

    rows: list[dict[str, Any]] = []
    for eq_id, raw in frames.items():
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        if et not in {"AHU", "RTU", "CHILLER", "CHW_PLANT", "HEATPUMP", "HP"}:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        mapped = merge_weather(mapped, weather)
        db, dp, wx_src = resolve_web_drybulb_dewpoint(mapped)
        weather_ok = db is not None and dp is not None
        n = len(mapped)
        coverage = 0.0
        if weather_ok and n:
            coverage = float((db.notna() & dp.notna()).sum() / n)

        opp = (
            free_cool_opportunity_mask(db, dp, db_min=db_min, db_max=db_max, dp_max=dp_max)
            if weather_ok
            else pd.Series(False, index=mapped.index)
        )
        damper = None
        if "outside-air-damper" in mapped.columns:
            damper = norm_cmd(mapped["outside-air-damper"]).fillna(0)
        clg = None
        if "cooling-valve" in mapped.columns:
            clg = norm_cmd(mapped["cooling-valve"]).fillna(0)

        integrated_ok = pd.Series(False, index=mapped.index)
        integrated_bad = pd.Series(False, index=mapped.index)
        if damper is not None and clg is not None:
            mech_valve = clg > 0.01
            integrated_ok = opp & mech_valve & (damper >= float(damper_hi))
            integrated_bad = opp & mech_valve & (damper < float(damper_hi))

        run, proof = mechanical_proof_mask(mapped, equipment_type=et, equipment_id=eq_id)
        cold = (
            (db.notna() & (db < float(cold_oat_f)))
            if db is not None
            else pd.Series(False, index=mapped.index)
        )
        prohibited = cold & run if proof else pd.Series(False, index=mapped.index)

        winter = pd.Series(False, index=mapped.index)
        if damper is not None and db is not None:
            winter = db.notna() & (db < float(freeze_oat_f)) & (damper > float(damper_winter_max))

        rows.append(
            {
                "equipment_id": eq_id,
                "equipment_type": et,
                "weather_source": wx_src,
                "proof_source": proof or "",
                "weather_coverage": round(coverage, 4),
                "opportunity_hours": round(_mask_hours_from_index(opp), 3),
                "integrated_compliant_hours": round(_mask_hours_from_index(integrated_ok), 3),
                "integrated_noncompliant_hours": round(_mask_hours_from_index(integrated_bad), 3),
                "prohibited_mech_hours_below_60f": round(_mask_hours_from_index(prohibited), 3),
                "winter_economizing_hours_below_25f": round(_mask_hours_from_index(winter), 3),
            }
        )

    cols = [
        "equipment_id",
        "equipment_type",
        "weather_source",
        "proof_source",
        "weather_coverage",
        "opportunity_hours",
        "integrated_compliant_hours",
        "integrated_noncompliant_hours",
        "prohibited_mech_hours_below_60f",
        "winter_economizing_hours_below_25f",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows).sort_values(["equipment_type", "equipment_id"]).reset_index(drop=True)
