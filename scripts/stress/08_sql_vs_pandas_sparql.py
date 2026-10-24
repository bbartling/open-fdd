#!/usr/bin/env python3
"""Gate F — Timescale/registry SQL FDD ≈ pandas via SPARQL→point-resolve DF.

Port of BPS ``08_building50_sql_vs_pandas_sparql.py`` to Open-FDD routes.

Contract (#1253 — quality gap, not equation drift):
  * Product FDD = warehouse/Timescale SQL (no ``open_fdd.quality`` OUT_OF_RANGE
    / sentinel nulling).
  * SQL parity oracle = equation + gate + confirm with ``quality=False``.
  * Full ``run_rule`` (``quality=True``) is a *different* product surface; hour
    deltas vs SQL must be DIAG'ed, never used as the SQL fail criterion.

Flow:
  1. SPARQL discovers AHU + FC1 / SAT roles on package RDF (``ofdd:``)
  2. ``GET /api/model/point-resolve?include_history=true`` → pandas DataFrame
     with Haystack cookbook column names (not SQL short aliases).
  3. pandas oracle locally:
       (A) full ``open_fdd.rules.run_rule`` (quality layer ON)
       (B) SQL-aligned oracle = equation + gate + confirm, quality OFF
  4. ``POST /api/fdd/run`` same rule on product SQL (Timescale Soft-OPEN tip)
  5. Strict: SQL fault_hours ≈ (B) (|Δ| ≤ HOURS_TOL) on the single SQL row
     with exact ``(rule_id, equipment_id)`` identity — no looser fallback
  6. Reconcile: quality-ON oracle on normalized frame ≈ (A)

Fail-closed by default. ``--allow-satdev-drift`` downgrades only AHU-SATDEV
SQL↔oracle mismatch to WARN (lab emergency; do not weaken default).
Missing roles, fewer than ``MIN_SAMPLES`` history rows, or fewer than
``--min-rules`` compared rules exit 2 (BLOCKED); divergence exits 1 (FAIL).

Soft-OPEN ≠ FQ. Synthetic ``--building-id`` only.

  python scripts/stress/08_sql_vs_pandas_sparql.py --building-id SYNTH_01
  python scripts/stress/08_sql_vs_pandas_sparql.py --host <lab-ip> --building-id SYNTH_01
"""

from __future__ import annotations

import argparse
import math
import sys
import warnings
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
    apply_base_url,
    banner,
    client,
    fdd_run,
    login,
    mint_opaque_point_iri,
    point_resolve,
    post_sparql,
    print_table,
    require_building_id,
    record_check,
    resolve_base_url,
    run_child,
    safe_print,
    wait_until_ready,
)

POLL_S = 300.0
HOURS_TOL = 0.05
MIN_SAMPLES = 20


class MissingFixture(Exception):
    """Synthetic fixture lacks roles or history: BLOCKED, never a pass."""

# Canonical Haystack cookbook roles (must match open_fdd RULES_BY_ID columns).
# Short SQL aliases (sat / sat_sp) are warehouse-only — never pandas DF columns.
FC1_ROLES = (
    "duct-static-pressure",
    "duct-static-pressure-sp",
    "fan-cmd",
    "fan-status",
)
SATDEV_ROLES = (
    "discharge-air-temp",
    "discharge-air-temp-sp",
    "fan-status",
    "fan-cmd",
)
DUCTHI_ROLES = ("duct-static-pressure", "duct-static-pressure-sp", "fan-status")


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def _first_ahu(http, headers, building_id: str) -> str | None:
    rows = post_sparql(
        http,
        headers,
        building_id=building_id,
        query_id="equip_by_ahu_class",
    )
    if rows:
        eid = (rows[0].get("equipmentId") or rows[0].get("equipment_id") or "").strip()
        if eid:
            return eid
    rows = post_sparql(
        http,
        headers,
        building_id=building_id,
        query="""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT DISTINCT ?equipmentId WHERE {
  ?equip ofdd:equipmentId ?equipmentId .
  { ?equip rdf:type phIoT:ahu . } UNION { ?equip ph:hasTag phIoT:ahu . }
}
ORDER BY ?equipmentId
LIMIT 1
""",
    )
    return (rows[0].get("equipmentId") or "").strip() if rows else None


