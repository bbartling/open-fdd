"""SV-RATE — context-aware sensor rate-of-change validation.

Differs from SV-SPIKE (one-sample jump), SV-RANGE, SV-FLATLINE, and PID-HUNT-1.
Thresholds depend on quantity, location, and operating state (steady vs transient).
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from app.rules.base import confirm_fault
from app.rules.sensor_rate_profiles import (
    IN_WC_TO_PA,
    PSI_TO_KPA,
    ROLE_TO_PROFILE,
    SensorRateProfile,
    apply_profile_overrides,
    resolve_profile,
)

OperatingState = Literal[
    "OFF",
    "STARTUP_TRANSIENT",
    "SHUTDOWN_TRANSIENT",
    "RUNNING_STEADY",
    "UNKNOWN_STATE",
]

IntervalClass = Literal["STEADY", "TRANSIENT", "OFF", "UNKNOWN_STATE", "INSUFFICIENT_DATA"]

RATEABLE_ROLES: tuple[str, ...] = tuple(ROLE_TO_PROFILE.keys())
MAX_GAP_HOURS_DEFAULT = 2.0
# Noise deadband profiles (e.g. CO2 100 ppm) are authored for ~5-minute samples.
DEADBAND_REFERENCE_HOURS = 5.0 / 60.0


def _norm_cmd(s: pd.Series) -> pd.Series:
    """Element-wise 0–100 → 0–1 (same convention as cookbook_catalog.norm_cmd)."""
    x = pd.to_numeric(s, errors="coerce")
    return x.where(x <= 1.0, x / 100.0)


def _as_bool(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return (x.fillna(0) > 0.5) | (s.astype(str).str.lower().isin(["true", "on", "1"]))


def _false(index) -> pd.Series:
    return pd.Series(False, index=index)


def _ensure_dt_index(d: pd.DataFrame) -> pd.DataFrame:
    if isinstance(d.index, pd.DatetimeIndex):
        return d
    if "timestamp" in d.columns:
        out = d.copy()
        out.index = pd.DatetimeIndex(pd.to_datetime(out["timestamp"], utc=True, errors="coerce"))
        return out
    raise ValueError("SV-RATE requires a DatetimeIndex or timestamp column")


def _mark_forward_windows(idx: pd.DatetimeIndex, event_mask: pd.Series, win: pd.Timedelta) -> np.ndarray:
    """True where sample time is within [event, event+win] for any event. O(n log m)."""
    n = len(idx)
    out = np.zeros(n, dtype=bool)
    if n == 0 or not bool(event_mask.any()):
        return out
    times = np.asarray(idx.asi8)
    win_ns = int(win.total_seconds() * 1e9)
    event_times = np.sort(times[event_mask.reindex(idx).fillna(False).to_numpy()])
    if len(event_times) == 0:
        return out
    # sample t is covered iff some event e with e <= t <= e+win  ⟺  e in [t-win, t]
    left = np.searchsorted(event_times, times - win_ns, side="left")
    right = np.searchsorted(event_times, times, side="right")
    return right > left


def detect_operating_state(
    d: pd.DataFrame,
    *,
    transition_window_minutes: int = 20,
) -> tuple[pd.Series, dict[str, Any]]:
    """Classify each sample. Missing proofs → UNKNOWN_STATE + reduced confidence."""
    idx = d.index
    meta: dict[str, Any] = {"confidence": "high", "transition_count": 0, "signals_used": []}
    on = pd.Series(False, index=idx)
    used = False

    if "fan-status" in d.columns and d["fan-status"].notna().any():
        on = on | _as_bool(d["fan-status"])
        meta["signals_used"].append("fan-status")
        used = True
    elif "fan-cmd" in d.columns and d["fan-cmd"].notna().any():
        on = on | (_norm_cmd(d["fan-cmd"]).fillna(0) > 0.05)
        meta["signals_used"].append("fan-cmd")
        used = True

    for role in ("pump-status", "chw-pump-status", "hw-pump-status", "chiller-status", "compressor-status"):
        if role in d.columns and d[role].notna().any():
            on = on | _as_bool(d[role])
            meta["signals_used"].append(role)
            used = True

    for role in ("chw-pump-cmd", "hw-pump-cmd"):
        if role in d.columns and d[role].notna().any():
            on = on | (_norm_cmd(d[role]).fillna(0) > 0.05)
            meta["signals_used"].append(role)
            used = True

    cmd_change = pd.Series(False, index=idx)
    for role in ("cooling-valve", "heating-valve", "outside-air-damper", "reheat-valve"):
        if role not in d.columns:
            continue
        c = _norm_cmd(d[role]).fillna(0)
        cmd_change = cmd_change | (c.diff().abs() > 0.05).fillna(False)
        meta["signals_used"].append(role)

    if not used:
        meta["confidence"] = "reduced"
        return pd.Series("UNKNOWN_STATE", index=idx, dtype=object), meta

    on_b = on.fillna(False).astype(bool)
    started = on_b & ~on_b.shift(1, fill_value=False)
    stopped = (~on_b) & on_b.shift(1, fill_value=False)
    meta["transition_count"] = int(started.sum() + stopped.sum() + int(cmd_change.sum()))

    state_arr = np.where(on_b.to_numpy(), "RUNNING_STEADY", "OFF").astype(object)

    if isinstance(idx, pd.DatetimeIndex) and len(idx):
        win = pd.Timedelta(minutes=max(1, transition_window_minutes))
        start_win = _mark_forward_windows(idx, started, win)
        stop_win = _mark_forward_windows(idx, stopped, win)
        cmd_win = _mark_forward_windows(idx, cmd_change, win)
        state_arr = np.where(start_win, "STARTUP_TRANSIENT", state_arr)
        state_arr = np.where(stop_win, "SHUTDOWN_TRANSIENT", state_arr)
        # Valve/damper moves only elevate RUNNING_STEADY → transient
        steady = state_arr == "RUNNING_STEADY"
        state_arr = np.where(cmd_win & steady, "STARTUP_TRANSIENT", state_arr)

    return pd.Series(state_arr, index=idx, dtype=object), meta


def _interval_class(state: str) -> IntervalClass:
    if state == "OFF":
        return "OFF"
    if state in {"STARTUP_TRANSIENT", "SHUTDOWN_TRANSIENT"}:
        return "TRANSIENT"
    if state == "RUNNING_STEADY":
        return "STEADY"
    if state == "UNKNOWN_STATE":
        return "UNKNOWN_STATE"
    return "INSUFFICIENT_DATA"


def compute_rates(
    values: pd.Series,
    *,
    max_gap_hours: float = MAX_GAP_HOURS_DEFAULT,
    extra_window_minutes: int | None = None,
) -> dict[str, pd.Series]:
    """Point-to-point and approx windowed absolute rates (per hour)."""
    s = pd.to_numeric(values, errors="coerce")
    if not isinstance(s.index, pd.DatetimeIndex):
        raise ValueError("values index must be DatetimeIndex")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    dt_h = s.index.to_series().diff().dt.total_seconds() / 3600.0
    dt_h = dt_h.where((dt_h > 0) & (dt_h <= max_gap_hours))
    rate = s.diff().abs() / dt_h

    def window_rate(minutes: int) -> pd.Series:
        shifted = s.reindex(
            s.index - pd.Timedelta(minutes=minutes),
            method="nearest",
            tolerance=pd.Timedelta(minutes=max(2, minutes // 2)),
        )
        shifted.index = s.index
        span_h = minutes / 60.0
        return (s - shifted).abs() / span_h

    dt_vals = dt_h.to_numpy(dtype=float)
    finite = dt_vals[np.isfinite(dt_vals)]
    n_med = float(np.median(finite)) if len(finite) else 300.0 / 3600.0
    sample_s = n_med * 3600 if n_med > 0 else 300.0
    n = max(3, int(round(15 * 60 / max(sample_s, 60))))
    inst = rate.copy()
    robust = inst.rolling(n, min_periods=3).median()

    out = {
        "instantaneous_rate": rate.reindex(values.index),
        "rate_5min": window_rate(5).reindex(values.index),
        "rate_15min": window_rate(15).reindex(values.index),
        "rate_60min": window_rate(60).reindex(values.index),
        "robust_slope_15min": robust.reindex(values.index),
        "dt_hours": dt_h.reindex(values.index),
    }
    if extra_window_minutes is not None and int(extra_window_minutes) not in {5, 15, 60}:
        m = max(1, int(extra_window_minutes))
        out[f"rate_{m}min"] = window_rate(m).reindex(values.index)
    return out


def _thresholds_for_state(profile: SensorRateProfile, state: str) -> tuple[float, float, str]:
    cls = _interval_class(state)
    if cls == "TRANSIENT":
        return profile.transient_warning_per_hour, profile.transient_fault_per_hour, "transient"
    if cls == "OFF":
        return profile.steady_warning_per_hour, profile.steady_fault_per_hour, "off_steady"
    if cls == "UNKNOWN_STATE":
        return profile.steady_warning_per_hour, profile.steady_fault_per_hour, "unknown_steady"
    return profile.steady_warning_per_hour, profile.steady_fault_per_hour, "steady"


def evaluate_point(
    values: pd.Series,
    state: pd.Series,
    profile: SensorRateProfile,
    *,
    design_flow: float | None = None,
    sensor_span: float | None = None,
    max_gap_hours: float = MAX_GAP_HOURS_DEFAULT,
    poll_seconds: float = 300.0,
) -> dict[str, Any]:
    idx = values.index
    empty_mask = _false(idx)

    if profile.normalize_by == "design_flow":
        scale = design_flow if design_flow and design_flow > 0 else sensor_span
        if not scale or scale <= 0:
            return {
                "status_hint": "INSUFFICIENT_DATA",
                "fault_mask": empty_mask,
                "diagnostic_message": (
                    f"Profile {profile.profile_id} requires design flow or sensor span; neither available."
                ),
                "confidence": "skipped_missing_scale",
                "resolved_profile_id": profile.profile_id,
            }
        series = pd.to_numeric(values, errors="coerce") / float(scale)
    else:
        series = pd.to_numeric(values, errors="coerce")
        # Demo packages store imperial engineering units; profiles use SI canonical rates.
        if profile.quantity == "air_pressure":
            series = series * IN_WC_TO_PA
        elif profile.quantity == "hydronic_pressure":
            series = series * PSI_TO_KPA
        if profile.normalize_by == "sensor_span" and sensor_span and float(sensor_span) > 0:
            series = series / float(sensor_span)

    ext_min = int(profile.extreme_interval_minutes or 5) if profile.extreme_interval_change is not None else None

    try:
        rates = compute_rates(series, max_gap_hours=max_gap_hours, extra_window_minutes=ext_min)
    except ValueError as exc:
        return {
            "status_hint": "INSUFFICIENT_DATA",
            "fault_mask": empty_mask,
            "diagnostic_message": str(exc),
            "resolved_profile_id": profile.profile_id,
        }

    # Dt-aware noise deadband (authored for ~5-min samples); never hide warning-rate motion.
    if profile.noise_deadband > 0:
        series_n = series.copy()
        prev = series_n.shift(1)
        step = (series_n - prev).abs()
        dt_h = rates["dt_hours"].reindex(series_n.index)
        scale = (dt_h / DEADBAND_REFERENCE_HOURS).clip(lower=0.2, upper=5.0)
        scaled_db = float(profile.noise_deadband) * scale
        implied = step / dt_h
        suppress = (step <= scaled_db) & (implied.isna() | (implied < profile.steady_warning_per_hour))
        series_n = series_n.where(~suppress.fillna(False), prev)
        try:
            rates = compute_rates(series_n, max_gap_hours=max_gap_hours, extra_window_minutes=ext_min)
        except ValueError:
            pass
        series = series_n

    primary = rates["robust_slope_15min"].fillna(rates["rate_15min"]).fillna(rates["instantaneous_rate"])

    st = state.reindex(idx).fillna("UNKNOWN_STATE").astype(str)
    is_trans = st.isin(["STARTUP_TRANSIENT", "SHUTDOWN_TRANSIENT"])
    fault_thr = pd.Series(profile.steady_fault_per_hour, index=idx)
    warn_thr = pd.Series(profile.steady_warning_per_hour, index=idx)
    fault_thr = fault_thr.where(~is_trans, profile.transient_fault_per_hour)
    warn_thr = warn_thr.where(~is_trans, profile.transient_warning_per_hour)
    thr_label = pd.Series("steady", index=idx, dtype=object).where(~is_trans, "transient")

    warn = primary.notna() & (primary >= warn_thr)
    fault = primary.notna() & (primary >= fault_thr)

    extreme = _false(idx)
    if profile.extreme_interval_change is not None and ext_min is not None:
        hrs = ext_min / 60.0
        rate_key = f"rate_{ext_min}min" if f"rate_{ext_min}min" in rates else "rate_5min"
        if ext_min == 5:
            rate_key = "rate_5min"
        elif ext_min == 15:
            rate_key = "rate_15min"
        elif ext_min == 60:
            rate_key = "rate_60min"
        net = rates[rate_key] * hrs
        extreme = net.fillna(0) >= float(profile.extreme_interval_change)

    persist_s = max(60.0, float(profile.persistence_minutes) * 60.0)
    confirmed = confirm_fault(fault.fillna(False), poll_seconds=poll_seconds, confirm_seconds=persist_s)
    confirmed = confirmed | extreme.fillna(False)

    if int(fault.fillna(False).sum()) < 2 and not bool(extreme.any()):
        confirmed = empty_mask

    max_rate = float(primary.max()) if primary.notna().any() else float("nan")
    max_15 = float(rates["rate_15min"].max()) if rates["rate_15min"].notna().any() else float("nan")
    max_60 = float(rates["rate_60min"].max()) if rates["rate_60min"].notna().any() else float("nan")

    viol = confirmed.reindex(idx).fillna(False)
    dt_h = rates["dt_hours"].reindex(idx)
    # Sum real intervals for violations; fall back to poll when dt missing (first sample)
    viol_hours = float(dt_h.where(viol, 0.0).fillna(0.0).sum())
    if viol.any() and viol_hours <= 0:
        viol_hours = float(viol.sum()) * poll_seconds / 3600.0
    viol_minutes = viol_hours * 60.0

    longest = 0.0
    if viol.any():
        groups = (viol != viol.shift()).cumsum()
        for _, g in viol.groupby(groups):
            if not bool(g.iloc[0]):
                continue
            g_hours = float(dt_h.reindex(g.index).fillna(poll_seconds / 3600.0).sum())
            longest = max(longest, g_hours * 60.0)

    mode_state = str(st.mode().iloc[0]) if len(st) else "UNKNOWN_STATE"
    _, fault_thr_s, thr_s = _thresholds_for_state(profile, mode_state)
    unit = profile.canonical_unit
    msg = (
        f"{profile.location.replace('_', ' ').title()} sensor "
        f"(profile `{profile.profile_id}`) changed at a maximum robust rate of "
        f"{max_rate:.2f} {unit} during predominantly {mode_state} operation, "
        f"{'exceeding' if bool(viol.any()) else 'below'} the configured "
        f"{fault_thr_s:.2f} {unit} {thr_s} fault threshold"
        + (f" for {viol_minutes:.0f} minutes." if bool(viol.any()) else ".")
    )

    first_ts = last_ts = None
    if viol.any():
        nz = viol.to_numpy().nonzero()[0]
        first_ts = str(viol.index[nz[0]])
        last_ts = str(viol.index[nz[-1]])

    return {
        "fault_mask": confirmed.reindex(idx).fillna(False),
        "warning_mask": warn.reindex(idx).fillna(False),
        "resolved_profile_id": profile.profile_id,
        "quantity": profile.quantity,
        "canonical_unit": unit,
        "operating_state_mode": mode_state,
        "threshold_used": fault_thr_s,
        "threshold_type": thr_s,
        "maximum_rate": max_rate,
        "maximum_15_min_change": max_15,
        "maximum_60_min_change": max_60,
        "violation_count": int(viol.sum()),
        "violation_minutes": viol_minutes,
        "longest_violation_minutes": longest,
        "first_violation_timestamp": first_ts,
        "last_violation_timestamp": last_ts,
        "sample_count": int(series.notna().sum()),
        "data_coverage": float(series.notna().mean()) if len(series) else 0.0,
        "diagnostic_message": msg,
        "primary_rate": primary,
        "threshold_series": fault_thr,
        "threshold_label_series": thr_label,
        "dt_hours": dt_h,
    }


def sv_rate_compute(d: pd.DataFrame, p: dict, poll: float) -> pd.Series:
    """Cookbook compute: OR of fault masks across rateable sensors present."""
    try:
        d2 = _ensure_dt_index(d)
    except ValueError:
        return _false(d.index)

    idx = d2.index
    mask = _false(idx)
    window = int(float(p.get("transition_window_min", 20)))
    state, state_meta = detect_operating_state(d2, transition_window_minutes=window)
    max_gap = float(p.get("max_gap_hours", MAX_GAP_HOURS_DEFAULT))
    design_flow = p.get("design_flow")
    sensor_span = p.get("sensor_span")
    override = p.get("profile_override") or None

    point_evidence: list[dict[str, Any]] = []
    for role in RATEABLE_ROLES:
        if role not in d2.columns or not d2[role].notna().any():
            continue
        prof, src = resolve_profile(
            role=role,
            override_id=str(override) if override else None,
            equipment_type=str(d2.attrs.get("equipment_type", "")),
        )
        if prof is None:
            continue
        ov: dict[str, float] = {}
        prefix = f"svrate__{prof.profile_id}__"
        for k, v in p.items():
            if k.startswith(prefix):
                try:
                    ov[k[len(prefix) :]] = float(v)
                except (TypeError, ValueError):
                    pass
        if "persistence_min" in p:
            ov["persistence_minutes"] = float(p["persistence_min"])
        if "transition_window_min" in p:
            ov["transition_window_minutes"] = float(p["transition_window_min"])
        override_error = None
        try:
            prof = apply_profile_overrides(prof, ov or None)
        except ValueError as exc:
            override_error = str(exc)

        ev = evaluate_point(
            d2[role],
            state,
            prof,
            design_flow=float(design_flow) if design_flow not in (None, "") else None,
            sensor_span=float(sensor_span) if sensor_span not in (None, "") else None,
            max_gap_hours=max_gap,
            poll_seconds=poll,
        )
        ev["role"] = role
        ev["profile_resolution_source"] = src
        ev["confidence"] = state_meta.get("confidence", "high")
        if override_error:
            ev["override_error"] = override_error
        dt_h = ev.pop("dt_hours", None)
        fm = ev.get("fault_mask")
        if isinstance(fm, pd.Series) and isinstance(dt_h, pd.Series):
            fault_hours_raw = float(dt_h.where(fm.reindex(dt_h.index).fillna(False), 0.0).fillna(0.0).sum())
        elif isinstance(fm, pd.Series):
            fault_hours_raw = float(fm.sum()) * poll / 3600.0
        else:
            fault_hours_raw = 0.0
        slim = {
            k: v
            for k, v in ev.items()
            if k not in {"fault_mask", "warning_mask", "primary_rate", "threshold_series", "threshold_label_series"}
        }
        slim["fault_hours_raw"] = fault_hours_raw
        point_evidence.append(slim)
        if isinstance(fm, pd.Series):
            mask = mask | fm.reindex(idx).fillna(False)

    d.attrs["sv_rate_evidence"] = point_evidence
    d.attrs["sv_rate_state_meta"] = state_meta
    return mask.reindex(d.index).fillna(False) if len(mask) == len(d.index) else mask


sv_slew_compute = sv_rate_compute
