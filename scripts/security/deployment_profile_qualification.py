#!/usr/bin/env python3
"""Evaluate sanitized deployment/exposure evidence against a named profile.

This is an offline evaluator.  It does not resolve DNS, contact Railway, start
containers, or read credentials.  A missing, stale, incomplete, or tampered
evidence file exits nonzero and can never be promoted to a PASS.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from openfdd_security.deployment import (  # noqa: E402
    EVIDENCE_SCHEMA_VERSION,
    evaluate_deployment_evidence,
    load_profile_registry,
)


def _now(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError("--now must include a timezone")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument("--profile", help="deployment profile id")
    parser.add_argument("--evidence", type=Path, help="sanitized evidence JSON")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--now", help="UTC timestamp override for deterministic tests")
    args = parser.parse_args(argv)

    registry = load_profile_registry()
    if args.list_profiles:
        print(json.dumps({"profiles": sorted(registry["profiles"])}, indent=2))
        return 0
    if not args.profile or not args.evidence:
        parser.error("--profile and --evidence are required unless --list-profiles")
    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema_version": EVIDENCE_SCHEMA_VERSION, "ok": False, "error": str(exc)}))
        return 2
    try:
        ok, reason = evaluate_deployment_evidence(
            evidence,
            expected_profile=args.profile,
            registry=registry,
            now=_now(args.now),
            artifact_root=args.artifact_root,
        )
    except (OSError, ValueError) as exc:
        ok, reason = False, str(exc)
    result = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "profile": args.profile,
        "ok": ok,
        "status": "PASS" if ok else "BLOCKED",
        "reason": reason,
    }
    print(json.dumps(result, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
