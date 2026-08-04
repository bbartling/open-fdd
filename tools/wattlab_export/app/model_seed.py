"""Model-seed analytics for EnergyPlus calibration.

Infers schedules and OAT-binned operating signatures from historian frames so
vibe20 can calibrate a prototype IDF against observed behavior (even without a
full year of data).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.analytics import (
    _is_on,
    _oat_series,
    _preferred_motor_roles,
    dataset_time_span,
    mech_cooling_run_mask,
)
from app.data_loader import infer_poll_seconds
from app.role_map import apply_role_map
from app.site_model import resolve_equipment_type


def _fan_on_mask(df: pd.DataFrame) -> tuple[pd.Series | None, str]:
    """Prefer fan-status over fan-cmd."""
    for role in ("fan-status", "fan-cmd"):
        if role in df.columns and df[role].notna().any():
            return _is_on(df[role]), role
    return None, ""


def _median_hour_of_transitions(
    on: pd.Series,
    *,
    weekday_mask: pd.Series,
    rising: bool,
) -> float | None:
    """Median clock-hour (0–23) of ON→OFF or OFF→ON transitions on selected days."""
    if on is None or on.empty:
        return None
    idx = on.index
    if not isinstance(idx, pd.DatetimeIndex):
        return None
    on = on.fillna(False).astype(bool)
    prev = on.shift(1)
    prev = (prev.fillna(0) > 0).astype(bool)
    if rising:
        edges = on & ~prev
    else:
        edges = ~on & prev
    edges = edges & weekday_mask.reindex(on.index).fillna(False).astype(bool)
    if not bool(edges.any()):
        return None
    hours = idx[edges].hour.astype(float) + idx[edges].minute.astype(float) / 60.0
    return float(np.median(hours.to_numpy()))


def infer_schedules(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Infer per-equipment occupied start/stop from fan ON signals.

    Returns a tidy DataFrame and a JSON-ready dict keyed by equipment_id.
    """
    rows: list[dict[str, Any]] = []
    by_eq: dict[str, Any] = {}
    for eq_id, raw in frames.items():
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        on, signal = _fan_on_mask(mapped)
        if on is None:
            # Fall back to any preferred motor role (pumps for plants)
            preferred = _preferred_motor_roles(mapped)
            if not preferred:
                continue
            role, _kind = preferred[0]
            on = _is_on(mapped[role])
            signal = role
        poll = float(raw.attrs.get("poll_seconds") or infer_poll_seconds(raw))
        idx = mapped.index
        if not isinstance(idx, pd.DatetimeIndex):
            continue
        dow = idx.dayofweek  # Mon=0
        weekday = pd.Series(dow < 5, index=idx)
        weekend = ~weekday
        on_f = on.fillna(False).astype(bool)
        samples = int(len(on_f))
        on_samples = int(on_f.sum())
        always_on_frac = float(on_samples / samples) if samples else 0.0
        night = (idx.hour < 5) | (idx.hour >= 22)
        nights_running = float(on_f[night].mean()) if night.any() else 0.0
        weekends_running = float(on_f[weekend].mean()) if weekend.any() else 0.0

        wd_start = _median_hour_of_transitions(on_f, weekday_mask=weekday, rising=True)
        wd_stop = _median_hour_of_transitions(on_f, weekday_mask=weekday, rising=False)
        we_start = _median_hour_of_transitions(on_f, weekday_mask=weekend, rising=True)
        we_stop = _median_hour_of_transitions(on_f, weekday_mask=weekend, rising=False)

        # Fallback: first/last hour with >50% ON rate when edges are sparse
        def _fallback_hours(mask: pd.Series) -> tuple[float | None, float | None]:
            sub = on_f[mask]
            if sub.empty:
                return None, None
            by_h = sub.groupby(sub.index.hour).mean()
            active = by_h[by_h > 0.5]
            if active.empty:
                return None, None
            return float(active.index.min()), float(active.index.max() + 1)

        if wd_start is None or wd_stop is None:
            fs, fe = _fallback_hours(weekday)
            wd_start = wd_start if wd_start is not None else fs
            wd_stop = wd_stop if wd_stop is not None else fe
        if we_start is None or we_stop is None:
            fs, fe = _fallback_hours(weekend)
            we_start = we_start if we_start is not None else fs
            we_stop = we_stop if we_stop is not None else fe

        # Map signal role → historian column when role_map provides it
        eq_block = role_map.get(eq_id, {}) if isinstance(role_map, dict) else {}
        source_column = signal
        if isinstance(eq_block, dict):
            mapped_col = eq_block.get(signal)
            if isinstance(mapped_col, str) and mapped_col:
                source_column = mapped_col
        # Confidence proxy from duty-cycle balance (not literal edge-transition count):
        # mid-range always_on_frac + more ON samples → higher (capped).
        edge_density = min(1.0, (on_samples / samples) * (1.0 - abs(always_on_frac - 0.5) * 0.5)) if samples else 0.0
        confidence = round(float(min(1.0, max(0.05, 0.35 + 0.55 * edge_density))), 3)
        method = "fan_transition_median_hour"

        row = {
            "equipment_id": eq_id,
            "equipment_type": et,
            "signal": signal,
            "poll_seconds": poll,
            "samples": samples,
            "on_samples": on_samples,
            "always_on_fraction": round(always_on_frac, 4),
            "nights_running_fraction": round(nights_running, 4),
            "weekends_running_fraction": round(weekends_running, 4),
            "weekday_start_hour": None if wd_start is None else round(wd_start, 2),
            "weekday_stop_hour": None if wd_stop is None else round(wd_stop, 2),
            "weekend_start_hour": None if we_start is None else round(we_start, 2),
            "weekend_stop_hour": None if we_stop is None else round(we_stop, 2),
            "likely_always_on": always_on_frac >= 0.85,
            "source_equipment": eq_id,
            "source_role": signal,
            "source_column": source_column,
            "method": method,
            "sample_count": samples,
            "confidence": confidence,
            "editable": True,
        }
        rows.append(row)
        by_eq[eq_id] = {k: v for k, v in row.items() if k != "equipment_id"}

    cols = [
        "equipment_id",
        "equipment_type",
        "signal",
        "poll_seconds",
        "samples",
        "on_samples",
        "always_on_fraction",
        "nights_running_fraction",
        "weekends_running_fraction",
        "weekday_start_hour",
        "weekday_stop_hour",
        "weekend_start_hour",
        "weekend_stop_hour",
        "likely_always_on",
        "source_equipment",
        "source_role",
        "source_column",
        "method",
        "sample_count",
        "confidence",
        "editable",
    ]
    table = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
    if not table.empty:
        table = table.sort_values("equipment_id").reset_index(drop=True)

    inferred_parameters: list[dict[str, Any]] = []
    for row in rows:
        for param_name in (
            "weekday_start_hour",
            "weekday_stop_hour",
            "weekend_start_hour",
            "weekend_stop_hour",
        ):
            if row.get(param_name) is None:
                continue
            inferred_parameters.append(
                {
                    "parameter": param_name,
                    "value": row[param_name],
                    "source_equipment": row["source_equipment"],
                    "source_role": row["source_role"],
                    "source_column": row["source_column"],
                    "method": row["method"],
                    "sample_count": row["sample_count"],
                    "confidence": row["confidence"],
                    "editable": True,
                }
            )

    span = dataset_time_span(frames)
    payload = {
        "product": "OpenFDD Model Seed",
        "data_window": {
            "start_utc": None if span["start"] is None else str(span["start"]),
            "end_utc": None if span["end"] is None else str(span["end"]),
            "span_hours": span["span_hours"],
        },
        "equipment": by_eq,
        "inferred_parameters": inferred_parameters,
        "summary": {
            "equipment_count": len(by_eq),
            "likely_always_on_count": int(sum(1 for v in by_eq.values() if v.get("likely_always_on"))),
        },
    }
    return table, payload


