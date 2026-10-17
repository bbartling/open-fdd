#!/usr/bin/env python3
"""Lesson 03 — SPARQL → point-resolve history → pandas DataFrame → open_fdd.rules.

Proves the teaching path:
  1. POST /api/model/sparql finds AHU + SAT (or discharge-air) points
  2. GET /api/model/point-resolve?include_history=true builds a DF
  3. ``open_fdd.rules.run_rule("FC1", df, …)`` runs locally on that DF

  python scripts/lessons/lesson_03_fc1_dataframe.py \\
    --base-url https://openfdd-web-production.up.railway.app --building-id SYNTH_03

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

# Roles FC1 needs (cookbook / SQL short names after seed).
FC1_ROLES = ("sat", "mat", "oa_t", "rat", "oa_damper_pct", "fan_status")

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
        if "ahu" in blob or "sat" in blob or "mat" in blob:
            counts[eid] = counts.get(eid, 0) + 1
    if not counts:
        raise SystemExit("FAIL: SPARQL returned no AHU-ish equipment for building_id")
    return max(counts, key=counts.get)


def _role_for_column(col: str, sel: str) -> str | None:
    blob = f"{col} {sel}".lower().replace("-", "_")
    aliases = {
        "sat": ("sat", "discharge_air", "da_t", "supply_air_temp"),
        "mat": ("mat", "mixed_air"),
        "oa_t": ("oa_t", "outside_air_temp", "oat"),
        "rat": ("rat", "return_air"),
        "oa_damper_pct": ("oa_damper", "oad", "outside_air_damper"),
        "fan_status": ("fan_status", "fan_stat", "sf_s"),
    }
    for role, keys in aliases.items():
        if any(k in blob for k in keys):
            return role
    # Exact cookbook column already used as openfdd_key suffix.
    if col.lower() in aliases:
        return col.lower()
    return None


def _df_for_ahu(http, headers, building_id: str, equipment_id: str, role_rows: list[dict[str, str]]):
    import pandas as pd

    by_role: dict[str, str] = {}
    for r in role_rows:
        if (r.get("equipmentId") or "").strip() != equipment_id:
            continue
        col = (r.get("column") or r.get("pointId") or "").strip()
        sel = (r.get("fddSelection") or "").strip()
        role = _role_for_column(col, sel)
        if role and role in FC1_ROLES and col and role not in by_role:
            by_role[role] = col
    # Prefer role-named keys when SPARQL is thin (package seed uses role suffixes).
    for role in FC1_ROLES:
        by_role.setdefault(role, role)

    missing = [r for r in FC1_ROLES if r not in by_role]
    if missing:
        raise SystemExit(f"FAIL: could not map FC1 roles {missing}")

    series: dict[str, "pd.Series"] = {}
    for role in FC1_ROLES:
        key = by_role[role]
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
        series[role] = pd.Series([s.get("val") for s in samples], index=idx, name=role)

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
        safe_print(f"  column→role keys={by_role}")

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
    if status in {"ERROR", "SKIP"} and hours == 0.0 and df.isna().all().all():
        safe_print("FAIL: rule could not evaluate (empty/NaN frame)")
        return 2
    safe_print("\nPASS lesson 03 — SPARQL→pandas→open_fdd.rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
