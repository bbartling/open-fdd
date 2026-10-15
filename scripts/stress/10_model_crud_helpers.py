#!/usr/bin/env python3
"""Gate H — RDF / model mutation helpers (dry_run) or honest gap vs BPS.

BPS has revisioned overlay CRUD (``dry_run``, ``expected_revision``, tombstones)
in ``bps/semantic/model_crud.py``. Open-FDD tip Soft-OPEN exposes:

  - ``POST /api/model/commissioning-import`` (fail-closed validation)
  - ``POST /api/model/assignments/save``
  - Package mapping / Haystack TTL (read) + SPARQL (read-only)

This gate probes whether a dry_run / revision contract exists. If not, it
documents the gap and exits 0 with WARN (Soft-OPEN honesty — not a greenwash
PASS claiming BPS parity). Soft-OPEN ≠ FQ.

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

GAP_DOC = """
Open-FDD Soft-OPEN model mutation vs BPS model_crud
===================================================

BPS (Windows twin):
  - Revisioned RDF overlay CRUD with dry_run + expected_revision + tombstones
  - Acceptance wave w1_model_crud

Open-FDD tip (this gate):
  - Read: POST /api/model/sparql, GET package TTL / haystack.ttl, point-resolve
  - Write-ish: POST /api/model/commissioning-import (full bundle, fail-closed)
  - Write-ish: POST /api/model/assignments/save
  - No first-class HTTP dry_run / expected_revision overlay CRUD matching BPS

Track: #997 / #1123 / #1003 / #1004 (Haystack RDF) + PARITY-CORE RDF CRUD residual.
Soft-OPEN ≠ FQ — do not claim BPS CRUD parity until a revisioned dry_run API lands.
"""


def main(argv: list[str] | None = None) -> int:
    args = parse_connection(argv)
    building_id = require_building_id(args)
    banner(
        "Stress 10 — model CRUD helpers / gap doc",
        base_url=args.base_url,
        building_id=building_id,
    )
    with client(args.base_url) as http:
        wait_until_ready(http)
        headers = login(http, user=args.user, password=args.password)

        # Probe commissioning-import with dry_run-ish empty payload (expect 4xx, not 500).
        status, _hdrs, raw = http.request(
            "POST",
            "/api/model/commissioning-import",
            headers=headers,
            json_body={"dry_run": True, "building_id": building_id, "payload": {}},
            timeout=30.0,
        )
        safe_print(f"POST /api/model/commissioning-import dry_run probe -> HTTP {status}")
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {"raw": raw[:200].decode("utf-8", errors="replace")}
        safe_print(f"  body keys={list(body)[:12] if isinstance(body, dict) else type(body)}")

        # If server echoes dry_run support explicitly, note it.
        dry = None
        if isinstance(body, dict):
            dry = body.get("dry_run")
            if "dry_run" in str(body.get("error", "")).lower():
                dry = "mentioned-in-error"
        if dry is True or dry == "mentioned-in-error":
            safe_print("NOTE: commissioning-import acknowledges dry_run (partial)")
        else:
            safe_print(
                "GAP: no BPS-equivalent revisioned overlay CRUD dry_run/expected_revision "
                "on tip — see docstring / ART"
            )

        # assignments/save probe — expect authz or validation, not crash
        status2, _, raw2 = http.request(
            "POST",
            "/api/model/assignments/save",
            headers=headers,
            json_body={"dry_run": True, "building_id": building_id, "assignments": []},
            timeout=30.0,
        )
        safe_print(f"POST /api/model/assignments/save dry_run probe -> HTTP {status2}")
        if status2 >= 500:
            safe_print("FAIL: assignments/save returned 5xx")
            return 1

    safe_print(GAP_DOC)
    safe_print(
        "WARN 10 — OSS commissioning paths differ from BPS model_crud; "
        "gap documented (not a false PASS). Soft-OPEN ≠ FQ"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
