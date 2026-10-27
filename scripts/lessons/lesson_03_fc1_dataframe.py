#!/usr/bin/env python3
"""Lesson 03 — SPARQL → point-resolve history → pandas DataFrame → open_fdd.rules.

Proves the teaching path:
  1. POST /api/model/sparql finds AHU + FC1 points
  2. GET /api/model/point-resolve?include_history=true builds a DF
  3. ``open_fdd.rules.run_rule("FC1", df, …)`` runs locally on that DF

FC1 (GL36 A) required open_fdd columns:
  duct-static-pressure, duct-static-pressure-sp, fan-cmd

Package seed short keys (opaque IRI suffix) are usually:
  duct_static, duct_static_sp, fan_cmd

  python scripts/lessons/lesson_03_fc1_dataframe.py \\
    --base-url http://127.0.0.1:8080 --building-id SYNTH_03

Requires: ``pip install pandas open-fdd``. Soft-OPEN ≠ FQ. Synthetic sites only.
"""

from __future__ import annotations

import sys
import warnings
from importlib.util import find_spec
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lesson_helpers import (  # noqa: E402
    banner,
    client,
    login,
    mint_opaque_point_iri,
    parse_connection,
    point_resolve,
    post_sparql,
    print_table,
    require_building_id,
    safe_print,
    wait_until_ready,
)

# open_fdd cookbook role → package history key candidates (first hit wins).
FC1_OPENFDD_TO_KEYS: dict[str, tuple[str, ...]] = {
    "duct-static-pressure": (
        "duct_static",
        "duct-static-pressure",
        "duct_static_pressure",
        "dsp",
    ),
    "duct-static-pressure-sp": (
        "duct_static_sp",
        "duct-static-pressure-sp",
        "duct_static_pressure_sp",
        "dsp_sp",
    ),
    "fan-cmd": ("fan_cmd", "fan-cmd", "sf_cmd", "supply_fan_cmd"),
}

POINTS_RQ = """\
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?equipmentId ?pointId ?column ?fddSelection WHERE {
  ?point phIoT:equipRef ?equip .
  ?equip ofdd:equipmentId ?equipmentId .
  OPTIONAL { ?point ofdd:pointId ?pointId . }
  OPTIONAL { ?point ofdd:column ?column . }
  OPTIONAL { ?point ofdd:fddSelection ?fddSelection . }
}
ORDER BY ?equipmentId ?column
LIMIT 200
"""


def _need_pandas() -> None:
    if find_spec("pandas") is None or find_spec("open_fdd") is None:
        raise SystemExit(
            "FAIL: need pandas + open-fdd — pip install pandas open-fdd"
        )


def _pick_ahu(rows: list[dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        eid = (r.get("equipmentId") or "").strip()
        if not eid:
            continue
        blob = " ".join(
            [
                eid.lower(),
                (r.get("column") or "").lower(),
                (r.get("fddSelection") or "").lower(),
                (r.get("pointId") or "").lower(),
            ]
        )
        if "ahu" in blob or "duct_static" in blob or "fan_cmd" in blob:
            counts[eid] = counts.get(eid, 0) + 1
    if not counts:
        raise SystemExit("FAIL: SPARQL returned no AHU-ish equipment for building_id")
    return max(counts, key=counts.get)


def _norm(s: str) -> str:
    return s.lower().replace("-", "_")


def _resolve_package_key(
    openfdd_role: str, equipment_id: str, role_rows: list[dict[str, str]]
) -> str:
    """Map open_fdd FC1 role → package column / pointId used in opaque IRI."""
    candidates = FC1_OPENFDD_TO_KEYS[openfdd_role]
    avail: list[str] = []
    for r in role_rows:
        if (r.get("equipmentId") or "").strip() != equipment_id:
            continue
        for field in ("column", "pointId", "fddSelection"):
            v = (r.get(field) or "").strip()
            if v:
                avail.append(v)
    # Exact / alias match against SPARQL columns first.
    for cand in candidates:
        cn = _norm(cand)
        for a in avail:
            if _norm(a) == cn or cn in _norm(a):
                # Prefer package short key (underscore) when SPARQL has it.
                return a if "_" in a or "-" not in a else cand
    # Package seed defaults (SYNTH_03 / openfdd_package_v1).
    return candidates[0]


def _df_for_ahu(http, headers, building_id: str, equipment_id: str, role_rows: list[dict[str, str]]):
    import pandas as pd

    by_role: dict[str, str] = {}
    for openfdd_role in FC1_OPENFDD_TO_KEYS:
        by_role[openfdd_role] = _resolve_package_key(openfdd_role, equipment_id, role_rows)

    series: dict[str, "pd.Series"] = {}
    for openfdd_role, key in by_role.items():
        iri = mint_opaque_point_iri(building_id, equipment_id, key)
        body = point_resolve(
            http, headers, point_iri=iri, include_history=True, max_points=2000
        )
        hist = body.get("history") if isinstance(body.get("history"), dict) else {}
        samples = hist.get("samples") or []
        if hist.get("ok") is False:
            raise SystemExit(f"FAIL: history error for {iri}: {hist.get('error')}")
        if len(samples) < 10:
            raise SystemExit(
                f"FAIL: {iri} only {len(samples)} samples — need Timescale history"
            )
        idx = pd.to_datetime([s["ts"] for s in samples], utc=True)
        series[openfdd_role] = pd.Series(
            [s.get("val") for s in samples], index=idx, name=openfdd_role
        )

    df = pd.DataFrame(series).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.attrs.update(
        equipment_id=equipment_id, equipment_type="ahu", building_id=building_id
    )
    return df, by_role


def main(argv: list[str] | None = None) -> int:
    _need_pandas()
    args = parse_connection(argv)
    building_id = require_building_id(args)
    banner(
        "Lesson 03 — SPARQL → pandas DF → open_fdd.rules FC1",
        base_url=args.base_url,
        building_id=building_id,
    )

    with client(args.base_url) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)
        rows = post_sparql(http, headers, building_id=building_id, query=POINTS_RQ)
        print_table("SPARQL points (sample)", rows, limit=12)
        if not rows:
            safe_print("FAIL: empty SPARQL — import package with semantic_meta / RDF")
            return 2
        equipment_id = _pick_ahu(rows)
        safe_print(f"  equipment_id={equipment_id}")
        df, by_role = _df_for_ahu(http, headers, building_id, equipment_id, rows)
        safe_print(
            f"  dataframe shape={df.shape} roles={list(df.columns)} "
            f"span={df.index.min()} → {df.index.max()}"
        )
        safe_print(f"  openfdd_role→package_key={by_role}")

    from open_fdd.rules import run_rule

    warnings.filterwarnings("ignore", category=FutureWarning, module=r"open_fdd\.rules")
    res = run_rule(
        "FC1",
        df,
        params={"confirm_min": 0, "mode_delay_min": 0, "startup_delay_min": 0},
        poll_seconds=300.0,
        require_operational_gates=False,
    )
    hours = float(getattr(res, "fault_hours", 0) or 0)
    status = str(getattr(res, "status", "?"))
    safe_print(f"  open_fdd.rules FC1 status={status} fault_hours={hours:.4f}")
    if status in {"ERROR", "SKIP", "SKIPPED_MISSING_ROLES"} or (
        status.startswith("SKIP") and "MISSING" in status
    ):
        safe_print("FAIL: FC1 did not evaluate (missing roles / skip)")
        return 2
    if df.isna().all().all():
        safe_print("FAIL: rule could not evaluate (empty/NaN frame)")
        return 2
    safe_print("\nPASS lesson 03 — SPARQL→pandas→open_fdd.rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
