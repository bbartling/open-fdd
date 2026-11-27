"""SQL mechanical-cooling OAT bins (issue #1649): ``sql/analytics/mech_cooling_oat_bins.sql`` on SQLite, DuckDB or PostgreSQL.

The query reads the v5 SI core (``fdd.point`` + ``fdd.input_sample``). Which points prove that a device is cooling is
decided here, from bound roles and the equipment type, with the same ladder as
:func:`open_fdd.analytics.core._select_mech_cooling_proof`; the sample math (which tier is used, intervals, bins) runs in
SQL. The packaged copy ``open_fdd/data/mech_cooling_oat_bins.sql`` is byte-identical to the repo file (a test checks it).

:func:`mech_cooling_oat_bins_sql` takes pandas frames plus a role map and returns the individual-device rows of
:func:`open_fdd.analytics.core.mech_cooling_oat_bins`, so the two can be compared. Not ported here: the
``use_status_proof=False`` CHW-temperature inference, the imperial bins and the ``include_total`` aggregate rows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import resources
from typing import Any, Iterable, Mapping

from open_fdd.analytics.runtime_intervals import ELAPSED_MAX_GAP_SECONDS
from open_fdd.analytics.si_thresholds import MECH_OAT_BIN_EDGES_C, MECH_OAT_BIN_LABELS
from open_fdd.analytics.sql_anomaly import DEFAULT_SITE, _connect, _quote, create_core, load_core, normalize_engine
from open_fdd.analytics.sql_runtime import OAT_ROLES, TS_MS, _inline

CHILLER_AMPS_MIN = 5.0
CHILLER_POWER_KW_MIN = 1.0

COMPRESSOR_STAGES = ("compressor-stage-1", "compressor-stage-2", "cool-stage", "dx-stage")
HP_COOLING_MODE = ("heat-pump-cooling-status", "unit-cooling-status")


@dataclass(frozen=True)
class Tier:
    """One rung of the proof ladder: ``alts`` are tried in order; a tuple inside ``alts`` is OR'ed (stages)."""

    alts: tuple  # each item: a role, or a tuple of roles OR'ed together
    kind: str  # "on" (run threshold) or "above" (value > thr)
    thr: float | None
    legacy: str  # pandas legacy proof label (source_kind)
    proof_role: str | None = None  # label when the alt is a group (compressor stages)


def _ladder(et: str) -> tuple[list[Tier], tuple[str, ...]]:
    """(tiers, cooling-mode gate roles) for a canonical equipment type; ([], ()) when it is not a cooling device."""
    if et == "CHW_PLANT":
        return [
            Tier(("chiller-status", "compressor-status"), "on", None, "chiller-status"),
            Tier(("compressor-cmd", "dx-cool-cmd"), "on", None, "chiller-status"),
            Tier(("chiller-amps",), "above", CHILLER_AMPS_MIN, "chiller-amps"),
            Tier(("chiller-power",), "above", CHILLER_POWER_KW_MIN, "chiller_power"),
            Tier(("compressor-power",), "above", CHILLER_POWER_KW_MIN, "chiller_power"),
            Tier(("compressor-current",), "above", CHILLER_AMPS_MIN, "chiller-amps"),
        ], ()
    if et in {"AHU", "RTU", "HP"}:
        legacy = "heatpump" if et == "HP" else "ahu_dx"
        tiers = [
            Tier(("compressor-status",), "on", None, legacy),
            Tier(("compressor-cmd", "dx-cool-cmd"), "on", None, legacy),
            Tier((COMPRESSOR_STAGES,), "on", None, legacy, proof_role="compressor-stage"),
            Tier(("dx-cooling", "unit-cooling-status"), "on", None, legacy),
            Tier(("compressor-power",), "above", CHILLER_POWER_KW_MIN, legacy),
            Tier(("compressor-current",), "above", CHILLER_AMPS_MIN, legacy),
        ]
        return tiers, (HP_COOLING_MODE if et == "HP" else ())
    if et == "VRF":
        return [
            Tier(("vrf-outdoor-compressor-status",), "on", None, "vrf-outdoor-compressor-status"),
            Tier(("compressor-status",), "on", None, "vrf-outdoor-compressor-status"),
        ], ()
    return [], ()


