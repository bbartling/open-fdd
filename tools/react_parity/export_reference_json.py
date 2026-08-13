#!/usr/bin/env python3
"""P1-M1-02 — normalize React SPA/oracle reference JSON (characterization only).

Not a production service. Emits sorted, timezone-explicit payloads for parity.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "openfdd.react_parity.reference.v1"


def _clean_number(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value):
            return {"$number": "NaN"}
        if math.isinf(value):
            return {"$number": "Infinity" if value > 0 else "-Infinity"}
    return value


def normalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: normalize(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [normalize(x) for x in obj]
    if isinstance(obj, set):
        return sorted(normalize(x) for x in obj)
    return _clean_number(obj)


def build_envelope(
    *,
    fixture_id: str,
    fixture_hash: str,
    capability_ids: list[str],
    payload: dict[str, Any],
    engine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize(
        {
            "schema": SCHEMA,
            "generated_at_zone": "UTC",
            # intentionally omitted volatile wall clock from compared body
            "fixture_id": fixture_id,
            "fixture_hash": fixture_hash,
            "capability_ids": sorted(capability_ids),
            "engine": engine
            or {
                "fdd": "datafusion_sql",
                "ui_reference": "react",
                "code_commit": "UNKNOWN",
            },
            "payload": payload,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--fixture-hash", required=True)
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument(
        "--payload-json",
        type=Path,
        help="Raw payload JSON to normalize (stdin if omitted)",
    )
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()

    if args.payload_json:
        payload = json.loads(args.payload_json.read_text(encoding="utf-8"))
    else:
        import sys

        payload = json.load(sys.stdin)

    envelope = build_envelope(
        fixture_id=args.fixture_id,
        fixture_hash=args.fixture_hash,
        capability_ids=args.capability,
        payload=payload,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
