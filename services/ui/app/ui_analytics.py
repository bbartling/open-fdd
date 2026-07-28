"""Streamlit helpers for Milestone C central analytics APIs.

Builds inline payloads from frames/role_map and calls ``central_client.analytics_post``.
Does **not** silently fall back to pandas — callers decide on error dicts.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from app import central_client
from app.role_map import apply_role_map
from app.site_model import normalize_equipment_type, resolve_equipment_type

FAN_ROLES: tuple[str, ...] = ("fan-status", "fan-cmd")
ECON_AIR_TYPES = frozenset({"AHU", "RTU"})


def _is_on(series: pd.Series) -> pd.Series:
    """True when a command/status indicates the motor is running."""
    num = pd.to_numeric(series, errors="coerce")
    if num.notna().any():
        scaled = num.where(num <= 1.5, num / 100.0)
        return scaled.fillna(0) > 0.05
    return series.fillna(False).astype(bool)


def _ts_iso(ts: Any) -> str | None:
    """Serialize a timestamp to UTC ISO-8601 for central DateTime<Utc>."""
    try:
        t = pd.Timestamp(ts)
    except Exception:
        return None
    if pd.isna(t):
        return None
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.isoformat().replace("+00:00", "Z")


def prefer_central_analytics() -> bool:
    """True when env forces central or central health responds ok."""
    flag = (os.environ.get("OPENFDD_ANALYTICS_CENTRAL") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    return central_client.health_ok()


def provenance_caption(envelope: dict[str, Any] | None) -> str:
    """Dev provenance string from an analytics envelope (engine / query_version / run_id)."""
    if not isinstance(envelope, dict):
        return ""
    engine = envelope.get("engine") or "—"
    qv = envelope.get("query_version") or "—"
    run_id = envelope.get("run_id") or envelope.get("job_id") or "—"
    return f"analytics provenance · engine={engine} · query_version={qv} · run_id={run_id}"


def build_runtime_samples(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build ``{equipment_id, timestamp, on}`` samples (fan-status preferred over fan-cmd)."""
    role_map = role_map or {}
    samples: list[dict[str, Any]] = []
    ids = equipment_ids or list(frames.keys())
    for eq_id in ids:
        raw = frames.get(eq_id)
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        on_ser: pd.Series | None = None
        for role in FAN_ROLES:
            if role in mapped.columns and mapped[role].notna().any():
                on_ser = _is_on(mapped[role])
                break
        if on_ser is None:
            continue
        idx = mapped.index
        if not isinstance(idx, pd.DatetimeIndex):
            continue
        for ts, on_val in zip(idx, on_ser.fillna(False).astype(bool)):
            iso = _ts_iso(ts)
            if iso is None:
                continue
            samples.append(
                {
                    "equipment_id": str(eq_id),
                    "timestamp": iso,
                    "on": bool(on_val),
                }
            )
    return samples


