#!/usr/bin/env python3
"""Lesson 01 — health + SPARQL list AHU-class equipment (Open-FDD Soft-OPEN).

  python scripts/lessons/lesson_01_sites_and_equipment.py --building-id SYNTH_01
  python scripts/lessons/lesson_01_sites_and_equipment.py --host <lab-ip> --building-id SYNTH_01

Synthetic building_id only. Soft-OPEN ≠ FQ.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lesson_helpers import (  # noqa: E402
    banner,
    client,
    login,
    parse_connection,
    post_sparql,
    print_table,
    require_building_id,
    safe_print,
    wait_until_ready,
)

LIST_AHUS = (_HERE / "sparql" / "01_list_ahu_equip.rq").read_text(encoding="utf-8")
# Strip comment lines for the API body.
LIST_AHUS = "\n".join(
    line for line in LIST_AHUS.splitlines() if not line.strip().startswith("#")
)


def main(argv: list[str] | None = None) -> int:
    args = parse_connection(argv)
    building_id = require_building_id(args)
    banner("Lesson 01 — sites / AHU equipment via SPARQL", base_url=args.base_url, building_id=building_id)
    with client(args.base_url) as http:
        health = wait_until_ready(http)
        safe_print(
            f"  version={health.get('version')} historian={health.get('historian')} "
            f"fdd_engine={health.get('fdd_engine')}"
        )
        headers = login(http, user=args.user, password=args.password)
        rows = post_sparql(http, headers, building_id=building_id, query=LIST_AHUS)
        print_table("AHU-class equipment", rows)
        if not rows:
            safe_print(
                "WARN: empty — import a synthetic package with Haystack RDF for this building_id"
            )
            return 0
    safe_print("\nPASS lesson 01")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
