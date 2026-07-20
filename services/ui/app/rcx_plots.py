"""RCx multi-equipment plot collectors — prebuilt mechanical categories + generic picker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.role_map import apply_role_map
from app.site_model import resolve_equipment_type
from app.weather_psychrometrics import prefer_web_oat


@dataclass(frozen=True)
class RcxPreset:
    id: str
    title: str
    description: str
    role: str
    equipment_types: tuple[str, ...]
    chart: str  # "timeseries" | "box" | "scatter_oat" | "ranking" | "metering"
    filter_fan_on: bool = False
    y_role_alt: str | None = None  # for scatter: plant temp role
    dry_bulb_ref: bool = False  # CW scatter: also plot vs dry-bulb
    # UI family bucket — keeps AHU presets out of chiller/boiler lists
    family: str = "AHU / air"
    # timeseries extras: overlay a companion role (e.g. setpoint) per equipment
    overlay_role: str | None = None
    # timeseries pairs: plot role + return role + computed ΔT per equipment
    pair_return_role: str | None = None
    # timeseries: add this role's series as "<eq> · setpoint" traces when mapped
    overlay_role: str | None = None
    # timeseries: pair `role` (supply) with this return role + computed ΔT traces
    pair_return_role: str | None = None


# Mechanical families for the RCx Plots picker (order = UI order).
RCX_FAMILY_ORDER: tuple[str, ...] = (
    "Zones / VAV",
    "AHU / air",
    "Boiler / HW",
    "Chiller / CHW / tower",
    "Metering",
)


# Dropdown labels include chart type so the picker is self-documenting.
PRESETS: list[RcxPreset] = [
    RcxPreset(
        "zone_comfort_rank",
        "Zones — comfort fail ranking (occupied hours)",
        "Rank VAVs by % of occupied time outside Overview zone low/high band.",
        "zone-air-temp",
        ("VAV",),
        "ranking",
        family="Zones / VAV",
    ),
    RcxPreset(
        "zone_temps",
        "Zones — all space temps (timeseries)",
        "Every VAV/zone space temp on one chart.",
        "zone-air-temp",
        ("VAV",),
        "timeseries",
        family="Zones / VAV",
    ),
    RcxPreset(
        "vav_flows",
        "Zones — all VAV airflow (timeseries)",
        "Zone airflow across boxes.",
        "zone-airflow",
        ("VAV",),
        "timeseries",
        family="Zones / VAV",
    ),
    RcxPreset(
        "ahu_sat_reset_scatter",
        "AHU — SAT vs web dry-bulb (scatter)",
        "SAT / leave-air temp vs Open-Meteo dry bulb — look for SAT reset with outdoor air.",
        "discharge-air-temp",
        ("AHU",),
        "scatter_oat",
        family="AHU / air",
    ),
    RcxPreset(
        "ahu_dats",
        "AHU — all discharge air temps (timeseries)",
        "SAT / DAT for every AHU.",
        "discharge-air-temp",
        ("AHU",),
        "timeseries",
        family="AHU / air",
    ),
    RcxPreset(
        "ahu_mats",
        "AHU — all mixed air temps (timeseries)",
        "MAT across AHUs.",
        "mixed-air-temp",
        ("AHU",),
        "timeseries",
        family="AHU / air",
    ),
    RcxPreset(
        "ahu_rats",
        "AHU — all return air temps (timeseries)",
        "RAT across AHUs.",
        "return-air-temp",
        ("AHU",),
        "timeseries",
        family="AHU / air",
    ),
    RcxPreset(
        "ahu_dampers",
        "AHU — all OA dampers (timeseries)",
        "OA damper % across AHUs (preferred % companion for SAT/MAT/RAT views).",
        "outside-air-damper",
        ("AHU",),
        "timeseries",
        family="AHU / air",
    ),
    RcxPreset(
        "ahu_cooling_valves",
        "AHU — all cooling valves (timeseries)",
        "Cooling valve % across AHUs — use with SAT/MAT temp charts (not fan command).",
        "cooling-valve",
        ("AHU",),
        "timeseries",
        family="AHU / air",
    ),
    RcxPreset(
        "ahu_heating_valves",
        "AHU — all heating valves (timeseries)",
        "Heating valve % across AHUs — use with SAT/MAT temp charts (not fan command).",
        "heating-valve",
        ("AHU",),
        "timeseries",
        family="AHU / air",
    ),
    RcxPreset(
        "fan_speeds",
        "AHU — all fan speeds (timeseries)",
        "Fan command % across AHUs — pair with duct-static / FC1 pressure views, not SAT/MAT.",
        "fan-cmd",
        ("AHU",),
        "timeseries",
        family="AHU / air",
    ),
    RcxPreset(
        "duct_static_box",
        "AHU — duct static fan-on (box)",
        "Box plot of duct static while fan proven on — look for high fixed static (reset opportunity).",
        "duct-static-pressure",
        ("AHU",),
        "box",
        filter_fan_on=True,
        family="AHU / air",
    ),
    RcxPreset(
        "duct_static_ts",
        "AHU — duct static + setpoint (timeseries)",
        "Duct static pressure over time per AHU, with the mapped setpoint as a companion trace — "
        "flat setpoint + high static while fan runs means a reset opportunity.",
        "duct-static-pressure",
        ("AHU",),
        "timeseries",
        family="AHU / air",
        overlay_role="duct-static-pressure-sp",
    ),
    RcxPreset(
        "hw_reset_scatter",
        "Boiler / HW — leave temp vs web dry-bulb (scatter)",
        "HW supply / leave temp vs Open-Meteo dry bulb (boiler / HW plant reset).",
        "hot-water-supply-temp",
        ("BOILER",),
        "scatter_oat",
        family="Boiler / HW",
    ),
    RcxPreset(
        "chw_reset_scatter",
        "Chiller / CHW — leave temp vs web dry-bulb (scatter)",
        "CHW supply / leave temp vs Open-Meteo dry bulb (chiller plant reset).",
        "chilled-water-supply-temp",
        ("CHW_PLANT", "CHILLER"),
        "scatter_oat",
        family="Chiller / CHW / tower",
    ),
    RcxPreset(
        "cw_reset_scatter",
        "Tower / CW — leave temp vs wet-bulb + dry-bulb ref (scatter)",
        "CW supply vs wet-bulb (tower reset); dry-bulb shown as reference markers.",
        "condenser-water-supply-temp",
        ("CHW_PLANT", "CHILLER", "COOLING_TOWER"),
        "scatter_oat",
        y_role_alt="web-outside-air-wetbulb",
        dry_bulb_ref=True,
        family="Chiller / CHW / tower",
    ),
    RcxPreset(
        "chw_temps_ts",
        "Chiller / CHW — supply + return + ΔT (timeseries)",
        "CHW supply and return temps per chiller/plant with computed ΔT (return − supply) "
        "when both are mapped — low ΔT while pumps run is the classic low delta-T syndrome.",
        "chilled-water-supply-temp",
        ("CHW_PLANT", "CHILLER"),
        "timeseries",
        family="Chiller / CHW / tower",
        pair_return_role="chilled-water-return-temp",
    ),
    RcxPreset(
        "cw_temps_ts",
        "Tower / CW — supply + return + ΔT (timeseries)",
        "Condenser/tower water supply and return temps per device with computed ΔT "
        "(return − supply) when both are mapped — watch tower approach and range.",
        "condenser-water-supply-temp",
        ("CHW_PLANT", "CHILLER", "COOLING_TOWER"),
        "timeseries",
        family="Chiller / CHW / tower",
        pair_return_role="condenser-water-return-temp",
    ),
    RcxPreset(
        "meter_elec_cdd",
        "Metering — electric kWh/month vs CDD (scatter + stats)",
        "Integrate mapped kW (elec_power_kw / meter) to monthly kWh; stats + scatter vs cooling degree-days (65°F base).",
        "elec-power",
        ("METER", "CHILLER", "CHW_PLANT"),
        "metering",
        family="Metering",
    ),
    RcxPreset(
        "meter_gas_hdd",
        "Metering — gas/month vs HDD (scatter + stats)",
        "Integrate mapped gas rate (gas_flow) to monthly quantity; stats + scatter vs heating degree-days (65°F base).",
        "gas-flow",
        ("METER", "BOILER"),
        "metering",
        family="Metering",
    ),
]


# Full existing RCx catalog freeze — agents must not delete any of these without an
# explicit product decision + vibe19_agent_spec/docs/DASHBOARD_CONTRACT.md update.
# New presets may be added to PRESETS; promote them into this set when they become
# part of the supported dashboard.
REQUIRED_RCX_PRESET_IDS: frozenset[str] = frozenset(
    {
        "zone_comfort_rank",
        "zone_temps",
        "ahu_dats",
        "ahu_mats",
        "ahu_rats",
        "ahu_dampers",
        "duct_static_box",
        "ahu_sat_reset_scatter",
        "hw_reset_scatter",
        "chw_reset_scatter",
        "cw_reset_scatter",
        "vav_flows",
        "fan_speeds",
        "meter_elec_cdd",
        "meter_gas_hdd",
        "duct_static_ts",
        "chw_temps_ts",
        "cw_temps_ts",
    }
)


def _etype(eq_id: str, raw: pd.DataFrame, role_map: dict | None = None) -> str:
    return resolve_equipment_type(eq_id, df=raw, role_map=role_map)


def operating_mask(df: pd.DataFrame) -> tuple[pd.Series | None, str]:
    """Boolean mask when equipment looks running, plus proof role label.

    AHU / fans: ``fan_status`` then ``fan_cmd``.
    VAV / zones: ``zone_flow`` above a small activity threshold when fan roles absent.
    Returns ``(None, "")`` when no usable proof columns exist.
    """
    for role in ("fan-status", "fan-cmd"):
        if role in df.columns and df[role].notna().any():
            num = pd.to_numeric(df[role], errors="coerce")
            if num.notna().any():
                scaled = num.where(num <= 1.5, num / 100.0)
                return scaled.fillna(0) > 0.05, role
            return df[role].fillna(False).astype(bool), role
    if "zone-airflow" in df.columns and df["zone-airflow"].notna().any():
        flow = pd.to_numeric(df["zone-airflow"], errors="coerce")
        if flow.notna().any():
            # CFM: treat near-zero as off; threshold scales with typical max when available
            p95 = float(flow.quantile(0.95)) if flow.notna().sum() >= 5 else float(flow.max())
            thr = max(10.0, 0.05 * p95) if np.isfinite(p95) else 10.0
            return flow.fillna(0) > thr, "zone-airflow"
    return None, ""


def _fan_on(df: pd.DataFrame) -> pd.Series:
    """Legacy helper: operating mask, or all-True when no proof (keeps old filter_fan_on behavior)."""
    mask, _ = operating_mask(df)
    if mask is None:
        return pd.Series(True, index=df.index)
    return mask


def collect_role_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    role: str,
    equipment_types: tuple[str, ...] | None = None,
    equipment_ids: list[str] | None = None,
    filter_fan_on: bool = False,
    fan_mode: str = "all",
) -> dict[str, pd.Series]:
    """Map equipment_id → numeric series for a logical role.

    ``fan_mode``: ``all`` | ``on`` | ``off`` using :func:`operating_mask`.
    ``filter_fan_on=True`` is equivalent to ``fan_mode="on"`` (preset compatibility).
    """
    mode = "on" if filter_fan_on else str(fan_mode or "all").lower()
    if mode not in {"all", "on", "off"}:
        mode = "all"
    out: dict[str, pd.Series] = {}
    for eq_id, raw in frames.items():
        if equipment_ids is not None and eq_id not in equipment_ids:
            continue
        et = _etype(eq_id, raw, role_map)
        if equipment_types:
            allowed = {t.upper() for t in equipment_types}
            # Typed membership only — no id-substring fallback
            if et not in allowed:
                continue
        mapped = apply_role_map(raw, eq_id, role_map)
        if role not in mapped.columns or mapped[role].notna().sum() == 0:
            continue
        s = pd.to_numeric(mapped[role], errors="coerce")
        if mode in {"on", "off"}:
            mask, _proof = operating_mask(mapped)
            if mask is None:
                # Preset filter_fan_on legacy: no proof → keep all samples.
                # Explicit fan_mode slices: skip equipment without proof.
                if not (filter_fan_on and mode == "on"):
                    continue
            else:
                on = mask.reindex(s.index).fillna(False)
                s = s.where(on if mode == "on" else ~on)
        if s.notna().any():
            out[eq_id] = s
    return out


def series_summary_stats(series_map: dict[str, pd.Series], *, outlier_z: float = 2.5) -> pd.DataFrame:
    """Per-series summary + outlier sample counts (z-score vs cohort mean of means)."""
    rows: list[dict[str, Any]] = []
    means = []
    for eq_id, s in series_map.items():
        num = pd.to_numeric(s, errors="coerce").dropna()
        if num.empty:
            continue
        means.append(float(num.mean()))
        rows.append(
            {
                "equipment_id": eq_id,
                "n": int(len(num)),
                "mean": round(float(num.mean()), 3),
                "std": round(float(num.std(ddof=0)), 3) if len(num) > 1 else 0.0,
                "min": round(float(num.min()), 3),
                "p25": round(float(num.quantile(0.25)), 3),
                "p50": round(float(num.quantile(0.5)), 3),
                "p75": round(float(num.quantile(0.75)), 3),
                "max": round(float(num.max()), 3),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["equipment_id", "n", "mean", "std", "min", "p25", "p50", "p75", "max", "outlier"]
        )
    df = pd.DataFrame(rows)
    if len(means) >= 3:
        mu, sd = float(np.mean(means)), float(np.std(means))
        if sd > 1e-9:
            df["outlier"] = (df["mean"] - mu).abs() / sd >= outlier_z
        else:
            df["outlier"] = False
    else:
        df["outlier"] = False
    return df.sort_values("equipment_id")


def fan_mode_summary_bundle(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    role: str,
    equipment_types: tuple[str, ...] | None,
    outlier_z: float = 2.5,
) -> tuple[dict[str, pd.DataFrame], str]:
    """Build summary stats for all / on / off slices. Returns (tables_by_mode, proof_caption)."""
    proof_labels: set[str] = set()
    for eq_id, raw in frames.items():
        et = _etype(eq_id, raw, role_map)
        if equipment_types and et not in {t.upper() for t in equipment_types}:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        _mask, label = operating_mask(mapped)
        if label:
            proof_labels.add(label)
    tables: dict[str, pd.DataFrame] = {}
    for mode, key in (("all", "all"), ("on", "on"), ("off", "off")):
        series_map = collect_role_series(
            frames,
            role_map,
            role=role,
            equipment_types=equipment_types,
            fan_mode=mode,
        )
        tables[key] = series_summary_stats(series_map, outlier_z=outlier_z)
    caption = ""
    if proof_labels:
        caption = "Operating proof: " + ", ".join(sorted(proof_labels))
        if "zone-airflow" in proof_labels:
            caption += " (VAV airflow used when fan roles absent)"
    else:
        caption = "No fan_status / fan_cmd / zone_flow mapped — on/off slices empty"
    return tables, caption


def hydronic_operating_mask(df: pd.DataFrame) -> tuple[pd.Series | None, str]:
    """Pump / hydronic proof mask for plant leave-temp summaries."""
    from app.rules.operational_gate import resolve_hydronic_running

    mask, src = resolve_hydronic_running(df, command_fallback=True)
    if src.startswith("ungated"):
        return None, ""
    return mask, src


def collect_role_series_pump_mode(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    role: str,
    equipment_types: tuple[str, ...] | None = None,
    pump_mode: str = "all",
) -> dict[str, pd.Series]:
    """Like collect_role_series but filters with hydronic/pump proof (All / on / off)."""
    mode = str(pump_mode or "all").lower()
    if mode not in {"all", "on", "off"}:
        mode = "all"
    out: dict[str, pd.Series] = {}
    for eq_id, raw in frames.items():
        et = _etype(eq_id, raw, role_map)
        if equipment_types:
            allowed = {t.upper() for t in equipment_types}
            if et not in allowed:
                continue
        mapped = apply_role_map(raw, eq_id, role_map)
        if role not in mapped.columns or mapped[role].notna().sum() == 0:
            continue
        s = pd.to_numeric(mapped[role], errors="coerce")
        if mode in {"on", "off"}:
            mask, _proof = hydronic_operating_mask(mapped)
            if mask is None:
                continue
            on = mask.reindex(s.index).fillna(False)
            s = s.where(on if mode == "on" else ~on)
        if s.notna().any():
            out[eq_id] = s
    return out


def collect_paired_temp_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    supply_role: str,
    return_role: str,
    equipment_types: tuple[str, ...] | None = None,
    operating: str = "all",
    operating_kind: str = "pump",
) -> dict[str, pd.Series]:
    """Supply / return / ΔT series per equipment for plant temp timeseries.

    Keys are chart labels: ``"{eq} · supply"``, ``"{eq} · return"`` and — only
    when **both** roles are mapped with data — ``"{eq} · ΔT"`` (return − supply).
    ``operating="on"`` filters samples to pump (``operating_kind="pump"``) or
    fan proof; equipment without proof keeps all samples (informational chart).
    """
    mode = str(operating or "all").lower()
    out: dict[str, pd.Series] = {}
    for eq_id, raw in frames.items():
        et = _etype(eq_id, raw, role_map)
        if equipment_types:
            allowed = {t.upper() for t in equipment_types}
            if et not in allowed:
                continue
        mapped = apply_role_map(raw, eq_id, role_map)

        def _series(role: str) -> pd.Series | None:
            if role not in mapped.columns or mapped[role].notna().sum() == 0:
                return None
            return pd.to_numeric(mapped[role], errors="coerce")

        sup = _series(supply_role)
        ret = _series(return_role)
        if sup is None and ret is None:
            continue

        mask: pd.Series | None = None
        if mode == "on":
            if operating_kind == "pump":
                mask, _proof = hydronic_operating_mask(mapped)
            else:
                mask, _proof = operating_mask(mapped)

        def _gated(s: pd.Series) -> pd.Series:
            if mask is None:
                return s
            return s.where(mask.reindex(s.index).fillna(False))

        if sup is not None:
            g = _gated(sup)
            if g.notna().any():
                out[f"{eq_id} · supply"] = g
        if ret is not None:
            g = _gated(ret)
            if g.notna().any():
                out[f"{eq_id} · return"] = g
        if sup is not None and ret is not None:
            delta = _gated(ret - sup)
            if delta.notna().any():
                out[f"{eq_id} · ΔT"] = delta
    return out


def collect_status_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    equipment_types: tuple[str, ...] | None = None,
    equipment_ids: list[str] | None = None,
    kind: str = "fan",
) -> dict[str, pd.Series]:
    """Map equipment_id → 0/1 motor status series for chart overlays.

    ``kind="fan"`` uses :func:`operating_mask` (fan-status → fan-cmd → VAV airflow);
    ``kind="pump"`` uses :func:`hydronic_operating_mask`. Equipment without any
    proof signal is omitted.
    """
    out: dict[str, pd.Series] = {}
    for eq_id, raw in frames.items():
        if equipment_ids is not None and eq_id not in equipment_ids:
            continue
        et = _etype(eq_id, raw, role_map)
        if equipment_types:
            allowed = {t.upper() for t in equipment_types}
            if et not in allowed:
                continue
        mapped = apply_role_map(raw, eq_id, role_map)
        if kind == "pump":
            mask, _proof = hydronic_operating_mask(mapped)
        else:
            mask, _proof = operating_mask(mapped)
        if mask is None:
            continue
        out[eq_id] = mask.astype(bool).astype(int)
    return out


def pump_mode_summary_bundle(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    role: str,
    equipment_types: tuple[str, ...] | None,
    outlier_z: float = 2.5,
) -> tuple[dict[str, pd.DataFrame], str]:
    """Plant leave-temp summary stats for all / pump-on / pump-off."""
    proof_labels: set[str] = set()
    for eq_id, raw in frames.items():
        et = _etype(eq_id, raw, role_map)
        if equipment_types and et not in {t.upper() for t in equipment_types}:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        _mask, label = hydronic_operating_mask(mapped)
        if label:
            proof_labels.add(label)
    tables: dict[str, pd.DataFrame] = {}
    for mode in ("all", "on", "off"):
        series_map = collect_role_series_pump_mode(
            frames,
            role_map,
            role=role,
            equipment_types=equipment_types,
            pump_mode=mode,
        )
        tables[mode] = series_summary_stats(series_map, outlier_z=outlier_z)
    if proof_labels:
        caption = "Pump / hydronic proof: " + ", ".join(sorted(proof_labels))
    else:
        caption = "No pump proof roles mapped — pump-on/off slices empty"
    return tables, caption


def cohort_wants_fan_slices(equipment_types: tuple[str, ...] | None) -> bool:
    """AHU / VAV(/HP) air-side cohorts get All / on / off summary tabs."""
    if not equipment_types:
        return True  # generic "all types" — still offer slices when proof exists
    air = {"AHU", "VAV", "HP", "RTU"}
    return bool(air.intersection({t.upper() for t in equipment_types}))


def outlier_equipment_ids(stats: pd.DataFrame) -> set[str]:
    if stats is None or stats.empty or "outlier" not in stats.columns:
        return set()
    return set(stats.loc[stats["outlier"], "equipment_id"].astype(str))


def zone_comfort_fail_ranking(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    schedule,
    comfort_low_f: float,
    comfort_high_f: float,
    equipment_types: tuple[str, ...] = ("VAV",),
    outlier_z: float = 2.5,
) -> pd.DataFrame:
    """Rank zones by % of *occupied* samples outside Overview comfort band.

    Uses :func:`app.occupancy.occupied_mask` with the Overview occupancy calendar.
    """
    from app.occupancy import occupied_mask

    lo = float(min(comfort_low_f, comfort_high_f))
    hi = float(max(comfort_low_f, comfort_high_f))
    rows: list[dict[str, Any]] = []
    for eq_id, raw in frames.items():
        et = _etype(eq_id, raw, role_map)
        if equipment_types and et not in {t.upper() for t in equipment_types}:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        if "zone-air-temp" not in mapped.columns or mapped["zone-air-temp"].notna().sum() == 0:
            continue
        zone = pd.to_numeric(mapped["zone-air-temp"], errors="coerce")
        if not isinstance(zone.index, pd.DatetimeIndex):
            continue
        occ = occupied_mask(zone.index, schedule).reindex(zone.index).fillna(False)
        occ_vals = zone.where(occ).dropna()
        if occ_vals.empty:
            continue
        below = occ_vals < lo
        above = occ_vals > hi
        outside = below | above
        n_occ = int(len(occ_vals))
        n_out = int(outside.sum())
        pct = 100.0 * float(outside.mean())
        rows.append(
            {
                "equipment_id": eq_id,
                "pct_outside_comfort": round(pct, 2),
                "n_occupied": n_occ,
                "n_outside": n_out,
                "n_below": int(below.sum()),
                "n_above": int(above.sum()),
                "mean_zone_t": round(float(occ_vals.mean()), 2),
                "min_zone_t": round(float(occ_vals.min()), 2),
                "max_zone_t": round(float(occ_vals.max()), 2),
                "comfort_low_f": lo,
                "comfort_high_f": hi,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "equipment_id",
                "pct_outside_comfort",
                "n_occupied",
                "n_outside",
                "n_below",
                "n_above",
                "mean_zone_t",
                "min_zone_t",
                "max_zone_t",
                "comfort_low_f",
                "comfort_high_f",
                "outlier",
            ]
        )
    df = pd.DataFrame(rows)
    pcts = df["pct_outside_comfort"].astype(float).tolist()
    if len(pcts) >= 3:
        mu, sd = float(np.mean(pcts)), float(np.std(pcts))
        if sd > 1e-9:
            df["outlier"] = (df["pct_outside_comfort"] - mu).abs() / sd >= outlier_z
        else:
            df["outlier"] = False
    else:
        df["outlier"] = False
    return df.sort_values(["pct_outside_comfort", "equipment_id"], ascending=[False, True]).reset_index(
        drop=True
    )


def collect_oat_scatter(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    y_role: str,
    weather: pd.DataFrame | None,
    equipment_types: tuple[str, ...] | None = None,
    x_prefer: str = "web",  # web drybulb, or wetbulb
    operating_on: bool = False,
    operating_kind: str = "auto",  # auto | fan | pump
) -> pd.DataFrame:
    """Long dataframe: timestamp, equipment_id, oat, y [, dry_bulb] for scatter plots.

    When ``operating_on`` is True, keep only samples where fan (air-side) or pump
    (plant) proof is on. ``operating_kind="auto"`` picks pump for boiler/chiller/tower
    types and fan otherwise.
    """
    plantish = {"BOILER", "CHILLER", "CHW_PLANT", "COOLING_TOWER", "PUMP", "HW_PLANT"}
    rows: list[dict[str, Any]] = []
    for eq_id, raw in frames.items():
        et = _etype(eq_id, raw, role_map)
        if equipment_types and et not in {t.upper() for t in equipment_types}:
            # Typed membership only — no id-substring fallback
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        if y_role not in mapped.columns or mapped[y_role].notna().sum() == 0:
            continue
        dry = prefer_web_oat(mapped, weather, prefer_web=True)
        if x_prefer == "wetbulb" and weather is not None and "web-outside-air-wetbulb" in weather.columns:
            oat = pd.to_numeric(weather["web-outside-air-wetbulb"], errors="coerce").reindex(mapped.index)
        else:
            oat = dry
        if oat is None:
            continue
        y = pd.to_numeric(mapped[y_role], errors="coerce")
        if operating_on:
            kind = str(operating_kind or "auto").lower()
            if kind == "auto":
                kind = "pump" if et in plantish else "fan"
            if kind == "pump":
                mask, _ = hydronic_operating_mask(mapped)
            else:
                mask, _ = operating_mask(mapped)
            if mask is None:
                # No proof → drop series when filter requested (avoids messy "all data")
                continue
            y = y.where(mask.reindex(y.index).fillna(False))
        payload: dict[str, pd.Series] = {"oat": oat, "y": y}
        if dry is not None:
            payload["dry_bulb"] = pd.to_numeric(dry, errors="coerce")
        tmp = pd.DataFrame(payload).dropna(subset=["oat", "y"])
        # Vectorized row build (avoid iterrows)
        if tmp.empty:
            continue
        eq_ids = [eq_id] * len(tmp)
        chunk = pd.DataFrame(
            {
                "timestamp": tmp.index,
                "equipment_id": eq_ids,
                "oat": tmp["oat"].to_numpy(),
                "y": tmp["y"].to_numpy(),
            }
        )
        if "dry_bulb" in tmp.columns:
            chunk["dry_bulb"] = tmp["dry_bulb"].to_numpy()
        rows.append(chunk)
    if not rows:
        return pd.DataFrame(columns=["timestamp", "equipment_id", "oat", "y"])
    return pd.concat(rows, ignore_index=True)


def preset_by_id(preset_id: str) -> RcxPreset | None:
    for p in PRESETS:
        if p.id == preset_id:
            return p
    return None


def presets_for_family(family: str) -> list[RcxPreset]:
    """Presets in one mechanical family (UI picker scope)."""
    return [p for p in PRESETS if p.family == family]


def rcx_preset_coverage(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    weather: pd.DataFrame | None = None,
    outlier_z: float = 2.5,
    schedule=None,
    comfort_low_f: float = 70.0,
    comfort_high_f: float = 75.0,
) -> pd.DataFrame:
    """Diagnostics table: one row per RCx preset with series/row/outlier counts."""
    rows: list[dict[str, Any]] = []
    for preset in PRESETS:
        empty_reason = ""
        series_count = 0
        row_count = 0
        outlier_count = 0
        if preset.chart == "ranking":
            if schedule is None:
                from app.occupancy import OccupancySchedule

                schedule = OccupancySchedule()
            rank = zone_comfort_fail_ranking(
                frames,
                role_map,
                schedule=schedule,
                comfort_low_f=comfort_low_f,
                comfort_high_f=comfort_high_f,
                equipment_types=preset.equipment_types,
                outlier_z=outlier_z,
            )
            series_count = int(len(rank))
            row_count = int(rank["n_occupied"].sum()) if not rank.empty else 0
            outlier_count = int(rank["outlier"].sum()) if not rank.empty and "outlier" in rank.columns else 0
            if series_count == 0:
                empty_reason = "no mapped zone_t on VAV during occupied hours"
        elif preset.chart == "scatter_oat":
            x_pref = "wetbulb" if preset.id == "cw_reset_scatter" else "web"
            long_df = collect_oat_scatter(
                frames,
                role_map,
                y_role=preset.role,
                weather=weather,
                equipment_types=preset.equipment_types,
                x_prefer=x_pref,
            )
            row_count = int(len(long_df))
            series_count = int(long_df["equipment_id"].nunique()) if row_count and "equipment_id" in long_df.columns else 0
            if row_count == 0:
                empty_reason = f"no mapped {preset.role} and/or web OAT for {','.join(preset.equipment_types)}"
        elif preset.chart == "metering":
            from app.metering import build_meter_monthly_table

            kind = "electric" if "elec" in preset.id or preset.role.startswith("elec") else "gas"
            monthly_df, _stats, reason = build_meter_monthly_table(
                frames,
                role_map,
                kind=kind,  # type: ignore[arg-type]
                weather=weather,
                equipment_types=preset.equipment_types,
            )
            series_count = int(monthly_df["equipment_id"].nunique()) if not monthly_df.empty else 0
            row_count = int(len(monthly_df))
            if row_count == 0:
                empty_reason = reason or f"no metering data for {preset.role}"
        else:
            series_map = collect_role_series(
                frames,
                role_map,
                role=preset.role,
                equipment_types=preset.equipment_types,
                filter_fan_on=preset.filter_fan_on,
            )
            series_count = len(series_map)
            row_count = int(sum(int(s.notna().sum()) for s in series_map.values()))
            stats = series_summary_stats(series_map, outlier_z=outlier_z)
            outlier_count = int(stats["outlier"].sum()) if not stats.empty and "outlier" in stats.columns else 0
            if series_count == 0:
                empty_reason = f"no mapped {preset.role} for {','.join(preset.equipment_types)}"
                if preset.filter_fan_on:
                    empty_reason += " (fan-on filter)"
        rows.append(
            {
                "preset_id": preset.id,
                "title": preset.title,
                "chart_type": preset.chart,
                "role": preset.role,
                "series_count": series_count,
                "row_count": row_count,
                "outlier_count": outlier_count,
                "empty_reason": empty_reason,
            }
        )
    return pd.DataFrame(rows)
