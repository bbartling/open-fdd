"""Canonical VAV health matrix (vav_health_matrix_v1).

Analytic / cohort classification — does not add a 60th diagnostic rule.
Unknown evidence is not PASS.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from open_fdd.analytics.occupancy import OccupancySchedule, occupied_mask
from open_fdd.analytics.site_model import resolve_equipment_type

SCHEMA_VERSION = "vav_health_matrix_v1"
DEFAULT_BROKEN_RULES = (
    "VAV-3",
    "VAV-4",
    "VAV-5",
    "VAV-7",
    "VAV-REHEAT",
    "VAV-AHU-LEAVE",
)
FULL_OPEN_DEFAULT = 0.975
ENGINE_PANDAS = "pandas"


@dataclass
class VavHealthConfig:
    broken_rule_ids: tuple[str, ...] = DEFAULT_BROKEN_RULES
    comfort_low_f: float = 70.0
    comfort_high_f: float = 75.0
    min_occupied_hours: float = 8.0
    min_coverage_pct: float = 80.0
    damper_full_open: float = FULL_OPEN_DEFAULT
    rogue_prevalence_pct: float = 95.0
    min_operating_hours: float = 20.0
    flow_on_min: float = 25.0
    poll_seconds: float = 300.0

    def fingerprint(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _norm_damper(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.where(x.le(1.0), x / 100.0)


def _air_on(df: pd.DataFrame, flow_on_min: float) -> pd.Series:
    if "fan_status" in df.columns:
        st = pd.to_numeric(df["fan_status"], errors="coerce")
        if st.notna().any():
            return st > 0.05
    if "fan_cmd" in df.columns:
        cmd = pd.to_numeric(df["fan_cmd"], errors="coerce")
        cmd = cmd.where(cmd.le(1.0), cmd / 100.0)
        if cmd.notna().any():
            return cmd > 0.01
    if "zone_flow" in df.columns:
        fl = pd.to_numeric(df["zone_flow"], errors="coerce")
        return fl > flow_on_min
    return pd.Series(False, index=df.index)


def _hours(mask: pd.Series, poll: float) -> float:
    return float(mask.fillna(False).sum()) * poll / 3600.0


def _col(df: pd.DataFrame, *names: str) -> pd.Series | None:
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce")
    return None


def vav_health_matrix(
    frames: Mapping[str, pd.DataFrame],
    *,
    building_id: str,
    rule_results: pd.DataFrame | None = None,
    occupancy: OccupancySchedule | None = None,
    role_map: Mapping[str, Mapping[str, str]] | None = None,
    parent_ahu: Mapping[str, str] | None = None,
    config: VavHealthConfig | None = None,
    engine: str = ENGINE_PANDAS,
) -> pd.DataFrame:
    """Return one row per VAV-like equipment."""
    cfg = config or VavHealthConfig()
    occ = occupancy or OccupancySchedule()
    fp = cfg.fingerprint()
    rows: list[dict[str, Any]] = []
    _ = role_map

    rr = rule_results if rule_results is not None else pd.DataFrame()

    for eq_id, raw in frames.items():
        et = resolve_equipment_type(eq_id, df=raw)
        if str(et).upper() not in {"VAV", "ZONE", "VAVBOX"} and not str(eq_id).upper().startswith(
            "VAV"
        ):
            continue
        df = raw.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            ts = df.get("timestamp_utc")
            if ts is not None:
                df = df.set_index(pd.to_datetime(ts, utc=True))
        idx = df.index
        n = len(df)
        coverage = 100.0 if n else 0.0
        poll = cfg.poll_seconds
        air = _air_on(df, cfg.flow_on_min)
        operating_h = _hours(air, poll)

        # Broken box from rule results
        broken = None
        broken_ids: list[str] = []
        broken_h = 0.0
        if not rr.empty and "equipment_id" in rr.columns:
            sub = rr[rr["equipment_id"].astype(str) == str(eq_id)]
            if "rule_id" in sub.columns:
                hit = sub[sub["rule_id"].astype(str).isin(cfg.broken_rule_ids)]
                if not hit.empty:
                    if "fault_hours" in hit.columns:
                        broken_h = float(pd.to_numeric(hit["fault_hours"], errors="coerce").fillna(0).sum())
                    if "status" in hit.columns:
                        faulted = hit[hit["status"].astype(str).str.upper().eq("FAULT")]
                        broken_ids = sorted(faulted["rule_id"].astype(str).unique())
                        broken = bool(broken_ids) or broken_h > 0
                    else:
                        broken = broken_h > 0
                        broken_ids = sorted(hit["rule_id"].astype(str).unique()) if broken else []
                else:
                    broken = False

        # Occupied comfort
        poor = None
        fail_pct = None
        occ_h = 0.0
        occ_samples = 0
        zone = _col(df, "zone_t", "zone-air-temp")
        if zone is not None and n:
            om = occupied_mask(pd.DatetimeIndex(idx), occ)
            om = om.reindex(idx).fillna(False)
            occ_samples = int(om.sum())
            occ_h = _hours(om, poll)
            if occ_h < cfg.min_occupied_hours:
                poor = None
            else:
                z = zone.reindex(idx)
                outside = om & z.notna() & ((z < cfg.comfort_low_f) | (z > cfg.comfort_high_f))
                denom = float((om & z.notna()).sum())
                fail_pct = 100.0 * float(outside.sum()) / denom if denom else None
                poor = bool(fail_pct is not None and fail_pct > 0)
        elif n == 0:
            poor = None

        # Rogue damper
        rogue = None
        d_pct = None
        d_h = 0.0
        notes: list[str] = []
        dmp_col = None
        for c in ("damper_pct", "damper", "zone-damper"):
            if c in df.columns:
                dmp_col = c
                break
        if dmp_col is None:
            notes.append("missing_damper")
        elif operating_h < cfg.min_operating_hours:
            notes.append("insufficient_operating_hours")
        else:
            dmp = _norm_damper(df[dmp_col])
            full = air & dmp.notna() & (dmp >= cfg.damper_full_open)
            d_h = _hours(full, poll)
            d_pct = 100.0 * d_h / operating_h if operating_h else None
            if d_pct is None:
                rogue = None
            else:
                rogue = d_pct >= cfg.rogue_prevalence_pct
                if rogue:
                    notes.append("full_open_prevalence")

        flow = _col(df, "zone_flow", "zone-airflow")
        flow_sp = _col(df, "min_flow_sp", "min-flow-sp", "airflow_sp")
        track_pct = None
        track_h = None
        if flow is not None and flow_sp is not None and operating_h > 0:
            err = air & flow.notna() & flow_sp.notna() & ((flow - flow_sp).abs() > 50.0)
            track_h = _hours(err, poll)
            track_pct = 100.0 * track_h / operating_h
            if rogue and track_pct and track_pct > 20:
                notes.append("airflow_tracking_failure")
            elif rogue and poor:
                notes.append("comfort_or_load")
            elif rogue:
                notes.append("possible_starvation")

        dims = [broken, poor, rogue]
        evaluable = sum(x is not None for x in dims)
        hit = sum(bool(x) for x in dims if x is not None)
        if evaluable < 3:
            label = f"?/3"
            conf = "insufficient" if evaluable == 0 else "low"
        else:
            label = f"{hit}/3"
            conf = "high" if coverage >= cfg.min_coverage_pct else "medium"

        ts_min = str(idx.min()) if n else None
        ts_max = str(idx.max()) if n else None
        rows.append(
            {
                "building_id": building_id,
                "equipment_id": eq_id,
                "parent_ahu": (parent_ahu or {}).get(eq_id, ""),
                "equipment_type": et,
                "broken_box": broken,
                "poor_zone_performance": poor,
                "rogue_damper": rogue,
                "dimensions_hit": hit,
                "dimensions_evaluable": evaluable,
                "score_label": label,
                "broken_rule_ids": ";".join(broken_ids),
                "broken_fault_hours": broken_h,
                "occupied_comfort_fail_pct": fail_pct,
                "occupied_samples": occ_samples,
                "occupied_hours": occ_h,
                "damper_full_open_pct": d_pct,
                "damper_full_open_hours": d_h,
                "operating_hours": operating_h,
                "airflow_tracking_error_pct": track_pct,
                "airflow_tracking_error_hours": track_h,
                "data_coverage_pct": coverage,
                "confidence": conf,
                "first_evidence_timestamp": ts_min,
                "last_evidence_timestamp": ts_max,
                "engine": engine,
                "schema_version": SCHEMA_VERSION,
                "thresholds_fingerprint": fp,
                "notes": ",".join(notes),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {"3/3": 0, "2/3": 1, "1/3": 2, "0/3": 3, "?/3": 4}
    out["_g"] = out["score_label"].map(lambda s: order.get(str(s), 9))
    out = out.sort_values(["_g", "equipment_id"])
    return out.drop(columns=["_g"])


def vav_health_summary(matrix: pd.DataFrame) -> dict[str, Any]:
    """Counts and equipment lists by score group."""
    groups = ("3/3", "2/3", "1/3", "0/3", "?/3")
    out: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "groups": {}}
    if matrix is None or matrix.empty:
        for g in groups:
            out["groups"][g] = {"count": 0, "equipment_ids": []}
        return out
    for g in groups:
        ids = matrix.loc[matrix["score_label"] == g, "equipment_id"].astype(str).tolist()
        out["groups"][g] = {"count": len(ids), "equipment_ids": ids}
    return out
