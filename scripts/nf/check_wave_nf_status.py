#!/usr/bin/env python3
"""Fail unless Wave-NF status stays truthful: nothing deployed or qualified."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "docs" / "operations" / "wave_nf_status.json"

REQUIRED = {
    "n0-boundary",
    "n1-archive-real",
    "n1-restore-boot",
    "n1-workspace-remove",
    "n2-security",
    "n2-dns-pin",
    "n2-hot-secrets",
    "n3-model",
    "n3-replica-store",
    "n4-contract",
    "n5-durable",
    "n6-storage",
    "n7-gaps",
    "n8-scale",
    "n9-meteo",
    "n10-api-mcp",
    "n11-frontend",
    "n12-evidence",
    "n13-release",
    "m0-milestones",
    "m1-freeze-ot",
    "m2-adr",
    "m3-trait",
    "m4-nf-driver",
    "m5-map",
    "m6-fe-blast",
    "m7-fe-haystack",
    "m8-ops-ui",
    "m9-stub-ace",
    "m10-ghcr",
    "m11-prove",
    "m12-grok",
    "m13-acme-later",
    "m14-grok-tools",
}

FIELDS = ("implemented", "tested", "deployed", "qualified", "remaining", "phase", "id")


def fail(message: str) -> None:
    print(f"wave-nf status: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    try:
        doc = json.loads(STATUS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing {STATUS}")
    except json.JSONDecodeError as err:
        fail(f"invalid json: {err}")

    if doc.get("schema") != "openfdd-wave-nf-status-v1":
        fail("schema must be openfdd-wave-nf-status-v1")
    if doc.get("deployed") is not False or doc.get("qualified") is not False:
        fail("document deployed and qualified must both be false")

    items = doc.get("items")
    if not isinstance(items, list) or not items:
        fail("items must be a non-empty list")

    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            fail("each item must be an object")
        missing = [field for field in FIELDS if field not in item]
        if missing:
            fail(f"{item.get('id', '?')} missing {missing}")
        item_id = item["id"]
        if item_id in seen:
            fail(f"duplicate id {item_id}")
        seen.add(item_id)
        for flag in ("implemented", "tested", "deployed", "qualified"):
            if not isinstance(item[flag], bool):
                fail(f"{item_id} {flag} must be bool")
        if item["deployed"] or item["qualified"]:
            fail(f"{item_id} is marked deployed or qualified")
        remaining = item["remaining"]
        if not isinstance(remaining, str):
            fail(f"{item_id} remaining must be a string")
        if not item["implemented"] and not remaining.startswith("SoftOPEN defer —"):
            fail(f"{item_id} unfinished work must start with SoftOPEN defer —")
        if item["implemented"] and not item["tested"] and not remaining.strip():
            fail(f"{item_id} is implemented without tests and has an empty remaining")
        if not isinstance(item["phase"], str) or not item["phase"]:
            fail(f"{item_id} phase must be a non-empty string")

    absent = REQUIRED - seen
    extra = seen - REQUIRED
    if absent or extra:
        fail(f"id set mismatch missing={sorted(absent)} extra={sorted(extra)}")

    n12 = next(item for item in items if item["id"] == "n12-evidence")
    if not (n12["implemented"] and n12["tested"]):
        fail("n12 fixture matrix must be implemented and tested")
    if not str(n12["remaining"]).startswith("SoftOPEN defer —"):
        fail("n12 live pilot must stay SoftOPEN defer —")
    if "live" not in n12["remaining"].lower() and "pilot" not in n12["remaining"].lower():
        fail("n12 remaining must name the deferred pilot")

    print(f"wave-nf status: {len(seen)} items, deployed=false, qualified=false")


if __name__ == "__main__":
    main()
