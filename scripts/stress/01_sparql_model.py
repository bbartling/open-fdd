#!/usr/bin/env python3
"""Gate A1 — Haystack RDF: SPARQL synthetic model + package TTL + catalog.

  python scripts/stress/01_sparql_model.py --building-id OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1
  python scripts/stress/01_sparql_model.py --host <lab-ip> --building-id SYNTH_01

Requires a central with package Haystack RDF for ``building_id`` (CSV/package
import that populated semantic_meta / haystack dataset). Soft-OPEN ≠ FQ.
Synthetic sites only.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helpers import (  # noqa: E402
    banner,
    client,
    get_package_ttl,
    get_sparql_catalog,
    login,
    parse_connection,
    post_sparql,
    print_table,
    require_building_id,
    run_child,
    safe_print,
    wait_until_ready,
)

LIST_AHUS = """\
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT DISTINCT ?equip ?equipmentId WHERE {
  ?equip ofdd:equipmentId ?equipmentId .
  {
    ?equip rdf:type phIoT:ahu .
  } UNION {
    ?equip ph:hasTag phIoT:ahu .
  }
}
ORDER BY ?equipmentId
"""

POINT_COUNT = """\
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT (COUNT(?point) AS ?n) WHERE {
  ?point phIoT:equipRef ?equip .
  ?equip ofdd:equipmentId ?equipmentId .
}
"""

REQUIRED_CATALOG_IDS = (
    "equip_by_ahu_class",
    "points_on_equipment",
    "fdd_role_candidates",
)


def main(argv: list[str] | None = None) -> int:
    args = parse_connection(argv)
    base = args.base_url
    building_id = require_building_id(args)
    banner("Stress 01 — SPARQL + package TTL (Haystack RDF)", base_url=base, building_id=building_id)

    with client(base) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)

        # Catalog is JWT and does not require building RDF.
        catalog = get_sparql_catalog(http, headers)
        queries = catalog.get("queries") or []
        ids = {str(q.get("id") or "") for q in queries if isinstance(q, dict)}
        safe_print(f"\nSPARQL catalog status={catalog.get('status')!r}  queries={len(queries)}")
        for need in REQUIRED_CATALOG_IDS:
            if need not in ids:
                safe_print(f"FAIL: missing predefined query_id {need!r}")
                return 1
        safe_print(f"  catalog ids OK: {', '.join(REQUIRED_CATALOG_IDS)}")

        try:
            ahus = post_sparql(http, headers, building_id=building_id, query=LIST_AHUS)
        except RuntimeError as exc:
            safe_print(f"FAIL: SPARQL list AHUs — {exc}")
            safe_print(
                "  Hint: import a synthetic package with Haystack semantic_meta for this building_id"
            )
            return 1
        print_table("AHUs (free-form SPARQL)", ahus)
        equip_ids = {r.get("equipmentId") or r.get("equipment_id") or "" for r in ahus}
        if not any(equip_ids):
            # Template path as second chance (typed bindings flatten differently).
            try:
                ahus_t = post_sparql(
                    http, headers, building_id=building_id, query_id="equip_by_ahu_class"
                )
                print_table("AHUs (template equip_by_ahu_class)", ahus_t)
                equip_ids = {
                    r.get("equipmentId") or r.get("equipment_id") or "" for r in ahus_t
                }
            except RuntimeError as exc:
                safe_print(f"FAIL: template equip_by_ahu_class — {exc}")
                return 1
        if not any(e.strip() for e in equip_ids):
            safe_print(
                "FAIL: no AHU-class equipment in package RDF for this building_id "
                "(seed a synthetic package with stamped ahu equipType / phIoT:ahu)"
            )
            return 1
        safe_print(f"  AHU equipment ids: {sorted(e for e in equip_ids if e)}")

        try:
            counts = post_sparql(http, headers, building_id=building_id, query=POINT_COUNT)
            print_table("Point count", counts)
        except RuntimeError as exc:
            safe_print(f"WARN: point count SPARQL failed ({exc}) — continue")

        # Package TTL (product path). Prefer haystack.ttl; fall back to mapping ttl.
        ttl_ok = False
        for haystack in (True, False):
            label = "haystack.ttl" if haystack else "mapping/ttl"
            try:
                ttl, hdrs = get_package_ttl(
                    http, headers, building_id=building_id, haystack=haystack
                )
            except RuntimeError as exc:
                safe_print(f"WARN: GET package {label} — {exc}")
                continue
            ctype = hdrs.get("content-type", "")
            safe_print(f"\nTTL {label}: {len(ttl)} chars  content-type={ctype!r}")
            if not ttl.strip():
                safe_print(f"WARN: empty TTL body for {label}")
                continue
            # Haystack projection should mention ofdd / building; mapping ttl uses urn:openfdd.
            needles = ("urn:openfdd", "ofdd:", building_id)
            missing = [n for n in needles if n not in ttl]
            if missing and haystack:
                safe_print(f"WARN: {label} missing {missing!r} — checking mapping/ttl next")
                continue
            if "@prefix" not in ttl and "PREFIX" not in ttl and "<urn:openfdd" not in ttl:
                safe_print(f"FAIL: {label} does not look like Turtle/RDF")
                return 1
            ttl_ok = True
            safe_print(f"  TTL OK via {label}")
            break
        if not ttl_ok:
            safe_print("FAIL: no usable package TTL for building_id")
            return 1

    safe_print("\nPASS 01 — Haystack RDF SPARQL + package TTL + catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_child(main, "01_sparql_model.py"))
