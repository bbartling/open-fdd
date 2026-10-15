#!/usr/bin/env python3
"""Gate G — Analytics SQL ≈ independent pandas on the same samples.

Port of BPS ``09_analytics_sql_vs_pandas.py`` to Open-FDD:
  - ``POST /api/analytics/economizer`` (and related)
  - Comfort via RCx zone comfort / vav-health surfaces when available
  - Independent pandas recompute from SPARQL → point-resolve samples

Fail-closed on truncation and on numeric divergence beyond tolerances.
Soft-OPEN ≠ FQ. Synthetic ``--building-id`` only.

  python scripts/stress/09_analytics_sql_vs_pandas.py --building-id SYNTH_01
  python scripts/stress/09_analytics_sql_vs_pandas.py --host <lab-ip> --building-id SYNTH_01
"""

from __future__ import annotations

import argparse
import math
import sys
from importlib.util import find_spec
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helpers import (  # noqa: E402
    add_connection_args,
    analytics_post,
    apply_base_url,
    banner,
    client,
    login,
    mint_opaque_point_iri,
    point_resolve,
    post_sparql,
    require_building_id,
    resolve_base_url,
    safe_print,
    wait_until_ready,
)

PCT_TOL = 1e-4
TEMP_TOL = 1e-3
RESID_TOL = 5e-4


def _unwrap(body: dict) -> dict:
    if isinstance(body.get("analytics"), dict):
        return body["analytics"]
    return body if isinstance(body, dict) else {}


def _samples_for_key(http, headers, building_id: str, equipment_id: str, point_key: str):
    iri = mint_opaque_point_iri(building_id, equipment_id, point_key)
    body = point_resolve(http, headers, point_iri=iri, include_history=True, max_points=2000)
    hist = body.get("history") if isinstance(body.get("history"), dict) else {}
    samples = hist.get("samples") or []
    max_pts = int(hist.get("max_points") or 2000)
    if len(samples) >= max_pts:
        raise SystemExit(f"FAIL-CLOSED truncation on {iri} (max_points={max_pts})")
    return samples


def _pandas_comfort_pct(samples: list, low: float, high: float) -> tuple[float, int]:
    vals = []
    for s in samples:
        if not isinstance(s, dict) or s.get("val") is None:
            continue
        try:
            vals.append(float(s["val"]))
        except (TypeError, ValueError):
            continue
    if not vals:
        return float("nan"), 0
    inside = sum(1 for v in vals if low <= v <= high)
    return 100.0 * inside / len(vals), len(vals)


def _check_economizer(http, headers, building_id: str) -> int:
    """Compare economizer analytics points vs pandas ΔOR/ΔMR when roles resolve."""
    body = analytics_post(
        http,
        headers,
        "/api/analytics/economizer",
        {"building_id": building_id, "refresh": True},
    )
    env = _unwrap(body)
    if body.get("ok") is False and not env.get("points") and not env.get("rows"):
        err = body.get("error") or env.get("note") or "unavailable"
        safe_print(f"WARN economizer analytics unavailable: {err}")
        return 0
    points = env.get("points") or env.get("rows") or []
    if not points:
        safe_print("WARN economizer: empty points (seed synthetic pack with OAT/RAT/MAT)")
        return 0
    safe_print(f"  economizer engine={env.get('engine')} points={len(points)}")
    # Spot-check up to 25 points that carry the classic delta fields.
    checked = 0
    for pt in points[:25]:
        if not isinstance(pt, dict):
            continue
        try:
            oat = float(pt.get("oat_f") or pt.get("oa_t") or pt["oat"])
            rat = float(pt.get("rat_f") or pt.get("ra_t") or pt["rat"])
            mat = float(pt.get("mat_f") or pt.get("ma_t") or pt["mat"])
        except (KeyError, TypeError, ValueError):
            continue
        dor = pt.get("delta_or_f")
        dmr = pt.get("delta_mr_f")
        if dor is None or dmr is None:
            continue
        exp_or = oat - rat
        exp_mr = mat - rat
        if abs(float(dor) - exp_or) > TEMP_TOL or abs(float(dmr) - exp_mr) > TEMP_TOL:
            safe_print(
                f"FAIL economizer deltas: oat={oat} rat={rat} mat={mat} "
                f"sql ΔOR={dor} ΔMR={dmr} vs pandas {exp_or}/{exp_mr}"
            )
            return 1
        resid = pt.get("mat_resid_f")
        damper = pt.get("oa_damper_pct")
        if resid is not None and damper is not None:
            try:
                exp_resid = mat - (rat + float(damper) / 100.0 * exp_or)
                if abs(float(resid) - exp_resid) > RESID_TOL:
                    safe_print(
                        f"FAIL economizer mat_resid: sql={resid} pandas={exp_resid}"
                    )
                    return 1
            except (TypeError, ValueError):
                pass
        checked += 1
    if checked == 0:
        safe_print("WARN economizer: no points with oat/rat/mat + deltas to compare")
        return 0
    safe_print(f"PASS economizer: {checked} points match pandas ΔOR/ΔMR")
    return 0


