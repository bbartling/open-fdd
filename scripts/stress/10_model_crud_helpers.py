#!/usr/bin/env python3
"""Gate H — RDF / model mutation helpers (dry_run + expected_revision CAS).

BPS has revisioned overlay CRUD (``dry_run``, ``expected_revision``, tombstones)
in ``bps/semantic/model_crud.py``. Open-FDD Soft-OPEN tip exposes:

  - ``PUT /api/model/semantic-meta`` — dry_run + expected_revision CAS (HR-07)
  - ``GET /api/model/semantic-meta`` — tip meta + revision
  - ``PUT /api/model/overlay`` — Turtle whole-graph import (dry_run + CAS)
  - ``GET /api/model/overlay`` — overlay TTL + revision (+ tombstone list)
  - ``POST/DELETE /api/model/equip|point`` — overlay upsert + tombstones
  - ``GET /api/model/agent-context`` — BPS-compatible recipe bundle (revision + tree)
  - ``GET /api/model/ttl`` — BPS-compatible alias → Haystack projection Turtle
  - Read: ``POST /api/model/sparql``, point-resolve
  - Write-ish (bundle): commissioning-import / assignments/save

Honest Soft-OPEN gap: overlay is **not** unioned into SPARQL pack graph yet.
Soft-OPEN ≠ FQ. Track: #997 / #1123. Synthetic sites only.

  python scripts/stress/10_model_crud_helpers.py --building-id SYNTH_01
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from helpers import (  # noqa: E402
    banner,
    client,
    login,
    parse_connection,
    require_building_id,
    safe_print,
    wait_until_ready,
)

SKETCH_META = {
    "schema": "openfdd_point_metadata_v1_sketch",
    "points": [
        {
            "equipment_id": "AHU_1",
            "column": "SAT",
            "haystack_tags": ["sensor", "point", "air", "temp"],
            "unit": "°F",
            "unit_source": "package_map",
        }
    ],
    "equipment": [
        {
            "equipment_id": "AHU_1",
            "haystack_tags": ["ahu", "equip"],
            "display_name": "AHU 1",
        }
    ],
}


def main(argv: list[str] | None = None) -> int:
    args = parse_connection(argv)
    building_id = require_building_id(args)
    banner(
        "Stress 10 — model semantic-meta dry_run / CAS",
        base_url=args.base_url,
        building_id=building_id,
    )
    meta = dict(SKETCH_META)
    meta["building_id"] = building_id

    with client(args.base_url) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)

        # dry_run probe — must acknowledge without requiring a prior package
        status, _hdrs, raw = http.request(
            "PUT",
            "/api/model/semantic-meta",
            headers=headers,
            json_body={
                "building_id": building_id,
                "meta": meta,
                "dry_run": True,
            },
            timeout=30.0,
        )
        safe_print(f"PUT /api/model/semantic-meta dry_run -> HTTP {status}")
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {"raw": raw[:200].decode("utf-8", errors="replace")}
        safe_print(f"  body keys={list(body)[:12] if isinstance(body, dict) else type(body)}")

        if status == 404:
            safe_print(
                "GAP: /api/model/semantic-meta missing on this tip — "
                "need Soft-OPEN RDF CRUD PR (#997/#1123)"
            )
            return 1
        if status == 403:
            safe_print(
                "WARN 10 — JWT lacks mutate permission for semantic-meta "
                "(viewer?). Soft-OPEN ≠ FQ"
            )
            return 0
        if status >= 500:
            safe_print("FAIL: semantic-meta dry_run returned 5xx")
            return 1
        if not isinstance(body, dict) or body.get("ok") is not True or body.get("dry_run") is not True:
            safe_print(f"FAIL: dry_run contract missing ok/dry_run=true — {body!r}")
            return 1
        safe_print("  dry_run contract OK")

        # Optional: stale CAS should 409 when a tip exists (skip if building empty)
        status_g, _, raw_g = http.request(
            "GET",
            "/api/model/semantic-meta",
            headers=headers,
            params={"building_id": building_id},
            timeout=30.0,
        )
        try:
            got = json.loads(raw_g.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            got = {}
        rev = got.get("revision") if isinstance(got, dict) else None
        if status_g == 200 and isinstance(got, dict) and got.get("present") and rev:
            status_c, _, raw_c = http.request(
                "PUT",
                "/api/model/semantic-meta",
                headers=headers,
                json_body={
                    "building_id": building_id,
                    "meta": meta,
                    "expected_revision": "stale-rev-not-current",
                },
                timeout=30.0,
            )
            safe_print(f"PUT semantic-meta stale CAS -> HTTP {status_c}")
            if status_c != 409:
                safe_print(f"FAIL: expected HTTP 409 conflict, got {status_c} {raw_c[:200]!r}")
                return 1
            safe_print("  revision conflict (409) OK")
        else:
            safe_print(
                "NOTE: no tip revision yet — skip live 409 CAS "
                f"(GET status={status_g} present={got.get('present') if isinstance(got, dict) else None})"
            )

        # Turtle overlay dry_run (BPS PUT /api/model/overlay shape)
        sample_ttl = (
            "@prefix ph: <https://project-haystack.org/def/ph#> .\n"
            f"<urn:openfdd:site/{building_id}#equip-AHU_1> a ph:equip ;\n"
            '  ph:dis "AHU 1" .\n'
        )
        status_o, _, raw_o = http.request(
            "PUT",
            "/api/model/overlay",
            headers=headers,
            json_body={
                "building_id": building_id,
                "ttl": sample_ttl,
                "dry_run": True,
            },
            timeout=30.0,
        )
        try:
            overlay_body = json.loads(raw_o.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            overlay_body = {}
        safe_print(f"PUT /api/model/overlay dry_run -> HTTP {status_o}")
        if status_o == 404:
            safe_print(
                "GAP: /api/model/overlay missing on this tip — "
                "need Soft-OPEN Turtle overlay PR (#997/#1123)"
            )
            return 1
        if status_o == 403:
            safe_print(
                "WARN 10 — JWT lacks mutate permission for overlay "
                "(viewer?). Soft-OPEN ≠ FQ"
            )
        elif status_o >= 500:
            safe_print("FAIL: overlay dry_run returned 5xx")
            return 1
        elif (
            not isinstance(overlay_body, dict)
            or overlay_body.get("ok") is not True
            or overlay_body.get("dry_run") is not True
        ):
            safe_print(f"FAIL: overlay dry_run contract missing ok/dry_run=true — {overlay_body!r}")
            return 1
        else:
            safe_print("  overlay dry_run contract OK")

        # Equip upsert dry_run (BPS POST /api/model/equip)
        status_e, _, raw_e = http.request(
            "POST",
            "/api/model/equip",
            headers=headers,
            json_body={
                "building_id": building_id,
                "equipment_id": "AHU_STRESS",
                "kind": "ahu",
                "dis": "AHU stress",
                "dry_run": True,
            },
            timeout=30.0,
        )
        try:
            equip_body = json.loads(raw_e.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            equip_body = {}
        safe_print(f"POST /api/model/equip dry_run -> HTTP {status_e}")
        if status_e == 404:
            safe_print(
                "GAP: /api/model/equip missing on this tip — "
                "need Soft-OPEN equip/point CRUD PR (#997/#1123)"
            )
            return 1
        if status_e == 403:
            safe_print(
                "WARN 10 — JWT lacks mutate permission for equip "
                "(viewer?). Soft-OPEN ≠ FQ"
            )
        elif status_e >= 500:
            safe_print("FAIL: equip dry_run returned 5xx")
            return 1
        elif (
            not isinstance(equip_body, dict)
            or equip_body.get("ok") is not True
            or equip_body.get("dry_run") is not True
        ):
            safe_print(f"FAIL: equip dry_run contract missing ok/dry_run=true — {equip_body!r}")
            return 1
        else:
            safe_print("  equip dry_run contract OK")

        # BPS-compatible agent-context bundle (read)
        status_a, _, raw_a = http.request(
            "GET",
            "/api/model/agent-context",
            headers=headers,
            params={"building_id": building_id},
            timeout=30.0,
        )
        try:
            ctx = json.loads(raw_a.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            ctx = {}
        safe_print(f"GET /api/model/agent-context -> HTTP {status_a}")
        if status_a == 404:
            safe_print(
                "GAP: /api/model/agent-context missing on this tip — "
                "need Soft-OPEN agent-context PR (#997/#1123)"
            )
            return 1
        if status_a != 200 or not isinstance(ctx, dict) or ctx.get("ok") is not True:
            safe_print(f"FAIL: agent-context contract missing ok=true — {ctx!r}")
            return 1
        if ctx.get("writable_layer") != "openfdd_semantic_meta_v1":
            safe_print(f"FAIL: unexpected writable_layer — {ctx.get('writable_layer')!r}")
            return 1
        if not isinstance(ctx.get("recipes"), list) or not ctx["recipes"]:
            safe_print("FAIL: agent-context recipes missing")
            return 1
        safe_print("  agent-context contract OK")

        # BPS-compatible TTL alias (read)
        status_t, hdrs_t, _raw_t = http.request(
            "GET",
            "/api/model/ttl",
            headers=headers,
            params={"building_id": building_id},
            timeout=30.0,
        )
        ctype = (hdrs_t.get("content-type") or "").lower()
        safe_print(f"GET /api/model/ttl -> HTTP {status_t} content-type={ctype!r}")
        if status_t not in (200, 400, 404):
            safe_print("FAIL: /api/model/ttl unexpected status")
            return 1

    safe_print(
        "PASS 10 — semantic-meta + overlay + equip dry_run (+ optional CAS) + "
        "agent-context + /api/model/ttl alias. Soft-OPEN ≠ FQ "
        "(no SPARQL union)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
