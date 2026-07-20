"""Electrical / gas metering rollups for RCx — monthly energy + degree-day scatters.

Electric (kW demand) → integrate to monthly kWh, scatter vs CDD (base 65°F).
Natural gas (rate) → integrate to monthly quantity, scatter vs HDD (base 65°F).
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from app.role_map import apply_role_map
from app.site_model import resolve_equipment_type
from app.weather_psychrometrics import prefer_web_oat

MeterKind = Literal["electric", "gas"]

# Preferred cookbook roles (first hit wins on a frame).
ELEC_POWER_ROLES: tuple[str, ...] = (
    "elec-power",
    "building-power",
    "meter-power",
    "chiller-power",  # plant meters often reuse this column
)
GAS_RATE_ROLES: tuple[str, ...] = (
    "gas-flow",
    "gas-rate",
    "nat-gas-flow",
    "gas-therm-rate",
)

DD_BASE_F = 65.0


def interval_hours(index: pd.DatetimeIndex) -> pd.Series:
    """Hours represented by each sample (forward-fill first gap from median)."""
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return pd.Series(dtype=float)
    sec = pd.Series(index, index=index).diff().dt.total_seconds()
    med = float(sec.dropna().median()) if sec.notna().any() else 300.0
    if not np.isfinite(med) or med <= 0:
        med = 300.0
    sec = sec.fillna(med).clip(lower=0.0, upper=med * 20.0)
    return sec / 3600.0


def integrate_rate_to_monthly(
    rate: pd.Series,
    *,
    energy_col: str = "energy",
) -> pd.DataFrame:
    """Integrate a rate series (kW or gas units/h) to calendar-month totals."""
    num = pd.to_numeric(rate, errors="coerce")
    if num.dropna().empty or not isinstance(num.index, pd.DatetimeIndex):
        return pd.DataFrame(columns=["month", energy_col, "n_samples", "mean_rate", "max_rate"])
    hours = interval_hours(num.index).reindex(num.index)
    energy = (num * hours).fillna(0.0)
    # Month start labels
    g = energy.groupby(pd.Grouper(freq="MS"))
    rate_g = num.groupby(pd.Grouper(freq="MS"))
    out = pd.DataFrame(
        {
            energy_col: g.sum(),
            "n_samples": rate_g.count(),
            "mean_rate": rate_g.mean(),
            "max_rate": rate_g.max(),
        }
    ).dropna(how="all")
    out = out[out["n_samples"].fillna(0) > 0].copy()
    out["month"] = out.index
    return out.reset_index(drop=True)


def monthly_degree_days(
    oat: pd.Series,
    *,
    kind: Literal["cdd", "hdd"] = "cdd",
    base_f: float = DD_BASE_F,
) -> pd.Series:
    """Monthly CDD or HDD from dry-bulb (°F), using daily means then month sum."""
    num = pd.to_numeric(oat, errors="coerce")
    if num.dropna().empty or not isinstance(num.index, pd.DatetimeIndex):
        return pd.Series(dtype=float)
    daily = num.resample("D").mean().dropna()
    if kind == "cdd":
        dd = (daily - base_f).clip(lower=0.0)
    else:
        dd = (base_f - daily).clip(lower=0.0)
    monthly = dd.resample("MS").sum()
    monthly.name = kind
    return monthly


def series_basic_stats(s: pd.Series, *, label: str) -> dict[str, Any]:
    num = pd.to_numeric(s, errors="coerce").dropna()
    if num.empty:
        return {
            "metric": label,
            "n": 0,
            "total": None,
            "mean": None,
            "std": None,
            "min": None,
            "p50": None,
            "max": None,
        }
    return {
        "metric": label,
        "n": int(len(num)),
        "total": round(float(num.sum()), 3),
        "mean": round(float(num.mean()), 3),
        "std": round(float(num.std(ddof=0)), 3) if len(num) > 1 else 0.0,
        "min": round(float(num.min()), 3),
        "p50": round(float(num.quantile(0.5)), 3),
        "max": round(float(num.max()), 3),
    }


def pick_meter_role(mapped: pd.DataFrame, kind: MeterKind) -> tuple[str | None, pd.Series | None]:
    roles = ELEC_POWER_ROLES if kind == "electric" else GAS_RATE_ROLES
    for role in roles:
        if role in mapped.columns and mapped[role].notna().any():
            return role, pd.to_numeric(mapped[role], errors="coerce")
    return None, None


def collect_meter_frames(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    kind: MeterKind,
    equipment_types: tuple[str, ...] | None = ("METER",),
) -> dict[str, tuple[str, pd.Series]]:
    """equipment_id → (role_used, rate series).

    Includes METER-typed equipment and any frame that already has the meter role mapped
    (so building electric on a plant CSV still appears).
    """
    out: dict[str, tuple[str, pd.Series]] = {}
    allowed = {t.upper() for t in equipment_types} if equipment_types else None
    for eq_id, raw in frames.items():
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        mapped = apply_role_map(raw, eq_id, role_map)
        role, series = pick_meter_role(mapped, kind)
        if role is None or series is None:
            continue
        # Prefer typed METER; also accept when role is present on other types
        if allowed and et not in allowed and et not in {"METER", "UNKNOWN"}:
            # Still allow if role is an explicit elec/gas role (not only chiller_power fallback)
            if kind == "electric" and role == "chiller-power" and et not in {
                "METER",
                "CHILLER",
                "CHW_PLANT",
            }:
                continue
        out[eq_id] = (role, series)
    return out


def build_meter_monthly_table(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    kind: MeterKind,
    weather: pd.DataFrame | None,
    equipment_types: tuple[str, ...] | None = ("METER", "CHILLER", "CHW_PLANT", "BOILER"),
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Return (monthly long table, stats table, empty_reason).

    Monthly columns: month, equipment_id, role, energy, mean_rate, max_rate, cdd, hdd
    """
    meters = collect_meter_frames(frames, role_map, kind=kind, equipment_types=equipment_types)
    if not meters:
        label = "elec_power_kw / meter kW" if kind == "electric" else "gas_flow / gas rate"
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            f"no mapped {label} (equipment type METER or plant meter roles)",
        )

    # Degree days from web OAT (any frame + weather)
    sample_eq = next(iter(frames))
    sample_mapped = apply_role_map(frames[sample_eq], sample_eq, role_map)
    oat = prefer_web_oat(sample_mapped, weather, prefer_web=True)
    cdd = monthly_degree_days(oat, kind="cdd") if oat is not None else pd.Series(dtype=float)
    hdd = monthly_degree_days(oat, kind="hdd") if oat is not None else pd.Series(dtype=float)

    energy_col = "kwh" if kind == "electric" else "gas_qty"
    rows: list[dict[str, Any]] = []
    for eq_id, (role, series) in meters.items():
        monthly = integrate_rate_to_monthly(series, energy_col=energy_col)
        for _, r in monthly.iterrows():
            month = pd.Timestamp(r["month"])
            rows.append(
                {
                    "month": month,
                    "month_label": month.strftime("%Y-%m"),
                    "equipment_id": eq_id,
                    "role": role,
                    energy_col: float(r[energy_col]),
                    "mean_rate": float(r["mean_rate"]) if pd.notna(r["mean_rate"]) else None,
                    "max_rate": float(r["max_rate"]) if pd.notna(r["max_rate"]) else None,
                    "n_samples": int(r["n_samples"]),
                    "cdd": float(cdd.get(month, np.nan)) if len(cdd) else np.nan,
                    "hdd": float(hdd.get(month, np.nan)) if len(hdd) else np.nan,
                }
            )
    monthly_df = pd.DataFrame(rows)
    if monthly_df.empty:
        return monthly_df, pd.DataFrame(), "rate series present but no monthly totals"

    stats_rows = []
    for eq_id, part in monthly_df.groupby("equipment_id"):
        stats_rows.append(series_basic_stats(part[energy_col], label=f"{eq_id} · {energy_col}/mo"))
        if part["cdd"].notna().any():
            stats_rows.append(series_basic_stats(part["cdd"], label=f"{eq_id} · CDD/mo"))
        if part["hdd"].notna().any():
            stats_rows.append(series_basic_stats(part["hdd"], label=f"{eq_id} · HDD/mo"))
        if part["mean_rate"].notna().any():
            unit = "kW" if kind == "electric" else "gas rate"
            stats_rows.append(series_basic_stats(part["mean_rate"], label=f"{eq_id} · mean {unit}"))
    stats_df = pd.DataFrame(stats_rows)
    return monthly_df, stats_df, ""


def meter_scatter_frame(monthly_df: pd.DataFrame, *, kind: MeterKind) -> pd.DataFrame:
    """Long frame for Plotly: x=degree days, y=energy."""
    if monthly_df is None or monthly_df.empty:
        return pd.DataFrame()
    energy_col = "kwh" if kind == "electric" else "gas_qty"
    dd_col = "cdd" if kind == "electric" else "hdd"
    if energy_col not in monthly_df.columns or dd_col not in monthly_df.columns:
        return pd.DataFrame()
    out = monthly_df[["equipment_id", "month_label", energy_col, dd_col]].dropna()
    out = out.rename(columns={energy_col: "y", dd_col: "x"})
    return out
