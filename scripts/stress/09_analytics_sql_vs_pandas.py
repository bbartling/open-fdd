#!/usr/bin/env python3
"""Gate G — Analytics SQL ≈ independent pandas on the same samples.

Port of BPS ``09_analytics_sql_vs_pandas.py`` to Open-FDD:
  - ``POST /api/analytics/economizer`` (and related)
  - Comfort via RCx zone comfort / vav-health surfaces when available
  - Independent pandas recompute from SPARQL → point-resolve samples

Fail-closed on truncation and on numeric divergence beyond tolerances. Fewer than
the declared ``--min-*`` comparisons (default 1 each) exits 2 (BLOCKED), never 0.
Analytics numeric fields use relative tolerance ``1e-6`` when ``--si-parity-chain``
is set (see ``si_cutover/parity_chain.ANALYTICS_REL_TOL``). Fault seconds stay exact.
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
    EXIT_BLOCKED,
    EXIT_FAIL,
    EXIT_PASS,
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
    record_check,
    resolve_base_url,
    run_child,
    safe_print,
    wait_until_ready,
)

PCT_TOL = 1e-4
TEMP_TOL = 1e-3
RESID_TOL = 5e-4
SPOT_CHECK_LIMIT = 25
SI_PARITY_ANALYTICS_REL_TOL = 1e-6


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
            value = float(s["val"])
            if math.isfinite(value):
                vals.append(value)
        except (TypeError, ValueError):
            continue
    if not vals:
        return float("nan"), 0
    inside = sum(1 for v in vals if low <= v <= high)
    return 100.0 * inside / len(vals), len(vals)


def _num(pt: dict, *keys: str) -> float | None:
    for key in keys:
        val = pt.get(key)
        if val is None:
            continue
        try:
            out = float(val)
        except (TypeError, ValueError):
            continue
        if math.isfinite(out):
            return out
    return None


def compare_economizer_points(points: list, *, limit: int = SPOT_CHECK_LIMIT) -> tuple[str | None, int]:
    """SQL economizer deltas vs pandas ΔOR/ΔMR. Returns ``(failure, compared)``."""
    checked = 0
    for pt in points[:limit]:
        if not isinstance(pt, dict):
            continue
        oat = _num(pt, "oat_f", "oa_t", "oat")
        rat = _num(pt, "rat_f", "ra_t", "rat")
        mat = _num(pt, "mat_f", "ma_t", "mat")
        dor = _num(pt, "delta_or_c")
        dmr = _num(pt, "delta_mr_f")
        if None in (oat, rat, mat, dor, dmr):
            continue
        exp_or = oat - rat
        exp_mr = mat - rat
        if abs(dor - exp_or) > TEMP_TOL or abs(dmr - exp_mr) > TEMP_TOL:
            return (
                f"economizer deltas: oat={oat} rat={rat} mat={mat} "
                f"sql ΔOR={dor} ΔMR={dmr} vs pandas {exp_or}/{exp_mr}",
                checked,
            )
        resid = _num(pt, "mat_resid_f")
        damper = _num(pt, "oa_damper_pct")
        if resid is not None and damper is not None:
            exp_resid = mat - (rat + damper / 100.0 * exp_or)
            if abs(resid - exp_resid) > RESID_TOL:
                return f"economizer mat_resid: sql={resid} pandas={exp_resid}", checked
        checked += 1
    return None, checked


def verdict(name: str, failure: str | None, compared: int, minimum: int) -> int:
    if failure:
        safe_print(f"FAIL {name}: {failure}")
        return EXIT_FAIL
    if compared < minimum:
        safe_print(
            f"BLOCKED {name}: compared {compared}, need {minimum} "
            "(seed the synthetic pack — zero comparisons is never a pass)"
        )
        return EXIT_BLOCKED
    safe_print(f"PASS {name}: {compared} comparison(s) match pandas")
    record_check(name, True, comparisons=compared)
    return EXIT_PASS


def _check_economizer(http, headers, building_id: str, *, minimum: int) -> int:
    """Compare economizer analytics points vs pandas ΔOR/ΔMR."""
    body = analytics_post(
        http,
        headers,
        "/api/analytics/economizer",
        {"building_id": building_id, "refresh": True},
    )
    env = _unwrap(body)
    points = env.get("points") or env.get("rows") or []
    if not points:
        err = body.get("error") or env.get("note") or "empty points"
        safe_print(f"  economizer unavailable: {err} (seed synthetic pack with OAT/RAT/MAT)")
    else:
        safe_print(f"  economizer engine={env.get('engine')} points={len(points)}")
    failure, checked = compare_economizer_points(points)
    return verdict("economizer", failure, checked, minimum)


def _comfort_for_row(http, headers, building_id: str, row: dict) -> tuple[str | None, int]:
    """Returns ``(failure, compared)`` for one analytics row (compared is 0 or 1)."""
    eid = str(row.get("equipment_id") or "")
    try:
        sql_pct = float(row["comfort_pct"])
    except (KeyError, TypeError, ValueError):
        return None, 0
    if not eid or not math.isfinite(sql_pct):
        return None, 0
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
        return None, 0
    candidates = []
    for p in pts:
        if (p.get("equipmentId") or p.get("equipment_id") or "") != eid:
            continue
        role = (p.get("canonicalRole") or p.get("fddSelection") or "").strip()
        if role in {"zone-air-temp", "zone_t", "zone_air_temp"}:
            col = (p.get("column") or p.get("pointId") or "").strip()
            if col:
                candidates.append(col)
    if len(set(candidates)) != 1:
        safe_print(f"BLOCKED comfort: absent or ambiguous explicit zone temperature role for {eid}")
        return None, 0
    col = candidates[0]
    try:
        samples = _samples_for_key(http, headers, building_id, eid, col)
    except SystemExit as exc:
        return f"comfort samples: {exc}", 0
    low = float(row.get("comfort_low_f", 70.0))
    high = float(row.get("comfort_high_f", 75.0))
    pandas_pct, n = _pandas_comfort_pct(samples, low, high)
    if n == 0 or math.isnan(pandas_pct):
        safe_print(f"WARN comfort: no samples for {eid}/{col}")
        return None, 0
    if row.get("n") != n:
        return f"comfort {eid}: SQL/oracle coverage differs (SQL n={row.get('n')}, oracle n={n})", 0
    if abs(sql_pct - pandas_pct) > PCT_TOL * 100 and abs(sql_pct - pandas_pct) > 0.05:
        # allow 0.05 absolute pct points for Soft-OPEN float noise
        return f"comfort {eid}: sql={sql_pct:.4f} pandas={pandas_pct:.4f} n={n}", 0
    safe_print(f"  comfort {eid}: sql={sql_pct:.4f} ≈ pandas={pandas_pct:.4f} n={n}")
    return None, 1


def _check_comfort(http, headers, building_id: str, *, minimum: int) -> int:
    """comfort_pct vs pandas on zone-air-temp samples for ``minimum`` equipment."""
    compared = 0
    for path in (
        "/api/analytics/vav-health",
        "/api/analytics/rcx/preset",
    ):
        payload: dict = {"building_id": building_id, "refresh": True}
        if path.endswith("preset"):
            payload["series"] = {"preset_id": "zone_comfort_rank"}
        try:
            body = analytics_post(http, headers, path, payload)
        except RuntimeError as exc:
            safe_print(f"WARN {path}: {exc}")
            continue
        env = _unwrap(body)
        rows = env.get("equipment") or env.get("rows") or env.get("points") or []
        if not rows:
            note = env.get("note") or body.get("error")
            safe_print(f"WARN {path}: empty ({note})")
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("comfort_pct") is None:
                continue
            failure, n = _comfort_for_row(http, headers, building_id, row)
            if failure:
                return verdict("comfort", failure, compared, minimum)
            compared += n
            if compared >= minimum:
                return verdict("comfort", None, compared, minimum)
    return verdict("comfort", None, compared, minimum)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    add_connection_args(ap)
    ap.add_argument(
        "--min-economizer-points",
        type=int,
        default=1,
        help="economizer points that must be compared for PASS (>= 1)",
    )
    ap.add_argument(
        "--min-comfort-equipment",
        type=int,
        default=1,
        help="equipment whose comfort_pct must be compared for PASS (>= 1)",
    )
    ap.add_argument(
        "--si-parity-chain",
        action="store_true",
        help="Run offline P0 analytics golden check (relative tol 1e-6)",
    )
    args = ap.parse_args(argv)
    if args.min_economizer_points < 1 or args.min_comfort_equipment < 1:
        ap.error("comparison minimums must be >= 1 (zero comparisons is never a pass)")
    if args.min_economizer_points > SPOT_CHECK_LIMIT:
        ap.error(f"--min-economizer-points cannot exceed the {SPOT_CHECK_LIMIT}-point spot check")
    base = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    args.base_url = base
    building_id = require_building_id(args)

    if find_spec("pandas") is None:
        safe_print("FAIL: pip install pandas required for gate 09")
        return EXIT_FAIL

    banner(
        "Stress 09 — analytics SQL ↔ pandas",
        base_url=base,
        building_id=building_id,
    )
    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)
        codes = [
            _check_economizer(http, headers, building_id, minimum=args.min_economizer_points),
            _check_comfort(http, headers, building_id, minimum=args.min_comfort_equipment),
        ]

    code = combine(codes)
    if code != EXIT_PASS:
        return code
    if args.si_parity_chain:
        from si_cutover import parity_chain as pc  # noqa: E402

        golden = pc.load_ip_golden(pc.IP_GOLDENS_DIR / "SYNTH_SELFTEST.json")
        p0a = pc.compare_p0_analytics_golden(golden)
        if p0a.errors:
            safe_print(f"FAIL si-parity P0 analytics: {'; '.join(p0a.errors)}")
            return EXIT_FAIL
        if p0a.comparisons < 1:
            safe_print("BLOCKED si-parity P0 analytics: zero comparisons")
            return EXIT_BLOCKED
        record_check("si_parity.P0.analytics", True, comparisons=p0a.comparisons)
        safe_print(f"  si-parity P0 analytics: {p0a.comparisons} row(s)")
    return code


def combine(codes: list[int]) -> int:
    if not codes:
        safe_print("\nBLOCKED 09 — no analytics checks ran")
        return EXIT_BLOCKED
    if any(c not in (EXIT_PASS, EXIT_BLOCKED) for c in codes):
        safe_print("\nFAIL 09 — analytics SQL↔pandas divergence")
        return EXIT_FAIL
    if any(c == EXIT_BLOCKED for c in codes):
        safe_print("\nBLOCKED 09 — required analytics comparisons did not run")
        return EXIT_BLOCKED
    safe_print("\nPASS 09 — analytics SQL ↔ pandas")
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(run_child(main, "09_analytics_sql_vs_pandas.py"))