@dataclass
class Plan:
    """Inline tables for the query plus the labels to read its result back."""

    candidates: list[tuple]  # (equipment_id, tier, alt, point_key, kind, thr)
    gates: list[tuple]  # (equipment_id, point_key)
    oats: list[tuple]  # (equipment_id, point_key)
    labels: dict  # (equipment_id, tier, alt) -> (proof_role, legacy, quality)


def build_plan(devices: Iterable[tuple[str, str, Mapping[str, str]]]) -> Plan:
    """``devices``: (equipment_id, canonical equipment type, {pandas role: point_key}) for the bound roles.

    A heat pump with no cooling-mode role, or a device with no proof role, gets no candidates (pandas excludes it).
    """
    plan = Plan([], [], [], {})
    for eq_id, et, roles in devices:
        tiers, gate_roles = _ladder(et)
        if not tiers:
            continue
        gates = [roles[r] for r in gate_roles if r in roles]
        if gate_roles and not gates:
            continue
        rows = []
        for t_i, tier in enumerate(tiers, start=1):
            for a_i, alt in enumerate(tier.alts):
                group = alt if isinstance(alt, tuple) else (alt,)
                for role in group:
                    if role in roles:
                        rows.append((eq_id, t_i, a_i, roles[role], tier.kind, tier.thr))
                quality = "direct" if tier.kind == "on" else "analog"
                plan.labels[(eq_id, t_i, a_i)] = (tier.proof_role or group[0], tier.legacy, quality)
        if not rows:
            continue
        plan.candidates.extend(rows)
        plan.gates.extend((eq_id, g) for g in gates)
        oat = next((roles[r] for r in OAT_ROLES if r in roles), None)
        if oat is not None:
            plan.oats.append((eq_id, oat))
    return plan


def mech_bins_sql_template() -> str:
    return resources.files("open_fdd").joinpath("data/mech_cooling_oat_bins.sql").read_text(encoding="utf-8")


def render_mech_bins_sql(
    engine: str,
    plan: Plan,
    *,
    site_id: str = DEFAULT_SITE,
    start_ms: int | None = None,
    end_ms: int | None = None,
    max_gap_seconds: float = ELAPSED_MAX_GAP_SECONDS,
) -> str:
    if engine not in TS_MS:
        raise ValueError(f"unknown engine {engine!r}")
    gap = float(max_gap_seconds)
    if not math.isfinite(gap) or gap <= 0:
        raise ValueError("max_gap_seconds must be a positive number")
    if start_ms is not None and end_ms is not None and int(end_ms) <= int(start_ms):
        raise ValueError("end_ms must be after start_ms")
    for row in plan.candidates:
        if row[4] not in ("on", "above"):
            raise ValueError(f"unknown proof kind {row[4]!r}")
    window_filter = ""
    if start_ms is not None:
        window_filter += f" AND t >= {int(start_ms)}"
    if end_ms is not None:
        window_filter += f" AND t < {int(end_ms)}"
    cases = " ".join(f"WHEN oat < {float(e)!r} THEN {i}" for i, e in enumerate(MECH_OAT_BIN_EDGES_C))
    cases += f" ELSE {len(MECH_OAT_BIN_EDGES_C)}"
    body = "\n".join(ln for ln in mech_bins_sql_template().splitlines() if not ln.lstrip().startswith("--"))
    return body.format(
        candidates=_inline([("equipment_id", "TEXT"), ("tier", "INTEGER"), ("alt", "INTEGER"), ("point_key", "TEXT"),
                            ("kind", "TEXT"), ("thr", "DOUBLE PRECISION")], plan.candidates),
        gates=_inline([("equipment_id", "TEXT"), ("point_key", "TEXT")], plan.gates),
        oats=_inline([("equipment_id", "TEXT"), ("point_key", "TEXT")], plan.oats),
        ts_ms=TS_MS[engine],
        site_id=_quote(site_id),
        window_filter=window_filter,
        max_gap_ms=int(round(gap * 1000.0)),
        bin_cases=cases,
    )


COLUMNS = ("equipment_id", "tier", "alt", "bin", "on_ms", "valid_ms", "span_ms")


def run_mech_bins_sql(conn: Any, engine: str, plan: Plan, **kwargs: Any) -> list[dict]:
    """One dict per (equipment, OAT bin) with ON time; adds proof labels and the bin label."""
    if not plan.candidates:
        return []
    sql = render_mech_bins_sql(engine, plan, **kwargs)
    if normalize_engine(engine) == "postgres":
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    out = []
    for row in rows:
        rec = dict(zip(COLUMNS, row))
        for k in ("tier", "alt", "bin", "on_ms", "valid_ms", "span_ms"):
            rec[k] = int(rec[k])
        rec["bin_label"] = MECH_OAT_BIN_LABELS[rec["bin"]]
        rec["proof_role"], rec["legacy_proof"], rec["proof_quality"] = plan.labels[
            (rec["equipment_id"], rec["tier"], rec["alt"])
        ]
        out.append(rec)
    return out


