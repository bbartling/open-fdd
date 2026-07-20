"""Weather-aware economizer / mechanical-cooling diagnostics.

Shared helpers for ECON-3, MECH-OAT-1, ECON-6, and related analytics.
Strict web-weather only — never silently substitute BAS OAT/RH.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.rules.cookbook_catalog import _f, _false, as_bool, norm_cmd


def resolve_web_drybulb_dewpoint(d: pd.DataFrame) -> tuple[pd.Series | None, pd.Series | None, str]:
    """Return (dry_bulb_f, dewpoint_f, source) from web weather columns only.

    Dewpoint comes from ``web-outside-air-dewpoint`` or is calculated from web DB+RH.
    """
    from app.weather_psychrometrics import dewpoint_f_from_db_rh

    if "web-outside-air-temp" not in d.columns or not d["web-outside-air-temp"].notna().any():
        return None, None, "missing_web_oat"
    db = pd.to_numeric(d["web-outside-air-temp"], errors="coerce")
    if "web-outside-air-dewpoint" in d.columns and d["web-outside-air-dewpoint"].notna().any():
        dp = pd.to_numeric(d["web-outside-air-dewpoint"], errors="coerce")
        return db, dp, "web_dewpoint"
    if "web-outside-air-humidity" in d.columns and d["web-outside-air-humidity"].notna().any():
        rh = pd.to_numeric(d["web-outside-air-humidity"], errors="coerce")
        dp = dewpoint_f_from_db_rh(db, rh)
        return db, dp, "web_db_rh_magnus"
    return db, None, "missing_web_dewpoint_and_rh"


def free_cool_opportunity_mask(
    db: pd.Series,
    dp: pd.Series,
    *,
    db_min: float = 60.0,
    db_max: float = 72.0,
    dp_max: float = 60.0,
) -> pd.Series:
    """60°F ≤ DB < 72°F AND DP < 60°F (inclusive low dry-bulb)."""
    return db.notna() & dp.notna() & (db >= db_min) & (db < db_max) & (dp < dp_max)


def mechanical_proof_mask(d: pd.DataFrame, equipment_type: str = "", equipment_id: str = "") -> tuple[pd.Series, str]:
    """Proven DX / chiller mechanical cooling — never cooling-valve alone."""
    from app.analytics import mech_cooling_run_mask

    run, kind = mech_cooling_run_mask(
        d,
        equipment_type=equipment_type or str(d.attrs.get("equipment_type", "")),
        equipment_id=equipment_id or str(d.attrs.get("equipment_id", "")),
    )
    if run is None:
        return _false(d.index), ""
    return run.reindex(d.index).fillna(False).astype(bool), kind


def econ3_compute(d: pd.DataFrame, p: dict, poll: float, wx_ok: bool = True) -> pd.Series:
    """Fault: mech cooling while free cooling available but OA damper not integrated-open.

    Weather: strict web dry-bulb + dewpoint (calculated from web RH if needed).
    Band: 60 ≤ DB < 72°F and DP < 60°F. Damper must be ≥ integrated threshold (default 90%).
    """
    del wx_ok  # web presence is resolved explicitly below
    if not {"outside-air-damper", "cooling-valve"}.issubset(d.columns):
        return _false(d.index)
    db, dp, src = resolve_web_drybulb_dewpoint(d)
    if db is None or dp is None:
        d.attrs["econ3_weather_source"] = src
        return _false(d.index)

    db_min = _f(p, "econ3_db_min", 60.0)
    db_max = _f(p, "econ3_db_max", 72.0)
    dp_max = _f(p, "econ3_dp_max", 60.0)
    damper_hi = _f(p, "econ3_damper_hi", 0.90)

    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    clg = norm_cmd(d["cooling-valve"]).fillna(0)
    opportunity = free_cool_opportunity_mask(db, dp, db_min=db_min, db_max=db_max, dp_max=dp_max)
    mech = clg > 0.01
    not_integrated = econ < damper_hi
    raw = opportunity & mech & not_integrated
    d.attrs["econ3_weather_source"] = src
    return raw.fillna(False)


def econ7_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: economizer-OK web weather with cooling demand, but OA damper not economizing.

    Economizer OK: web dew point < 60°F AND dry-bulb < 72°F (above a freeze-guard
    floor, default 35°F). Dewpoint comes from the web sensor or is calculated from
    web DB+RH. Cooling demand: cooling valve open OR proven DX/chiller cooling.
    Expected operation: economizer-only below 60°F DB (see MECH-OAT-1) and
    mech + integrated economizer in the 60–72°F band (see ECON-3).
    """
    del poll
    if "outside-air-damper" not in d.columns:
        return _false(d.index)
    db, dp, src = resolve_web_drybulb_dewpoint(d)
    d.attrs["econ7_weather_source"] = src
    if db is None or dp is None:
        return _false(d.index)

    db_min = _f(p, "econ7_db_min", 35.0)
    db_max = _f(p, "econ7_db_max", 72.0)
    dp_max = _f(p, "econ7_dp_max", 60.0)
    damper_min = _f(p, "econ7_damper_min", 0.50)

    econ_ok = free_cool_opportunity_mask(db, dp, db_min=db_min, db_max=db_max, dp_max=dp_max)

    demand = _false(d.index)
    has_demand_signal = False
    if "cooling-valve" in d.columns and d["cooling-valve"].notna().any():
        demand = demand | (norm_cmd(d["cooling-valve"]).fillna(0) > 0.05)
        has_demand_signal = True
    mech, kind = mechanical_proof_mask(d)
    d.attrs["econ7_proof"] = kind
    if kind:
        demand = demand | mech
        has_demand_signal = True
    if not has_demand_signal:
        d.attrs["econ7_skip"] = "missing_cooling_demand_signal"
        return _false(d.index)

    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return (econ_ok & demand & (econ < damper_min)).fillna(False)


