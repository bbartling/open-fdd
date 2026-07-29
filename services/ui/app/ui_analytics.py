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


def oracle_fallback_enabled() -> bool:
    """True when explicit pandas oracle fallback is allowed (dev/parity only)."""
    flag = (os.environ.get("OPENFDD_ANALYTICS_ORACLE") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


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
    building_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST economizer series to central when healthy; return error dict on failure.

    OFDD-070: when ``building_id`` is provided it is forwarded so central can scope
    the historian read to ``building={id}/`` (no cross-site parquet bleed). Inline
    series is still built from the active site's frames.
    """
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
    bid = (building_id or "").strip()
    if bid:
        payload["building_id"] = bid
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


# ---------------------------------------------------------------------------
# Milestone D1 — central cutover for additional analytics families.
#
# Each ``fetch_*`` helper: gate on central health, build an inline payload from
# frames/role_map (no fabrication), POST to central, and return either
# ``{"ok": True, "analytics": envelope, ...}`` or an error dict. None of these
# ever fall back to pandas — call sites gate pandas behind OPENFDD_ANALYTICS_ORACLE.
# ---------------------------------------------------------------------------


def _normalize_central_response(resp: Any) -> dict[str, Any]:
    """Shared central-envelope unwrap (mirrors runtime/economizer tails)."""
    if not isinstance(resp, dict):
        return {"ok": False, "error": f"unexpected central response: {resp!r}"}
    if resp.get("ok") is False or resp.get("central_down"):
        return resp
    analytics = resp.get("analytics")
    if not isinstance(analytics, dict):
        return {"ok": False, "error": "central response missing analytics envelope", **resp}
    return {
        "ok": True,
        "analytics": analytics,
        **{k: v for k, v in resp.items() if k != "analytics"},
    }


# Numeric role columns (post ``apply_role_map`` dashed names) worth sensor stats.
SENSOR_HEALTH_ROLES: tuple[str, ...] = (
    "outside-air-temp",
    "return-air-temp",
    "mixed-air-temp",
    "discharge-air-temp",
    "zone-air-temp",
    "fan-cmd",
    "fan-status",
    "outside-air-damper",
    "cooling-valve",
    "heating-valve",
    "supply-air-temp-sp",
    "duct-static",
    "duct-static-sp",
    "zone-airflow",
)


def build_sensor_health_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build ``{"points": [{equipment_id, role, timestamp, value}]}`` for sensor health."""
    role_map = role_map or {}
    points: list[dict[str, Any]] = []
    ids = equipment_ids or list(frames.keys())
    for eq_id in ids:
        raw = frames.get(eq_id)
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        idx = mapped.index
        if not isinstance(idx, pd.DatetimeIndex):
            continue
        iso_index = [_ts_iso(ts) for ts in idx]
        for role in SENSOR_HEALTH_ROLES:
            if role not in mapped.columns:
                continue
            col = pd.to_numeric(mapped[role], errors="coerce")
            if not col.notna().any():
                continue
            for iso, val in zip(iso_index, col):
                if iso is None:
                    continue
                points.append(
                    {
                        "equipment_id": str(eq_id),
                        "role": role,
                        "timestamp": iso,
                        "value": None if pd.isna(val) else float(val),
                    }
                )
    return {"points": points}


def fetch_sensor_health_analytics(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST sensor-health series to central when healthy; error dict otherwise (no pandas)."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    series = build_sensor_health_series(frames, role_map, equipment_ids=equipment_ids)
    if not series.get("points"):
        return {"ok": False, "error": "no sensor series points to send"}
    payload: dict[str, Any] = {"series": series, "query_version": "sensor-health-v1"}
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if extra:
        payload.update(extra)
    return _normalize_central_response(central_client.analytics_post("sensor-health", payload))


def build_schedule_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    occupancy: Any | None = None,
    equipment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build ``{"occupied": [...], "fan": [...]}`` from an occupancy schedule + fan roles."""
    role_map = role_map or {}
    ids = equipment_ids or list(frames.keys())
    occupied: list[dict[str, Any]] = []
    fan: list[dict[str, Any]] = []
    seen_occ: set[str] = set()
    occ_mask_fn = None
    if occupancy is not None:
        try:
            from app.occupancy import occupied_mask as occ_mask_fn  # type: ignore
        except Exception:
            occ_mask_fn = None

    for eq_id in ids:
        raw = frames.get(eq_id)
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        idx = mapped.index
        if not isinstance(idx, pd.DatetimeIndex):
            continue
        if occ_mask_fn is not None:
            try:
                mask = occ_mask_fn(idx, occupancy)
            except Exception:
                mask = None
            if mask is not None:
                for ts, occ in zip(idx, mask):
                    iso = _ts_iso(ts)
                    if iso is None or iso in seen_occ:
                        continue
                    seen_occ.add(iso)
                    occupied.append({"timestamp": iso, "occupied": bool(occ)})
        fan_ser: pd.Series | None = None
        for role in FAN_ROLES:
            if role in mapped.columns and mapped[role].notna().any():
                fan_ser = _is_on(mapped[role])
                break
        if fan_ser is not None:
            for ts, on in zip(idx, fan_ser.fillna(False).astype(bool)):
                iso = _ts_iso(ts)
                if iso is None:
                    continue
                fan.append(
                    {"timestamp": iso, "fan_on": bool(on), "equipment_id": str(eq_id)}
                )

    out: dict[str, Any] = {}
    if occupied:
        out["occupied"] = occupied
    if fan:
        out["fan"] = fan
    return out


def fetch_schedule_analytics(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    occupancy: Any | None = None,
    max_gap_seconds: float = 900.0,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST schedule occupied mask (+ fan overlay) to central; error dict otherwise."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    series = build_schedule_series(
        frames, role_map, occupancy=occupancy, equipment_ids=equipment_ids
    )
    if not series.get("occupied"):
        return {
            "ok": False,
            "error": "no occupied-mask samples to send (occupancy schedule required)",
        }
    payload: dict[str, Any] = {
        "series": series,
        "max_gap_seconds": float(max_gap_seconds),
        "query_version": "schedule-v1",
    }
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if extra:
        payload.update(extra)
    return _normalize_central_response(central_client.analytics_post("schedule", payload))


# Dashed role column → central mechanical-cooling evidence_kind.
MECH_COOLING_EVIDENCE_ROLES: dict[str, str] = {
    "compressor-status": "compressor_status",
    "chiller-status": "chiller_status",
    "cooling-valve": "valve_cmd",
    "chw-valve": "valve_cmd",
    "pump-status": "pump_status",
    "chw-pump-status": "pump_status",
    "chw-pump": "pump_status",
}


def build_mechanical_cooling_evidence(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build ``{"evidence": [{equipment_id, evidence_kind, role, present}]}`` from role presence."""
    role_map = role_map or {}
    ids = equipment_ids or list(frames.keys())
    evidence: list[dict[str, Any]] = []
    for eq_id in ids:
        raw = frames.get(eq_id)
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        for role_col, kind in MECH_COOLING_EVIDENCE_ROLES.items():
            if role_col in mapped.columns and mapped[role_col].notna().any():
                evidence.append(
                    {
                        "equipment_id": str(eq_id),
                        "evidence_kind": kind,
                        "role": role_col,
                        "present": True,
                    }
                )
    return {"evidence": evidence}


def fetch_mechanical_cooling_analytics(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST mechanical-cooling evidence to central; error dict otherwise (no pandas)."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    series = build_mechanical_cooling_evidence(frames, role_map, equipment_ids=equipment_ids)
    if not series.get("evidence"):
        return {"ok": False, "error": "no mechanical-cooling evidence rows to send"}
    payload: dict[str, Any] = {"series": series, "query_version": "mechanical-cooling-v1"}
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if extra:
        payload.update(extra)
    return _normalize_central_response(
        central_client.analytics_post("mechanical-cooling", payload)
    )


# Dashed reset-evidence role column → central rcx role name.
RCX_AHU_RESET_ROLES: dict[str, str] = {
    "supply-air-temp-sp": "sat_sp",
    "duct-static-sp": "duct_static_sp",
}


def build_rcx_ahu_series(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build ``{"points": [{equipment_id, role, timestamp, value}]}`` for AHU reset evidence."""
    role_map = role_map or {}
    ids = equipment_ids or list(frames.keys())
    points: list[dict[str, Any]] = []
    for eq_id in ids:
        raw = frames.get(eq_id)
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        idx = mapped.index
        if not isinstance(idx, pd.DatetimeIndex):
            continue
        iso_index = [_ts_iso(ts) for ts in idx]
        for role_col, central_role in RCX_AHU_RESET_ROLES.items():
            if role_col not in mapped.columns:
                continue
            col = pd.to_numeric(mapped[role_col], errors="coerce")
            if not col.notna().any():
                continue
            for iso, val in zip(iso_index, col):
                if iso is None:
                    continue
                points.append(
                    {
                        "equipment_id": str(eq_id),
                        "role": central_role,
                        "timestamp": iso,
                        "value": None if pd.isna(val) else float(val),
                    }
                )
    return {"points": points}


def fetch_rcx_ahu_analytics(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST AHU reset-evidence series to central; error dict otherwise (no pandas)."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    series = build_rcx_ahu_series(frames, role_map, equipment_ids=equipment_ids)
    if not series.get("points"):
        return {"ok": False, "error": "no AHU reset-evidence points to send"}
    payload: dict[str, Any] = {"series": series, "query_version": "rcx-ahu-v1"}
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if extra:
        payload.update(extra)
    return _normalize_central_response(central_client.analytics_post("rcx/ahu", payload))


# Candidate dashed setpoint columns for VAV zone comfort (first present wins).
VAV_SETPOINT_ROLES: tuple[str, ...] = (
    "zone-temp-sp",
    "zone-air-temp-sp",
    "cooling-setpoint",
    "effective-setpoint",
)


def build_rcx_vav_zones(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
    band_f: float = 2.0,
) -> dict[str, Any]:
    """Build ``{"zones": [{equipment_id, timestamp, zone_temp, setpoint, band_f}]}``."""
    role_map = role_map or {}
    ids = equipment_ids or list(frames.keys())
    zones: list[dict[str, Any]] = []
    for eq_id in ids:
        raw = frames.get(eq_id)
        if raw is None or raw.empty:
            continue
        mapped = apply_role_map(raw, eq_id, role_map)
        idx = mapped.index
        if "zone-air-temp" not in mapped.columns or not isinstance(idx, pd.DatetimeIndex):
            continue
        zt = pd.to_numeric(mapped["zone-air-temp"], errors="coerce")
        if not zt.notna().any():
            continue
        sp = None
        for sp_role in VAV_SETPOINT_ROLES:
            if sp_role in mapped.columns and mapped[sp_role].notna().any():
                sp = pd.to_numeric(mapped[sp_role], errors="coerce")
                break
        if sp is None:
            continue
        for i, ts in enumerate(idx):
            iso = _ts_iso(ts)
            if iso is None:
                continue
            zt_v = zt.iloc[i]
            sp_v = sp.iloc[i]
            if pd.isna(zt_v) or pd.isna(sp_v):
                continue
            zones.append(
                {
                    "equipment_id": str(eq_id),
                    "timestamp": iso,
                    "zone_temp": float(zt_v),
                    "setpoint": float(sp_v),
                    "band_f": float(band_f),
                }
            )
    return {"zones": zones}


def fetch_rcx_vav_analytics(
    frames: dict[str, pd.DataFrame],
    role_map: dict | None,
    *,
    equipment_ids: list[str] | None = None,
    band_f: float = 2.0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST VAV zone-comfort series to central; error dict otherwise (no pandas)."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    series = build_rcx_vav_zones(frames, role_map, equipment_ids=equipment_ids, band_f=band_f)
    if not series.get("zones"):
        return {"ok": False, "error": "no VAV zone_temp/setpoint samples to send"}
    payload: dict[str, Any] = {"series": series, "query_version": "rcx-vav-v1"}
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if extra:
        payload.update(extra)
    return _normalize_central_response(central_client.analytics_post("rcx/vav", payload))


def build_metering_rows(
    monthly_df: pd.DataFrame,
    *,
    energy_col: str = "kwh",
) -> dict[str, Any]:
    """Convert an app.metering monthly frame to central ``{"rows": [{period, kwh, meter_id}]}``."""
    rows: list[dict[str, Any]] = []
    if monthly_df is None or monthly_df.empty:
        return {"rows": rows}
    period_col = "month_label" if "month_label" in monthly_df.columns else None
    for _, r in monthly_df.iterrows():
        if period_col is not None:
            period = str(r[period_col])
        else:
            period = str(r.get("month", ""))
        val = r.get(energy_col)
        if val is None or pd.isna(val):
            continue
        rows.append(
            {
                "period": period,
                "kwh": float(val),
                "meter_id": str(r.get("equipment_id") or r.get("role") or ""),
            }
        )
    return {"rows": rows}


def fetch_metering_analytics(
    monthly_df: pd.DataFrame,
    *,
    energy_col: str = "kwh",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST monthly meter rows to central for the metering envelope; error dict otherwise."""
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    series = build_metering_rows(monthly_df, energy_col=energy_col)
    if not series.get("rows"):
        return {"ok": False, "error": "no metering {period,kwh} rows to send"}
    payload: dict[str, Any] = {"series": series, "query_version": "metering-v1"}
    if extra:
        payload.update(extra)
    return _normalize_central_response(central_client.analytics_post("metering", payload))


def _fetch_plant_analytics(
    family: str,
    query_version: str,
    equipment_rows: list[dict[str, Any]] | None,
    equipment_ids: list[str] | None,
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    if not central_client.health_ok():
        return {"ok": False, "error": "central health check failed", "central_down": True}
    payload: dict[str, Any] = {"query_version": query_version}
    if equipment_rows:
        payload["series"] = {"equipment": equipment_rows}
    if equipment_ids:
        payload["equipment_ids"] = list(equipment_ids)
    if not equipment_rows and not equipment_ids:
        return {"ok": False, "error": "no plant equipment rows or equipment_ids to send"}
    if extra:
        payload.update(extra)
    return _normalize_central_response(central_client.analytics_post(family, payload))


def fetch_plant_chiller_analytics(
    equipment_rows: list[dict[str, Any]] | None = None,
    *,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST chiller plant evidence rows (run_hours etc.); never invents kW/ton."""
    return _fetch_plant_analytics(
        "rcx/chiller", "rcx-chiller-v1", equipment_rows, equipment_ids, extra
    )


def fetch_plant_boiler_analytics(
    equipment_rows: list[dict[str, Any]] | None = None,
    *,
    equipment_ids: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST boiler plant evidence rows (run_hours etc.); descriptive only."""
    return _fetch_plant_analytics(
        "rcx/boiler", "rcx-boiler-v1", equipment_rows, equipment_ids, extra
    )
