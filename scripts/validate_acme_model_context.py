#!/usr/bin/env python3
"""Validate ACME live-site commissioning model fixture (summary for operators/agents)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from open_fdd.validation.acme_model import (  # noqa: E402
    DEFAULT_FIXTURE,
    load_acme_model,
    round_trip_preserves_model_fields,
    summarize_acme_model,
    validate_acme_model,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ACME commissioning model fixture")
    parser.add_argument("--model", type=Path, default=DEFAULT_FIXTURE, help="Path to acme_data_model.json")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    if not args.model.is_file():
        print(f"Model not found: {args.model}", file=sys.stderr)
        return 2

    model = load_acme_model(args.model)
    report = validate_acme_model(model)
    rt_errors = round_trip_preserves_model_fields(model)
    if rt_errors:
        report.errors.extend(rt_errors)
        report.ok = False

    if args.json:
        out = report.to_dict()
        out["round_trip_ok"] = not rt_errors
        print(json.dumps(out, indent=2))
    else:
        print(summarize_acme_model(model, report))
        if rt_errors:
            print("  round-trip errors:")
            for e in rt_errors:
                print(f"    - {e}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