def _role_points(http, headers, building_id: str, equipment_id: str) -> list[dict[str, str]]:
    """Points on one equipment via template, then map column→likely role."""
    try:
        rows = post_sparql(
            http,
            headers,
            building_id=building_id,
            query_id="fdd_role_candidates",
            equipment_id=equipment_id,
        )
    except RuntimeError:
        rows = post_sparql(
            http,
            headers,
            building_id=building_id,
            query=f"""
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?equipmentId ?pointId ?column ?fddSelection WHERE {{
  ?point phIoT:equipRef ?equip .
  ?equip ofdd:equipmentId ?equipmentId .
  FILTER(?equipmentId = "{_esc(equipment_id)}")
  OPTIONAL {{ ?point ofdd:pointId ?pointId . }}
  OPTIONAL {{ ?point ofdd:column ?column . }}
  OPTIONAL {{ ?point ofdd:fddSelection ?fddSelection . }}
}}
ORDER BY ?column
""",
            )
    return [
        r for r in rows if (r.get("equipmentId") or r.get("equipment_id") or "") == equipment_id
    ]


def _guess_role(column: str, selection: str, needed: tuple[str, ...]) -> str | None:
    """Map SPARQL column/selection → Haystack cookbook role in ``needed``."""
    sel = (selection or "").strip().lower().replace("_", "-")
    if sel in needed:
        return sel
    exact = {
        "sat": "discharge-air-temp",
        "supply_air_temp": "discharge-air-temp",
        "da_t": "discharge-air-temp",
    }
    for token in (column, selection):
        key = (token or "").strip().lower().replace("-", "_")
        role = exact.get(key)
        if role and role in needed:
            return role
    mapping = [
        ("discharge_air_temp_sp", "discharge-air-temp-sp"),
        ("discharge_air_temp", "discharge-air-temp"),
        ("sat_sp", "discharge-air-temp-sp"),
        ("sat_setpoint", "discharge-air-temp-sp"),
        ("duct_static_pressure_sp", "duct-static-pressure-sp"),
        ("duct_static_sp", "duct-static-pressure-sp"),
        ("duct_static_pressure", "duct-static-pressure"),
        ("duct_static", "duct-static-pressure"),
        ("fan_status", "fan-status"),
        ("fan_cmd", "fan-cmd"),
        ("sf_sts", "fan-status"),
    ]
    tokens = {(token or "").strip().lower().replace("-", "_") for token in (column, selection)}
    for needle, role in mapping:
        if needle in tokens and role in needed:
            return role
    return None


def _build_df_from_resolve(
    http,
    headers,
    *,
    building_id: str,
    equipment_id: str,
    needed: tuple[str, ...],
    role_rows: list[dict[str, str]],
):
    import pandas as pd

    # Map Haystack role → column/point key (DF columns must be cookbook roles).
    by_role: dict[str, str] = {}
    for r in role_rows:
        col = (r.get("column") or r.get("pointId") or "").strip()
        sel = (r.get("fddSelection") or r.get("canonicalRole") or "").strip()
        role = _guess_role(col, sel, needed)
        if role and role in by_role and by_role[role] != col:
            raise MissingFixture(f"ambiguous candidates for {role}; explicit model approval required")
        if role and role in needed and col and role not in by_role:
            by_role[role] = col
    missing = [n for n in needed if n not in by_role]
    if missing:
        raise MissingFixture(
            f"SPARQL missed roles {missing} for {equipment_id} "
            f"(have columns={[r.get('column') for r in role_rows]})"
        )

    series: dict[str, "pd.Series"] = {}
    for role in needed:
        key = by_role[role]
        iri = mint_opaque_point_iri(building_id, equipment_id, key)
        body = point_resolve(http, headers, point_iri=iri, include_history=True, max_points=2000)
        hist = body.get("history") if isinstance(body.get("history"), dict) else {}
        samples = hist.get("samples") or []
        if hist.get("ok") is False:
            raise MissingFixture(f"point-resolve history error for {iri}: {hist.get('error')}")
        max_pts = int(hist.get("max_points") or 2000)
        if len(samples) >= max_pts:
            raise SystemExit(
                f"FAIL-CLOSED: {iri} history truncated at max_points={max_pts}"
            )
        if len(samples) < MIN_SAMPLES:
            raise MissingFixture(
                f"{iri} only {len(samples)} samples (< {MIN_SAMPLES}) — "
                "seed Timescale for synthetic building"
            )
        idx = pd.to_datetime([s["ts"] for s in samples], utc=True)
        vals = [s.get("val") for s in samples]
        series[role] = pd.Series(vals, index=idx, name=role)
    df = pd.DataFrame(series).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < MIN_SAMPLES:
        raise MissingFixture(
            f"{equipment_id} oracle frame has {len(df)} rows (< {MIN_SAMPLES})"
        )
    gaps = df.index.to_series().diff().dropna().dt.total_seconds()
    if not gaps.eq(POLL_S).all():
        raise MissingFixture("this fixed-grid oracle requires complete 300-second cadence; irregular/COV elapsed-time qualification is separate")
    df.attrs.update(equipment_id=equipment_id, equipment_type="ahu", building_id=building_id)
    return df


