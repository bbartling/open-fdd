#!/usr/bin/env python3
"""Lesson 05 — mutate RDF/semantic model via API (semantic-meta PUT).

Proves:
  1. GET /api/model/semantic-meta
  2. PUT dry_run=true (no write)
  3. PUT real write with expected_revision CAS (display_name Soft-OPEN lesson tag)
  4. GET proves the mutation
  5. PUT restore previous display_name when we changed one

  python scripts/lessons/lesson_05_rdf_semantic_meta_put.py \\
    --base-url https://openfdd-web-production.up.railway.app --building-id SYNTH_03

Soft-OPEN ≠ FQ. Synthetic sites only. Needs operator/admin JWT (not viewer).
"""

from __future__ import annotations

import copy
import json
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
    require_building_id,
    safe_print,
    wait_until_ready,
)

TAG = "softopen-lesson-05"


def _json_body(raw: bytes) -> dict:
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


def main(argv: list[str] | None = None) -> int:
    args = parse_connection(argv)
    building_id = require_building_id(args)
    banner(
        "Lesson 05 — RDF semantic-meta mutate via API",
        base_url=args.base_url,
        building_id=building_id,
    )

    with client(args.base_url) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)

        st, _, raw = http.request(
            "GET",
            "/api/model/semantic-meta",
            headers=headers,
            params={"building_id": building_id},
            timeout=30.0,
        )
        got = _json_body(raw)
        safe_print(f"GET /api/model/semantic-meta -> HTTP {st} present={got.get('present')}")
        if st == 404:
            safe_print("FAIL: semantic-meta route missing on tip")
            return 2
        if st >= 400:
            safe_print(f"FAIL: GET semantic-meta HTTP {st}: {raw[:300]!r}")
            return 2

        # Build a meta payload (use tip meta when present; else minimal sketch).
        tip_meta = got.get("meta") if isinstance(got.get("meta"), dict) else None
        if tip_meta:
            meta = copy.deepcopy(tip_meta)
        else:
            meta = {
                "schema": "openfdd_semantic_meta_v1",
                "building_id": building_id,
                "equipment": [
                    {
                        "equipment_id": "AHU_1",
                        "haystack_tags": ["ahu", "equip"],
                        "display_name": "AHU 1",
                    }
                ],
                "points": [],
            }
        meta["building_id"] = building_id
        equips = meta.get("equipment")
        if not isinstance(equips, list) or not equips:
            meta["equipment"] = [
                {
                    "equipment_id": "AHU_1",
                    "haystack_tags": ["ahu", "equip"],
                    "display_name": "AHU 1",
                }
            ]
            equips = meta["equipment"]
        target = equips[0] if isinstance(equips[0], dict) else None
        if target is None:
            safe_print("FAIL: semantic-meta equipment list unusable")
            return 2
        eid = str(target.get("equipment_id") or "AHU_1")
        old_dis = target.get("display_name")
        new_dis = f"{old_dis or eid} [{TAG}]"
        target["display_name"] = new_dis
        target["equipment_id"] = eid

        # dry_run
        st_d, _, raw_d = http.request(
            "PUT",
            "/api/model/semantic-meta",
            headers=headers,
            json_body={"building_id": building_id, "meta": meta, "dry_run": True},
            timeout=30.0,
        )
        body_d = _json_body(raw_d)
        safe_print(f"PUT dry_run -> HTTP {st_d} ok={body_d.get('ok')} dry_run={body_d.get('dry_run')}")
        if st_d == 403:
            safe_print("FAIL: JWT cannot mutate semantic-meta (need operator/admin)")
            return 2
        if st_d >= 400 or body_d.get("ok") is not True or body_d.get("dry_run") is not True:
            safe_print(f"FAIL: dry_run contract — {body_d!r}")
            return 2

        rev = got.get("revision") if got.get("present") else None
        put_body: dict = {"building_id": building_id, "meta": meta}
        if rev:
            put_body["expected_revision"] = rev
        st_w, _, raw_w = http.request(
            "PUT",
            "/api/model/semantic-meta",
            headers=headers,
            json_body=put_body,
            timeout=30.0,
        )
        body_w = _json_body(raw_w)
        safe_print(
            f"PUT write -> HTTP {st_w} ok={body_w.get('ok')} revision={body_w.get('revision')}"
        )
        if st_w == 409:
            safe_print("FAIL: revision conflict — reload and retry")
            return 2
        if st_w >= 400 or body_w.get("ok") is not True:
            safe_print(f"FAIL: write rejected — {body_w!r}")
            return 2

        st2, _, raw2 = http.request(
            "GET",
            "/api/model/semantic-meta",
            headers=headers,
            params={"building_id": building_id},
            timeout=30.0,
        )
        got2 = _json_body(raw2)
        meta2 = got2.get("meta") if isinstance(got2.get("meta"), dict) else {}
        equips2 = meta2.get("equipment") if isinstance(meta2.get("equipment"), list) else []
        found = None
        for e in equips2:
            if isinstance(e, dict) and str(e.get("equipment_id")) == eid:
                found = e.get("display_name")
                break
        safe_print(f"GET after write display_name={found!r}")
        if found != new_dis:
            safe_print("FAIL: mutation not visible on GET")
            return 2

        # Restore prior display_name (leave graph tidy).
        if isinstance(equips2, list):
            restore = copy.deepcopy(meta2)
            for e in restore.get("equipment") or []:
                if isinstance(e, dict) and str(e.get("equipment_id")) == eid:
                    if old_dis is None:
                        e.pop("display_name", None)
                    else:
                        e["display_name"] = old_dis
            rev2 = got2.get("revision")
            st_r, _, raw_r = http.request(
                "PUT",
                "/api/model/semantic-meta",
                headers=headers,
                json_body={
                    "building_id": building_id,
                    "meta": restore,
                    **({"expected_revision": rev2} if rev2 else {}),
                },
                timeout=30.0,
            )
            body_r = _json_body(raw_r)
            safe_print(f"PUT restore -> HTTP {st_r} ok={body_r.get('ok')}")
            if st_r >= 400 or body_r.get("ok") is not True:
                safe_print(f"WARN: restore failed — leave Soft-OPEN tag: {body_r!r}")
            else:
                safe_print("  restored previous display_name")

    safe_print("\nPASS lesson 05 — semantic-meta RDF mutate via API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())