def mech_cooling_oat_bins_sql(frames: dict, role_map: dict, *, engine: str = "sqlite"):
    """Individual-device rows of ``mech_cooling_oat_bins`` (metric bins), computed by the SQL query in-process."""
    plan, points, samples, types = plan_from_frames(frames, role_map)
    rows = []
    if plan.candidates:
        conn = _connect(engine)
        try:
            create_core(conn, engine)
            load_core(conn, engine, points, samples)
            rows = run_mech_bins_sql(conn, engine, plan)
        finally:
            conn.close()
    return rows_to_frame(rows, types)


def plan_from_frames(frames: dict, role_map: dict):
    """(plan, core points, core samples, {equipment_id: equipment type}) for pandas frames and a role map."""
    import numpy as np
    import pandas as pd

    from open_fdd.analytics.core import _mech_cooling_type, apply_role_map, resolve_equipment_type
    from open_fdd.analytics.role_map import coerce_role_map

    role_map = coerce_role_map(role_map, frames)
    wanted = set(OAT_ROLES) | set(HP_COOLING_MODE) | set(COMPRESSOR_STAGES)
    for et in ("CHW_PLANT", "AHU", "VRF"):
        for tier in _ladder(et)[0]:
            for alt in tier.alts:
                wanted.update(alt if isinstance(alt, tuple) else (alt,))
    devices, points, samples, types = [], [], [], {}
    for eq_id, raw in frames.items():
        if raw is None or raw.empty or not isinstance(raw.index, pd.DatetimeIndex):
            continue
        raw_type = resolve_equipment_type(eq_id, df=raw, role_map=role_map)
        types[eq_id] = raw_type
        mapped = apply_role_map(raw, eq_id, role_map)
        index = pd.DatetimeIndex(mapped.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        ts_ms = (index.tz_convert("UTC").as_unit("ns").asi8 // 1_000_000).astype("int64")
        roles = {}
        for role in sorted(wanted):
            if role not in mapped.columns:
                continue
            values = pd.to_numeric(mapped[role], errors="coerce").to_numpy(dtype=float)
            ok = ~np.isnan(values)
            if not ok.any():
                continue
            key = f"{eq_id}/{role}"
            roles[role] = key
            points.append({"site_id": DEFAULT_SITE, "point_key": key, "equipment_id": str(eq_id), "role": role})
            samples.extend((DEFAULT_SITE, key, int(t), float(v)) for t, v in zip(ts_ms[ok], values[ok]))
        devices.append((eq_id, _mech_cooling_type(raw_type, eq_id), roles))
    return build_plan(devices), points, samples, types


def rows_to_frame(rows: list[dict], types: Mapping[str, str]):
    """The query's rows as the individual-device columns of ``mech_cooling_oat_bins``."""
    import pandas as pd

    from open_fdd.analytics.core import _OAT_BIN_COLUMNS, _cooling_technology

    out = []
    for r in rows:
        eq_id = r["equipment_id"]
        et = types[eq_id]
        hours = r["on_ms"] / 1000.0 / 3600.0
        valid = r["valid_ms"] / 1000.0 / 3600.0
        span = r["span_ms"] / 1000.0 / 3600.0
        out.append(
            {
                "equipment_id": eq_id,
                "source": f"{eq_id} ({r['legacy_proof']})",
                "source_kind": r["legacy_proof"],
                "series_kind": "individual_device",
                "series_id": eq_id,
                "bin_start": r["bin"],
                "bin_label": r["bin_label"],
                "hours": round(hours, 2),
                "runtime_hours": round(hours, 2),
                "valid_elapsed_hours": round(valid, 2),
                "coverage_pct": round(100.0 * valid / span, 2) if span > 0 else 0.0,
                "equipment_type": et,
                "cooling_technology": _cooling_technology(et, compressor_based=True),
                "proof_role": r["proof_role"],
                "proof_quality": r["proof_quality"],
                "device_count": 1,
            }
        )
    return pd.DataFrame(out, columns=_OAT_BIN_COLUMNS)
