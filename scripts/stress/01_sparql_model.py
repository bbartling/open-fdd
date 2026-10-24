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
    record_check,
    ensure_repo_on_path,
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
        record_check("catalog", True)

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
        record_check("sparql_ahu", True)

        try:
            counts = post_sparql(http, headers, building_id=building_id, query=POINT_COUNT)
            print_table("Point count", counts)
        except RuntimeError as exc:
            safe_print(f"WARN: point count SPARQL failed ({exc}) — continue")

        # Parse the actual Haystack projection. A legacy mapping graph, prefix,
        # comment or building-name substring cannot satisfy semantic evidence.
        ensure_repo_on_path()
        from scripts.qualification.semantic.qualify import parse_model, graph_inventory
        try:
            ttl, _hdrs = get_package_ttl(http, headers, building_id=building_id, haystack=True)
            inventory = graph_inventory(parse_model(ttl))
        except ImportError:
            safe_print("BLOCKED: semantic parser dependency unavailable")
            return 2
        except RuntimeError as exc:
            safe_print(f"BLOCKED: Haystack projection unavailable ({exc})")
            return 2
        except (ValueError, SyntaxError):
            safe_print("FAIL: invalid or over-budget Haystack projection")
            return 1
        if inventory["equip_count"] < 1 or inventory["point_count"] < 1:
            safe_print("FAIL: parsed graph has no Haystack equipment/points")
            return 1
        safe_print(f"  Parsed inventory: {inventory['triple_count']} triples, "
                   f"{inventory['equip_count']} equipment, {inventory['point_count']} points")
        record_check("parsed_graph", True)

    safe_print("\nPASS 01 — parsed inventory + SPARQL + catalog (not full semantic qualification)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_child(main, "01_sparql_model.py"))
