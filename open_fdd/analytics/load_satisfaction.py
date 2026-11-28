"""Cross-equipment building load satisfaction for CHW-NOLOAD-1."""
from __future__ import annotations

from typing import Any

import pandas as pd

from open_fdd.analytics.role_map import apply_role_map
from open_fdd.analytics.site_model import resolve_equipment_type


ZONE_SAT_COL = "zone_load_satisfied_status"
AHU_SAT_COL = "air_handling_unit_load_satisfied_status"


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def aggregate_load_satisfaction(
    frames: dict[str, pd.DataFrame],
    role_map: dict[str, Any] | None = None,
    *,
    comfort_low: float = 70.0,
    comfort_high: float = 75.0,
    sat_band: float = 2.0,
) -> dict[str, Any]:
    """Compute building-wide zone and AHU SAT satisfaction; inject onto chillers.

    Mutates chiller frames in place. Absent evidence is never treated as satisfied.
    """
    rm = role_map or {}
    lo = float(min(comfort_low, comfort_high))
    hi = float(max(comfort_low, comfort_high))
    band = abs(float(sat_band))

    zone_series: list[pd.Series] = []
    ahu_series: list[pd.Series] = []
    zone_ids: list[str] = []
    ahu_ids: list[str] = []

    for eq_id, raw in frames.items():
        et = resolve_equipment_type(eq_id, df=raw, role_map=rm)
        mapped = apply_role_map(raw, eq_id, rm)
        if et in {"VAV", "ZONE"} and "zone_air_temperature" in mapped.columns and mapped["zone_air_temperature"].notna().any():
            zt = _numeric(mapped["zone_air_temperature"])
            ok = zt.notna() & (zt >= lo) & (zt <= hi)
            # Only count samples with valid zone temp
            zone_series.append(ok.where(zt.notna()))
            zone_ids.append(eq_id)
        if et in {"AHU", "RTU"} and "discharge_air_temperature" in mapped.columns and "discharge_air_temperature_setpoint" in mapped.columns:
            discharge_air_temperature = _numeric(mapped["discharge_air_temperature"])
            sp = _numeric(mapped["discharge_air_temperature_setpoint"])
            both = discharge_air_temperature.notna() & sp.notna()
            ok = both & ((discharge_air_temperature - sp).abs() <= band)
            ahu_series.append(ok.where(both))
            ahu_ids.append(eq_id)

    # Union index across chillers + contributors so injection aligns
    chiller_ids = [
        eq_id
        for eq_id, raw in frames.items()
        if resolve_equipment_type(eq_id, df=raw, role_map=rm) in {"CHILLER", "CHW_PLANT"}
    ]

    meta = {
        "zone_equipment": zone_ids,
        "ahu_equipment": ahu_ids,
        "chiller_equipment": chiller_ids,
        "comfort_low": lo,
        "comfort_high": hi,
        "sat_band": band,
    }

    def _all_satisfied(parts: list[pd.Series], index: pd.Index) -> pd.Series | None:
        if not parts:
            return None
        aligned = [s.reindex(index) for s in parts]
        # Sample is satisfied only when every equipment with a value is True and ≥1 contributes
        mixed_air_temperature = pd.concat(aligned, axis=1)
        any_valid = mixed_air_temperature.notna().any(axis=1)
        all_true = mixed_air_temperature.fillna(True).all(axis=1) & any_valid
        return all_true

    for cid in chiller_ids:
        cdf = frames[cid]
        idx = cdf.index
        zone_mask = _all_satisfied(zone_series, idx)
        ahu_mask = _all_satisfied(ahu_series, idx)
        if zone_mask is not None:
            cdf[ZONE_SAT_COL] = zone_mask.astype(bool)
        elif ZONE_SAT_COL in cdf.columns:
            del cdf[ZONE_SAT_COL]
        if ahu_mask is not None:
            cdf[AHU_SAT_COL] = ahu_mask.astype(bool)
        elif AHU_SAT_COL in cdf.columns:
            del cdf[AHU_SAT_COL]
        cdf.attrs["load_satisfaction"] = {
            **meta,
            "zone_injected": zone_mask is not None,
            "ahu_injected": ahu_mask is not None,
        }

    return meta