def _pandas_hours(rule_id: str, df, params: dict, *, gates: bool) -> tuple[float, str, dict]:
    from open_fdd.rules import run_rule

    warnings.filterwarnings("ignore", category=FutureWarning, module=r"open_fdd\.rules")
    res = run_rule(
        rule_id,
        df,
        params=params,
        poll_seconds=POLL_S,
        require_operational_gates=gates,
    )
    metrics = dict(getattr(res, "metrics", None) or {})
    return (
        float(getattr(res, "fault_hours", 0) or 0),
        str(getattr(res, "status", "?")),
        metrics,
    )


def _pandas_hours_sql_semantics(
    rule_id: str, df, params: dict, *, gates: bool, quality: bool
) -> tuple[float, dict]:
    import pandas as pd
    from open_fdd.rules import RULES_BY_ID
    from open_fdd.rules.base import confirm_fault, hours_true
    from open_fdd.rules.operational_gate import resolve_operational_mask

    rule = RULES_BY_ID[rule_id]
    d = df
    qmeta: dict = {}
    if quality:
        from open_fdd.quality import apply_normalized, assess_frame

        fq = assess_frame(d, [c for c in d.columns])
        d = apply_normalized(d, fq, attach_raw_and_flags=False)
        qmeta = {
            "invalid_sample_count": fq.invalid_sample_count,
            "reason_counts": dict(fq.reason_counts),
        }
    full = dict(rule.defaults())
    full.update(params or {})
    confirm_s = float(full.get("confirm_min", rule.confirm_seconds / 60.0)) * 60.0
    active, gate_meta = resolve_operational_mask(
        d, rule_id, poll_seconds=POLL_S, params=full, gate_enabled=gates
    )
    raw = rule.compute(d, full, POLL_S)
    raw = raw.reindex(d.index).fillna(False).astype(bool)
    if gate_meta.get("gate_applied"):
        raw = raw & active.reindex(d.index).fillna(False).astype(bool)
    confirmed = confirm_fault(raw, poll_seconds=POLL_S, confirm_seconds=confirm_s)
    meta = {
        "gate_source": gate_meta.get("gate_source"),
        "gate_applied": bool(gate_meta.get("gate_applied")),
        "fault_samples": int(confirmed.sum()),
        "quality": qmeta,
    }
    return float(hours_true(pd.Series(confirmed, index=d.index), POLL_S)), meta


def compare_sql_to_oracle(
    results: list, rule_id: str, equipment_id: str, oracle_hours: float
) -> tuple[str, float | None, str]:
    """Judge one rule on exact ``(rule_id, equipment_id)`` identity.

    Returns ``(status, sql_hours, message)`` with status PASS / FAIL / BLOCKED.
    A row for other equipment never stands in, even with identical fault-hours.
    """
    rows = [r for r in results if isinstance(r, dict)]
    if not rows:
        return "BLOCKED", None, f"no SQL result rows for {rule_id}/{equipment_id}"
    hits = [
        r
        for r in rows
        if str(r.get("rule_id")) == rule_id and str(r.get("equipment_id")) == equipment_id
    ]
    if not hits:
        seen = sorted({(str(r.get("rule_id")), str(r.get("equipment_id"))) for r in rows})
        return "FAIL", None, f"no SQL row with identity ({rule_id}, {equipment_id}); got {seen}"
    if len(hits) > 1:
        return "FAIL", None, f"{len(hits)} SQL rows share identity ({rule_id}, {equipment_id})"
    if hits[0].get("status") not in {"PASS", "FAULT"}:
        return "FAIL", None, f"{rule_id}/{equipment_id} was not a successful diagnostic evaluation"
    raw = hits[0].get("fault_hours")
    try:
        s_hours = float(raw)
    except (TypeError, ValueError):
        return "FAIL", None, f"{rule_id}/{equipment_id} SQL fault_hours={raw!r} is not numeric"
    if not math.isfinite(s_hours) or s_hours < 0 or not math.isfinite(oracle_hours) or oracle_hours < 0:
        return "FAIL", s_hours, f"{rule_id}/{equipment_id} SQL fault_hours={s_hours} not finite"
    if math.isclose(oracle_hours, s_hours, abs_tol=HOURS_TOL):
        return "PASS", s_hours, f"{rule_id}/{equipment_id} SQL≈pandas (|Δ|≤{HOURS_TOL})"
    return (
        "FAIL",
        s_hours,
        f"{rule_id}/{equipment_id} SQL fault_hours={s_hours:.4f} "
        f"vs pandas SQL-aligned={oracle_hours:.4f}",
    )


