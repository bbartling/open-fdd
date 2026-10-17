#!/usr/bin/env python3
"""Soft-OPEN DB sample checks via product API (no direct SQL on Railway).

Fails when package mapping shows roles but point-resolve history is empty
(mapped-but-0-samples). Soft-OPEN ≠ FQ.

  python scripts/softopen/validate_db_samples.py --host <hub> --building-id BUILDING_100
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_STRESS = Path(__file__).resolve().parents[1] / "stress"
if str(_STRESS) not in sys.path:
    sys.path.insert(0, str(_STRESS))

from helpers import (  # noqa: E402
    banner,
    client,
    fdd_equipment,
    login,
    mint_opaque_point_iri,
    parse_connection,
    point_resolve,
    print_table,
    require_building_id,
    safe_print,
    wait_until_ready,
)


def main(argv: list[str] | None = None) -> int:
    args = parse_connection(argv)
    extra = argparse.ArgumentParser(add_help=False)
    extra.add_argument("--equipment-id", default=None)
    extra.add_argument("--max-points", type=int, default=50)
    more, _ = extra.parse_known_args(argv)
    args.equipment_id = more.equipment_id
    args.max_points = more.max_points
    building_id = require_building_id(args)
    banner("Soft-OPEN DB samples", base_url=args.base_url, building_id=building_id)

    fail = 0
    rows_out: list[dict[str, str]] = []

    with client(args.base_url) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)
        inv = fdd_equipment(http, headers, building_id=building_id)
        equips = inv.get("equipment") or []
        if not equips:
            safe_print("FAIL: /api/fdd/equipment empty")
            return 2

        # Prefer mapping inventory when present.
        mapping = http.get_json(
            "/api/csv/import/package/mapping",
            headers=headers,
            params={"building_id": building_id},
        )
        map_equips = {
            str(e.get("equipment_id")): e
            for e in (mapping.get("equipment") or [])
            if isinstance(e, dict) and e.get("equipment_id")
        }

        for eq in equips:
            if not isinstance(eq, dict):
                continue
            eid = str(eq.get("equipment_id") or "")
            if args.equipment_id and eid != args.equipment_id:
                continue
            block = map_equips.get(eid) or {}
            columns = block.get("columns") or []
            roles = [
                str(c.get("role") or "")
                for c in columns
                if isinstance(c, dict) and str(c.get("status") or "") == "mapped"
            ]
            roles = [r for r in roles if r][:8]
            if not roles:
                # Fall back: probe sat / fan_status if type looks like AHU.
                et = str(eq.get("equipment_type") or "").lower()
                if "ahu" in et or et == "rtu":
                    roles = ["sat", "fan_status"]
                else:
                    continue
            for role in roles:
                iri = mint_opaque_point_iri(building_id, eid, role)
                hist = point_resolve(
                    http,
                    headers,
                    point_iri=iri,
                    include_history=True,
                    max_points=args.max_points,
                )
                history = hist.get("history") if isinstance(hist.get("history"), dict) else hist
                count = int((history or {}).get("point_count") or 0)
                ok = count > 0
                rows_out.append(
                    {
                        "equipment_id": eid,
                        "role": role,
                        "point_count": str(count),
                        "result": "PASS" if ok else "FAIL",
                    }
                )
                if not ok:
                    fail += 1

    print_table("sample counts", rows_out, limit=40)
    if fail:
        safe_print(f"\nFAIL Soft-OPEN DB samples ({fail} mapped roles with 0 history)")
        return 2
    if not rows_out:
        safe_print("\nFAIL Soft-OPEN DB samples (nothing probed)")
        return 2
    safe_print("\nPASS Soft-OPEN DB samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
