"""Cross-equipment building load satisfaction for CHW-NOLOAD-1."""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.role_map import apply_role_map
from app.site_model import resolve_equipment_type


ZONE_SAT_COL = "building-zone-load-satisfied"
AHU_SAT_COL = "building-ahu-load-satisfied"


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def aggregate_load_satisfaction(
    frames: dict[str, pd.DataFrame],
    role_map: dict[str, Any] | None = None,
    *,
    comfort_low_f: float = 70.0,
    comfort_high_f: float = 75.0,
    sat_band_f: float = 2.0,
) -> dict[str, Any]:
    """Compute building-wide zone and AHU SAT satisfaction; inject onto chillers.

    Mutates chiller frames in place. Absent evidence is never treated as satisfied.
    """
    rm = role_map or {}
    lo = float(min(comfort_low_f, comfort_high_f))
    hi = float(max(comfort_low_f, comfort_high_f))
    band = abs(float(sat_band_f))

    zone_series: list[pd.Series] = []
    ahu_series: list[pd.Series] = []
    zone_ids: list[str] = []
    ahu_ids: list[str] = []

    for eq_id, raw in frames.items():
        et = resolve_equipment_type(eq_id, df=raw, role_map=rm)
        mapped = apply_role_map(raw, eq_id, rm)
        if et in {"VAV", "ZONE"} and "zone-air-temp" in mapped.columns and mapped["zone-air-temp"].notna().any():
            zt = _numeric(mapped["zone-air-temp"])
            ok = zt.notna() & (zt >= lo) & (zt <= hi)
            # Only count samples with valid zone temp
            zone_series.append(ok.where(zt.notna()))
            zone_ids.append(eq_id)
        if et in {"AHU", "RTU"} and "discharge-air-temp" in mapped.columns and "discharge-air-temp-sp" in mapped.columns:
            sat = _numeric(mapped["discharge-air-temp"])
            sp = _numeric(mapped["discharge-air-temp-sp"])
            both = sat.notna() & sp.notna()
            ok = both & ((sat - sp).abs() <= band)
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
        "comfort_low_f": lo,
        "comfort_high_f": hi,
        "sat_band_f": band,
    }

    def _all_satisfied(parts: list[pd.Series], index: pd.Index) -> pd.Series | None:
        if not parts:
            return None
        aligned = [s.reindex(index) for s in parts]
        # Sample is satisfied only when every equipment with a value is True and ≥1 contributes
        mat = pd.concat(aligned, axis=1)
        any_valid = mat.notna().any(axis=1)
        all_true = mat.fillna(True).all(axis=1) & any_valid
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