def fetch_runtime_analytics(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    max_gap_seconds: float = 900.0,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST runtime samples to central when healthy; return error dict on failure (no pandas)."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    samples = build_runtime_samples(frames, role_map, equipment_ids=equipment_ids)
    if not samples:
        return {"ok": False, "error": "no fan-status/fan-cmd samples to send"}
    payload: dict[str, Any] = {
        "samples": samples,
        "max_gap_seconds": float(max_gap_seconds),
        "query_version": "runtime-v1",
    }
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if extra:
        payload.update(extra)
    resp = central_client.analytics_post("runtime", payload)
    if not isinstance(resp, dict):
        return {"ok": False, "error": f"unexpected central response: {resp!r}"}
    if resp.get("ok") is False or resp.get("central_down"):
        return resp
    analytics = resp.get("analytics")
    if not isinstance(analytics, dict):
        return {"ok": False, "error": "central response missing analytics envelope", **resp}
    return {"ok": True, "analytics": analytics, **{k: v for k, v in resp.items() if k != "analytics"}}


def _econ_fan_on_mask(mapped: pd.DataFrame) -> pd.Series:
    masks: list[pd.Series] = []
    for role in FAN_ROLES:
        if role in mapped.columns and mapped[role].notna().any():
            masks.append(_is_on(mapped[role]).fillna(False).astype(bool))
    if not masks:
        return pd.Series(False, index=mapped.index)
    out = masks[0]
    for m in masks[1:]:
        out = out | m
    return out


def _econ_resolve_oat(mapped: pd.DataFrame, *, prefer_web_oat: bool = False) -> pd.Series | None:
    bas = None
    if "outside-air-temp" in mapped.columns and mapped["outside-air-temp"].notna().any():
        bas = pd.to_numeric(mapped["outside-air-temp"], errors="coerce")
    elif "bas-outside-air-temp" in mapped.columns and mapped["bas-outside-air-temp"].notna().any():
        bas = pd.to_numeric(mapped["bas-outside-air-temp"], errors="coerce")
    web = None
    if "web-outside-air-temp" in mapped.columns and mapped["web-outside-air-temp"].notna().any():
        web = pd.to_numeric(mapped["web-outside-air-temp"], errors="coerce")
    elif "oa_t_effective" in mapped.columns and mapped["oa_t_effective"].notna().any():
        web = pd.to_numeric(mapped["oa_t_effective"], errors="coerce")
    if prefer_web_oat and web is not None and web.notna().any():
        return web
    if bas is not None and bas.notna().any():
        return bas
    return web


def _is_econ_air_equipment(eq_id: str, et: str) -> bool:
    et_n = normalize_equipment_type(et) if et else ""
    if et_n in ECON_AIR_TYPES:
        return True
    upper = str(eq_id).upper()
    return any(tok in upper for tok in ("AHU", "RTU", "MAU", "AIRHAND"))


def _damper_pct(series: pd.Series) -> pd.Series:
    """Normalize damper feedback to percent 0–100 (accepts 0–1 or 0–100)."""
    num = pd.to_numeric(series, errors="coerce")
    # Values ≤ 1.5 treated as fraction → percent.
    return num.where(num > 1.5, num * 100.0)


def build_economizer_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    weather: pd.DataFrame | None = None,
    prefer_web_oat: bool = False,
    equipment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build ``{"points": [...]}`` payload for ``POST /api/analytics/economizer``."""
    role_map = role_map or {}
    points: list[dict[str, Any]] = []
    ids = equipment_ids or list(frames.keys())

    for eq_id in ids:
        raw = frames.get(eq_id)
        if raw is None or raw.empty:
            continue
        et = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        if not _is_econ_air_equipment(eq_id, et or ""):
            continue
        et_n = normalize_equipment_type(et) if et else ""
        if et_n not in ECON_AIR_TYPES:
            et_n = et_n or "AHU"

        mapped = apply_role_map(raw, eq_id, role_map)
        if weather is not None and not weather.empty:
            try:
                from app.rules.runner import merge_weather

                mapped = merge_weather(mapped, weather)
            except Exception:
                pass
        fan_on = _econ_fan_on_mask(mapped)
        oat = _econ_resolve_oat(mapped, prefer_web_oat=prefer_web_oat)
        rat = (
            pd.to_numeric(mapped["return-air-temp"], errors="coerce")
            if "return-air-temp" in mapped.columns
            else None
        )
        mat = (
            pd.to_numeric(mapped["mixed-air-temp"], errors="coerce")
            if "mixed-air-temp" in mapped.columns
            else None
        )
        if oat is None or rat is None or mat is None:
            continue

        sat = (
            pd.to_numeric(mapped["discharge-air-temp"], errors="coerce")
            if "discharge-air-temp" in mapped.columns
            else None
        )
        damper = None
        if "outside-air-damper" in mapped.columns and mapped["outside-air-damper"].notna().any():
            damper = _damper_pct(mapped["outside-air-damper"])

        idx = mapped.index
        if not isinstance(idx, pd.DatetimeIndex):
            continue

        for i, ts in enumerate(idx):
            iso = _ts_iso(ts)
            if iso is None:
                continue
            oat_v = float(oat.iloc[i]) if oat is not None else float("nan")
            rat_v = float(rat.iloc[i]) if rat is not None else float("nan")
            mat_v = float(mat.iloc[i]) if mat is not None else float("nan")
            if any(pd.isna(v) for v in (oat_v, rat_v, mat_v)):
                continue
            row: dict[str, Any] = {
                "equipment_id": str(eq_id),
                "equipment_type": et_n or "AHU",
                "timestamp": iso,
                "oat_f": oat_v,
                "rat_f": rat_v,
                "mat_f": mat_v,
                "fan_on": bool(fan_on.iloc[i]) if i < len(fan_on) else False,
            }
            if sat is not None and not pd.isna(sat.iloc[i]):
                row["sat_f"] = float(sat.iloc[i])
            if damper is not None and not pd.isna(damper.iloc[i]):
                row["oa_damper_pct"] = float(damper.iloc[i])
            points.append(row)

    return {"points": points}


def fetch_economizer_analytics(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    weather: pd.DataFrame | None = None,
    prefer_web_oat: bool = False,
    dt_min_f: float = 10.0,
    max_points: int = 8000,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST economizer series to central when healthy; return error dict on failure."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    series = build_economizer_series(
        frames,
        role_map,
        weather=weather,
        prefer_web_oat=prefer_web_oat,
        equipment_ids=equipment_ids,
    )
    if not series.get("points"):
        return {"ok": False, "error": "no economizer points to send"}
    payload: dict[str, Any] = {
        "series": series,
        "dt_min_f": float(dt_min_f),
        "max_points": int(max_points),
        "query_version": "economizer-diagnostics-v1",
    }
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if extra:
        payload.update(extra)
    resp = central_client.analytics_post("economizer", payload)
    if not isinstance(resp, dict):
        return {"ok": False, "error": f"unexpected central response: {resp!r}"}
    if resp.get("ok") is False or resp.get("central_down"):
        return resp
    analytics = resp.get("analytics")
    if not isinstance(analytics, dict):
        return {"ok": False, "error": "central response missing analytics envelope", **resp}
    return {"ok": True, "analytics": analytics, **{k: v for k, v in resp.items() if k != "analytics"}}