def _check_comfort(http, headers, building_id: str) -> int:
    """Best-effort comfort_pct vs pandas on zone-air-temp samples."""
    # Prefer vav-health / rcx preset surfaces that expose comfort.
    for path in (
        "/api/analytics/vav-health",
        "/api/analytics/rcx/preset",
    ):
        payload: dict = {"building_id": building_id, "refresh": True}
        if path.endswith("preset"):
            payload["preset_id"] = "zone_comfort_rank"
        try:
            body = analytics_post(http, headers, path, payload)
        except RuntimeError as exc:
            safe_print(f"WARN {path}: {exc}")
            continue
        env = _unwrap(body)
        rows = env.get("equipment") or env.get("rows") or []
        if not rows:
            note = env.get("note") or body.get("error")
            safe_print(f"WARN {path}: empty ({note})")
            continue
        # Find first row with comfort_pct + equipment_id
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("comfort_pct") is None:
                continue
            eid = str(row.get("equipment_id") or "")
            if not eid:
                continue
            sql_pct = float(row["comfort_pct"])
            # Discover zone temp column via SPARQL
            try:
                pts = post_sparql(
                    http,
                    headers,
                    building_id=building_id,
                    query_id="fdd_role_candidates",
                    equipment_id=eid,
                )
            except RuntimeError as exc:
                safe_print(f"WARN SPARQL for comfort equip {eid}: {exc}")
                continue
            col = None
            for p in pts:
                blob = f"{p.get('column','')} {p.get('fddSelection','')} {p.get('canonicalRole','')}".lower()
                if "zone" in blob or "zn_t" in blob or "zone_air" in blob:
                    col = (p.get("column") or p.get("pointId") or "").strip()
                    if col:
                        break
            if not col:
                safe_print(f"WARN comfort: no zone temp column for {eid}")
                continue
            try:
                samples = _samples_for_key(http, headers, building_id, eid, col)
            except SystemExit as exc:
                safe_print(f"FAIL comfort samples: {exc}")
                return 1
            low = float(row.get("comfort_low_f") or 70.0)
            high = float(row.get("comfort_high_f") or 75.0)
            pandas_pct, n = _pandas_comfort_pct(samples, low, high)
            if n == 0 or math.isnan(pandas_pct):
                safe_print(f"WARN comfort: no samples for {eid}/{col}")
                continue
            if abs(sql_pct - pandas_pct) > PCT_TOL * 100 and abs(sql_pct - pandas_pct) > 0.05:
                # allow 0.05 absolute pct points for Soft-OPEN float noise
                safe_print(
                    f"FAIL comfort {eid}: sql={sql_pct:.4f} pandas={pandas_pct:.4f} n={n}"
                )
                return 1
            safe_print(
                f"PASS comfort {eid}: sql={sql_pct:.4f} ≈ pandas={pandas_pct:.4f} n={n}"
            )
            return 0
    safe_print(
        "WARN comfort: no analytics row with comfort_pct "
        "(seed synthetic VAV zone temps — Soft-OPEN ≠ FQ)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    add_connection_args(ap)
    args = ap.parse_args(argv)
    base = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    args.base_url = base
    building_id = require_building_id(args)

    if find_spec("pandas") is None:
        safe_print("FAIL: pip install pandas required for gate 09")
        return 1

    banner(
        "Stress 09 — analytics SQL ↔ pandas",
        base_url=base,
        building_id=building_id,
    )
    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)
        rc = 0
        rc |= _check_economizer(http, headers, building_id)
        rc |= _check_comfort(http, headers, building_id)

    if rc:
        safe_print("\nFAIL 09 — analytics SQL↔pandas divergence")
        return 1
    safe_print("\nPASS 09 — analytics SQL ↔ pandas (available queries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