def mech_oat1_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: proven mechanical cooling while web dry-bulb < 60°F."""
    del poll
    db, _dp, src = resolve_web_drybulb_dewpoint(d)
    d.attrs["mech_oat1_weather_source"] = src
    if db is None:
        return _false(d.index)
    oat_max = _f(p, "mech_oat_max_f", 60.0)
    run, kind = mechanical_proof_mask(d)
    d.attrs["mech_oat1_proof"] = kind
    if not kind:
        return _false(d.index)
    return (db.notna() & (db < oat_max) & run).fillna(False)


def econ6_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: OA damper above winter min-OA ceiling while web OAT < 25°F."""
    del poll
    if "outside-air-damper" not in d.columns:
        return _false(d.index)
    db, _dp, src = resolve_web_drybulb_dewpoint(d)
    d.attrs["econ6_weather_source"] = src
    if db is None:
        return _false(d.index)
    oat_max = _f(p, "econ6_oat_max_f", 25.0)
    damper_max = _f(p, "econ6_damper_max", 0.25)
    econ = norm_cmd(d["outside-air-damper"]).fillna(0)
    return (db.notna() & (db < oat_max) & (econ > damper_max)).fillna(False)


def chw_noload1_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Fault: chiller proven running while building load is satisfied.

    Satisfaction: ``building-zone-load-satisfied`` OR ``building-ahu-load-satisfied``
    (injected by load_satisfaction before batch run).
    """
    del poll
    run, kind = mechanical_proof_mask(d, equipment_type="CHILLER")
    d.attrs["chw_noload_proof"] = kind
    if not kind:
        return _false(d.index)

    zone_ok = None
    ahu_ok = None
    if "building-zone-load-satisfied" in d.columns and d["building-zone-load-satisfied"].notna().any():
        zone_ok = as_bool(d["building-zone-load-satisfied"])
    if "building-ahu-load-satisfied" in d.columns and d["building-ahu-load-satisfied"].notna().any():
        ahu_ok = as_bool(d["building-ahu-load-satisfied"])
    if zone_ok is None and ahu_ok is None:
        d.attrs["chw_noload_skip"] = "missing_load_satisfaction"
        return _false(d.index)

    satisfied = _false(d.index)
    if zone_ok is not None:
        satisfied = satisfied | zone_ok.reindex(d.index).fillna(False)
    if ahu_ok is not None:
        satisfied = satisfied | ahu_ok.reindex(d.index).fillna(False)
    return (run & satisfied).fillna(False)


def web_weather_missing_reasons(df: pd.DataFrame) -> list[str]:
    """Roles missing for strict web dry-bulb + dewpoint/RH resolution."""
    if "web-outside-air-temp" not in df.columns or not df["web-outside-air-temp"].notna().any():
        return ["web-outside-air-temp"]
    has_dp = "web-outside-air-dewpoint" in df.columns and df["web-outside-air-dewpoint"].notna().any()
    has_rh = "web-outside-air-humidity" in df.columns and df["web-outside-air-humidity"].notna().any()
    if not has_dp and not has_rh:
        return ["web-outside-air-dewpoint|web-outside-air-humidity"]
    return []