def _checks(equipment_id: str) -> list[dict]:
    return [
        {
            "rule_id": "FC1",
            "equipment_id": equipment_id,
            "needed": FC1_ROLES,
            "sql_params": {"confirm_min": 0, "mode_delay_min": 0, "startup_delay_min": 0},
            "pandas_params": {"confirm_min": 0, "mode_delay_min": 0, "startup_delay_min": 0},
            "pandas_gates": False,
        },
        {
            "rule_id": "AHU-DUCTHI",
            "equipment_id": equipment_id,
            "needed": DUCTHI_ROLES,
            "sql_params": {"confirm_min": 0, "startup_delay_min": 0},
            "pandas_params": {"confirm_min": 0, "startup_delay_min": 0},
            "pandas_gates": False,
        },
        {
            "rule_id": "AHU-SATDEV",
            "equipment_id": equipment_id,
            "needed": SATDEV_ROLES,
            "sql_params": {"confirm_min": 0, "startup_delay_min": 0},
            "pandas_params": {"confirm_min": 0, "startup_delay_min": 0},
            "pandas_gates": True,
        },
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    add_connection_args(ap)
    ap.add_argument(
        "--allow-satdev-drift",
        action="store_true",
        help="WARN-only for AHU-SATDEV SQL↔oracle mismatch (lab emergency; see #1253)",
    )
    ap.add_argument("--equipment-id", default=None, help="AHU equipment_id (default: SPARQL first)")
    ap.add_argument(
        "--min-rules",
        type=int,
        default=len(_checks("")),
        help="exact-identity SQL↔pandas rule comparisons required for PASS (>= 1; default all)",
    )
    args = ap.parse_args(argv)
    if args.min_rules < 1:
        ap.error("--min-rules must be >= 1 (zero comparisons is never a pass)")
    base = apply_base_url(
        resolve_base_url(base_url=args.base_url, host=args.host, port=args.port)
    )
    args.base_url = base
    building_id = require_building_id(args)

    if find_spec("open_fdd") is None or find_spec("pandas") is None:
        safe_print(
            "FAIL: need pandas + open-fdd[oracle] for gate 08 "
            "(pip install pandas 'open-fdd[oracle]')"
        )
        return 1

    banner(
        "Stress 08 — SQL FDD ↔ pandas via SPARQL/point-resolve",
        base_url=base,
        building_id=building_id,
    )

    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)
        try:
            equipment_id = (args.equipment_id or "").strip() or _first_ahu(
                http, headers, building_id
            )
            if not equipment_id:
                safe_print("BLOCKED: no AHU equipment in package RDF")
                return EXIT_BLOCKED
            safe_print(f"  equipment_id={equipment_id}")
            role_rows = _role_points(http, headers, building_id, equipment_id)
        except RuntimeError as exc:
            safe_print(f"FAIL: precondition: {exc}")
            return 1
        print_table("Role candidate points", role_rows, limit=30)

        if not role_rows:
            safe_print(f"BLOCKED: no role candidate points on {equipment_id}")
            return EXIT_BLOCKED

        failures = 0
        blocked = 0
        compared = 0
        for check in _checks(equipment_id):
            rid = check["rule_id"]
            safe_print("\n" + "-" * 50)
            safe_print(f"Rule {rid}")
            try:
                df = _build_df_from_resolve(
                    http,
                    headers,
                    building_id=building_id,
                    equipment_id=equipment_id,
                    needed=check["needed"],
                    role_rows=role_rows,
                )
            except MissingFixture as exc:
                safe_print(f"BLOCKED {rid}: {exc}")
                blocked += 1
                continue
            except (SystemExit, RuntimeError) as exc:
                safe_print(f"FAIL {rid}: {exc}")
                failures += 1
                continue

            safe_print(f"  DataFrame shape={df.shape} cols={list(df.columns)}")
            want_gates = bool(check["pandas_gates"])
            p_hours, p_status, p_metrics = _pandas_hours(
                rid, df, check["pandas_params"], gates=want_gates
            )
            safe_print(
                f"  pandas [quality ON]: status={p_status} fault_hours={p_hours:.4f} "
                f"gate={p_metrics.get('gate_source')}"
            )
            o_hours, o_meta = _pandas_hours_sql_semantics(
                rid, df, check["pandas_params"], gates=want_gates, quality=False
            )
            safe_print(
                f"  pandas [SQL-aligned, quality OFF]: fault_hours={o_hours:.4f} "
                f"fault_samples={o_meta['fault_samples']}"
            )
            q_hours, q_meta = _pandas_hours_sql_semantics(
                rid, df, check["pandas_params"], gates=want_gates, quality=True
            )
            quality_delta = o_hours - q_hours
            if abs(quality_delta) > HOURS_TOL:
                safe_print(
                    f"  DIAG {rid}: quality layer removes {quality_delta:.3f} fault-h "
                    f"(#1253) reason_counts={(q_meta.get('quality') or {}).get('reason_counts')}"
                )
            if not math.isclose(q_hours, p_hours, abs_tol=HOURS_TOL):
                safe_print(
                    f"FAIL: {rid} reconciliation broken — oracle(quality ON)={q_hours:.4f} "
                    f"vs run_rule={p_hours:.4f}"
                )
                failures += 1
                continue

            run_body = fdd_run(
                http,
                headers,
                building_id=building_id,
                rule_ids=[rid],
                equipment_id=equipment_id,
                params={rid: check["sql_params"]},
                force_new_data=True,
            )
            if not run_body.get("ok"):
                safe_print(f"FAIL: /api/fdd/run {rid}: {run_body.get('error')}")
                failures += 1
                continue
            status, s_hours, msg = compare_sql_to_oracle(
                run_body.get("results") or [], rid, equipment_id, o_hours
            )
            if s_hours is not None:
                safe_print(
                    f"  SQL FDD: fault_hours={s_hours:.4f} engine={run_body.get('engine')}"
                )
            if status == "PASS":
                safe_print(f"PASS {msg}")
                compared += 1
                record_check(f"oracle.{rid}", True, comparisons=1)
                continue
            if status == "BLOCKED":
                safe_print(f"BLOCKED {msg}")
                blocked += 1
                continue
            msg = f"{msg} (runner quality ON={p_hours:.4f})"
            if rid == "AHU-SATDEV" and s_hours is not None and args.allow_satdev_drift:
                safe_print(
                    f"WARN (--allow-satdev-drift): {msg} — likely #1253 quality-layer gap"
                )
                # A waived mismatch is diagnostic evidence, never strict parity.
                blocked += 1
                continue
            if rid == "AHU-SATDEV" and abs(quality_delta) > HOURS_TOL:
                safe_print(
                    f"FAIL: {msg} — quality layer delta {quality_delta:+.3f}h "
                    "(do not weaken; track #1253)"
                )
            else:
                safe_print(f"FAIL: {msg}")
            failures += 1

    if failures:
        safe_print(f"\nFAIL 08 — {failures} rule divergence(s) (fail-closed)")
        return EXIT_FAIL
    if blocked or compared < args.min_rules:
        safe_print(
            f"\nBLOCKED 08 — compared {compared} rule(s), need {args.min_rules}; "
            f"{blocked} blocked (seed the synthetic fixture)"
        )
        return EXIT_BLOCKED
    safe_print(f"\nPASS 08 — SQL FDD ↔ pandas via SPARQL (strict, {compared} rules)")
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(run_child(main, "08_sql_vs_pandas_sparql.py"))
