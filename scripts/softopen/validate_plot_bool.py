#!/usr/bin/env python3
"""Soft-OPEN plot bool gate — no screenshots, no token burn.

Uses SPARQL/RDF + package mapping to pick AHU equipment that the model supports,
runs applicable FDD rules, then asserts:

  * GET /api/fdd/plot → point_count > 0 (or explicit SKIP_MISSING_ROLES / no samples)
  * POST /api/analytics/runtime (RCx motor weekly) → non-empty rows when samples exist

BUILDING_100 / SYNTH / SOFTOPEN_* only. Soft-OPEN ≠ FQ.

  python scripts/softopen/validate_plot_bool.py --host <hub> --building-id BUILDING_100
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_STRESS = Path(__file__).resolve().parents[1] / "stress"
if str(_STRESS) not in sys.path:
    sys.path.insert(0, str(_STRESS))

from helpers import (  # noqa: E402
    analytics_post,
    banner,
    client,
    fdd_equipment,
    fdd_plot,
    fdd_results,
    fdd_run,
    login,
    parse_connection,
    post_sparql,
    print_table,
    require_building_id,
    safe_print,
    wait_until_ready,
)

# Rules that fit a typical AHU RDF/package model (type-first Soft-OPEN).
AHU_RULES = ("FC1", "AHU-SATDEV", "AHU-DUCTHI")

LIST_AHU = """
PREFIX ofdd: <urn:openfdd:vocab/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?equip ?label WHERE {
  ?equip a ofdd:Equip .
  OPTIONAL { ?equip rdfs:label ?label }
}
LIMIT 50
"""


def _equip_ids_from_sparql(rows: list[dict[str, str]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        for key in ("equip", "equipment", "equipment_id", "id"):
            raw = (row.get(key) or "").strip()
            if not raw:
                continue
            # IRI …/equip/AHU_1 → AHU_1
            if "/equip/" in raw:
                raw = raw.rsplit("/equip/", 1)[-1]
            if raw and raw not in out:
                out.append(raw)
            break
    return out


def _ahu_from_inventory(equip_body: dict[str, Any]) -> list[str]:
    rows = equip_body.get("equipment") or []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("equipment_id") or "")
        et = str(row.get("equipment_type") or row.get("equipment_type_raw") or "").lower()
        if not eid:
            continue
        if et in {"ahu", "vav ahu", "cv ahu", "rtu", "air"} or "ahu" in et:
            out.append(eid)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Soft-OPEN FDD/RCx plot bool gate (no screenshots)")
    # parse_connection owns --host/--base-url/--building-id
    args = parse_connection(argv)
    # Re-parse known extras without fighting connection flags.
    extra = argparse.ArgumentParser(add_help=False)
    extra.add_argument("--equipment-id", default=None)
    more, _ = extra.parse_known_args(argv)
    args.equipment_id = more.equipment_id
    building_id = require_building_id(args)
    banner("Soft-OPEN plot bool", base_url=args.base_url, building_id=building_id)

    matrix: list[dict[str, str]] = []
    fail = 0

    with client(args.base_url) as http:
        health = wait_until_ready(http)
        safe_print(
            f"  version={health.get('version')} historian={health.get('historian')}"
        )
        headers = login(http, user=args.user, password=args.password)

        sparql_rows = post_sparql(http, headers, building_id=building_id, query=LIST_AHU)
        sparql_ids = _equip_ids_from_sparql(sparql_rows)
        inv = fdd_equipment(http, headers, building_id=building_id)
        ahu_ids = _ahu_from_inventory(inv) or sparql_ids
        equipment_id = (args.equipment_id or "").strip() or (ahu_ids[0] if ahu_ids else "")
        if not equipment_id:
            safe_print("FAIL: no AHU equipment from RDF inventory / SPARQL")
            return 2
        safe_print(f"  equipment_id={equipment_id} (model-selected)")

        # Run applicable AHU rules once.
        run_body = fdd_run(
            http,
            headers,
            building_id=building_id,
            rule_ids=list(AHU_RULES),
            equipment_id=equipment_id,
            force_new_data=True,
        )
        if run_body.get("ok") is False:
            safe_print(f"FAIL: fdd/run ok=false error={run_body.get('error')}")
            fail += 1
        results = fdd_results(http, headers, building_id=building_id)
        result_rows = results.get("results") or []

        for rule_id in AHU_RULES:
            row = next(
                (
                    r
                    for r in result_rows
                    if str(r.get("rule_id")) == rule_id
                    and str(r.get("equipment_id")) == equipment_id
                ),
                None,
            )
            status = str((row or {}).get("status") or "MISSING")
            if status.upper().startswith("NOT_APPLICABLE"):
                matrix.append(
                    {
                        "check": f"fdd_plot:{rule_id}",
                        "result": "N/A",
                        "detail": status,
                    }
                )
                continue
            plot = fdd_plot(
                http,
                headers,
                building_id=building_id,
                equipment_id=equipment_id,
                rule_id=rule_id,
            )
            pts = int(plot.get("point_count") or 0)
            ok = plot.get("ok") is not False and pts > 0
            if ok:
                matrix.append(
                    {
                        "check": f"fdd_plot:{rule_id}",
                        "result": "PASS",
                        "detail": f"point_count={pts}",
                    }
                )
            else:
                # Mapped-but-empty historian is a FAIL for Soft-OPEN reference sites.
                detail = plot.get("note") or plot.get("error") or f"point_count={pts}"
                matrix.append(
                    {
                        "check": f"fdd_plot:{rule_id}",
                        "result": "FAIL",
                        "detail": str(detail)[:120],
                    }
                )
                fail += 1

        # RCx motor weekly — bool non-empty rows when historian has AHU samples.
        runtime = analytics_post(
            http,
            headers,
            "/api/analytics/runtime",
            {"building_id": building_id, "max_points": 4000},
        )
        rt_rows = runtime.get("rows") or []
        if rt_rows:
            matrix.append(
                {
                    "check": "rcx_runtime",
                    "result": "PASS",
                    "detail": f"rows={len(rt_rows)}",
                }
            )
        else:
            # Empty is FAIL only when FDD plot already proved samples exist.
            any_plot_pass = any(m["result"] == "PASS" for m in matrix)
            if any_plot_pass:
                matrix.append(
                    {
                        "check": "rcx_runtime",
                        "result": "FAIL",
                        "detail": "empty rows while FDD plots had points",
                    }
                )
                fail += 1
            else:
                matrix.append(
                    {
                        "check": "rcx_runtime",
                        "result": "FAIL",
                        "detail": "empty — no Timescale samples for plant motors",
                    }
                )
                fail += 1

    print_table("plot bool matrix", matrix, limit=50)
    if fail:
        safe_print(f"\nFAIL Soft-OPEN plot bool ({fail} checks)")
        return 2
    safe_print("\nPASS Soft-OPEN plot bool")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