def operating_signatures(
    frames: dict[str, pd.DataFrame],
    role_map: dict,
    *,
    weather: pd.DataFrame | None = None,
    bin_width_f: float = 5.0,
    prefer_web_oat: bool = True,
) -> pd.DataFrame:
    """OAT-binned ON-fraction for fans and mechanical cooling.

    Columns: equipment_id, kind, bin_start, bin_label, hours_available, hours_on, on_fraction.
    """
    rows: list[dict[str, Any]] = []
    bw = float(bin_width_f) or 5.0

    for eq_id, raw in frames.items():
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        poll = float(raw.attrs.get("poll_seconds") or infer_poll_seconds(raw))
        oat = _oat_series(mapped, weather, prefer_web=prefer_web_oat)
        if oat is None:
            continue
        oat_num = pd.to_numeric(oat, errors="coerce")
        valid = oat_num.notna()
        if not bool(valid.any()):
            continue
        clamped = oat_num.where(valid).clip(40, 110)
        bin_start = (np.floor(clamped.to_numpy(dtype=float) / bw) * bw).astype(float)

        masks: list[tuple[str, pd.Series]] = []
        fan_on, _sig = _fan_on_mask(mapped)
        if fan_on is not None:
            masks.append(("fan", fan_on.fillna(False).astype(bool)))
        cool_on, _kind = mech_cooling_run_mask(
            mapped, equipment_type=et, equipment_id=eq_id
        )
        if cool_on is not None and bool(cool_on.any()):
            masks.append(("mech_cooling", cool_on.fillna(False).astype(bool)))

        for kind, on in masks:
            tmp = pd.DataFrame(
                {
                    "bin_start": bin_start,
                    "valid": valid.to_numpy(),
                    "on": on.reindex(mapped.index).fillna(False).to_numpy(),
                },
                index=mapped.index,
            )
            tmp = tmp[tmp["valid"] & tmp["bin_start"].notna()]
            if tmp.empty:
                continue
            for b, g in tmp.groupby("bin_start"):
                b_i = int(b)
                hours_avail = float(len(g) * poll / 3600.0)
                hours_on = float(g["on"].sum() * poll / 3600.0)
                frac = (hours_on / hours_avail) if hours_avail > 0 else 0.0
                rows.append(
                    {
                        "equipment_id": eq_id,
                        "kind": kind,
                        "bin_start": b_i,
                        "bin_label": f"{b_i}–{b_i + int(bw)}",
                        "hours_available": round(hours_avail, 3),
                        "hours_on": round(hours_on, 3),
                        "on_fraction": round(frac, 4),
                    }
                )

    cols = [
        "equipment_id",
        "kind",
        "bin_start",
        "bin_label",
        "hours_available",
        "hours_on",
        "on_fraction",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    return (
        pd.DataFrame(rows, columns=cols)
        .sort_values(["kind", "equipment_id", "bin_start"])
        .reset_index(drop=True)
    )


def build_model_seed_dict(
    *,
    building_id: str,
    schedule_payload: dict[str, Any],
    signatures: pd.DataFrame | None = None,
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    utility_bills: list[dict[str, Any]] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """WattLab-shaped minimal-inputs dict with vibe19 provenance tags."""
    window = schedule_payload.get("data_window") or {}
    # Pick a representative AHU schedule for schedule hints
    equip = schedule_payload.get("equipment") or {}
    hint: dict[str, Any] = {}
    for eq_id, info in equip.items():
        et = str(info.get("equipment_type") or "").upper()
        if et == "AHU" or eq_id.upper().startswith("AHU"):
            hint = {
                "equipment_id": eq_id,
                "weekday_start_hour": info.get("weekday_start_hour"),
                "weekday_stop_hour": info.get("weekday_stop_hour"),
                "weekend_start_hour": info.get("weekend_start_hour"),
                "weekend_stop_hour": info.get("weekend_stop_hour"),
                "always_on_fraction": info.get("always_on_fraction"),
                "likely_always_on": info.get("likely_always_on"),
            }
            break
    if not hint and equip:
        eq_id, info = next(iter(equip.items()))
        hint = {
            "equipment_id": eq_id,
            "weekday_start_hour": info.get("weekday_start_hour"),
            "weekday_stop_hour": info.get("weekday_stop_hour"),
            "always_on_fraction": info.get("always_on_fraction"),
            "likely_always_on": info.get("likely_always_on"),
        }

    inferred = list(schedule_payload.get("inferred_parameters") or [])
    if not inferred and equip:
        # Rebuild provenance records from per-equipment schedule inference when present
        for eq_id, info in equip.items():
            if not isinstance(info, dict):
                continue
            for param_name in (
                "weekday_start_hour",
                "weekday_stop_hour",
                "weekend_start_hour",
                "weekend_stop_hour",
            ):
                if info.get(param_name) is None:
                    continue
                inferred.append(
                    {
                        "parameter": param_name,
                        "value": info.get(param_name),
                        "source_equipment": info.get("source_equipment") or eq_id,
                        "source_role": info.get("source_role") or info.get("signal") or "",
                        "source_column": info.get("source_column") or info.get("signal") or "",
                        "method": info.get("method") or "fan_transition_median_hour",
                        "sample_count": int(info.get("sample_count") or info.get("samples") or 0),
                        "confidence": float(info.get("confidence") or 0.5),
                        "editable": bool(info.get("editable", True)),
                    }
                )

    seed: dict[str, Any] = {
        "product": "OpenFDD Model Seed",
        "project_id": building_id or "unknown",
        "display_name": building_id or "OpenFDD building",
        "building_type": None,
        "floor_area_ft2": None,
        "floors": None,
        "city": city,
        "lat": lat,
        "lon": lon,
        "anonymized": True,
        "data_window": window,
        "schedule_hints": hint,
        "inferred_parameters": inferred,
        "vibe19_evidence": {
            "source": "vibe19",
            "schedule_equipment_count": len(equip),
            "signature_rows": 0 if signatures is None else int(len(signatures)),
        },
        "field_sources": {
            "project_id": {"source": "vibe19"},
            "data_window": {"source": "vibe19"},
            "schedule_hints": {"source": "vibe19"},
            "inferred_parameters": {"source": "vibe19"},
            "building_type": {"source": "user_required"},
            "floor_area_ft2": {"source": "user_required"},
            "floors": {"source": "user_required"},
            "city": {"source": "user_required" if not city else "user"},
            "lat": {"source": "user_required" if lat is None else "user"},
            "lon": {"source": "user_required" if lon is None else "user"},
            "utility_bills": {"source": "user_required"},
        },
    }
    if utility_bills:
        seed["utility_bills"] = utility_bills
        seed["field_sources"]["utility_bills"] = {"source": "user"}
    if extras:
        seed.update(extras)
    return seed


__all__ = [
    "infer_schedules",
    "operating_signatures",
    "build_model_seed_dict",
]
