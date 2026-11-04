#!/usr/bin/env python3
"""Verify an exported SI SQL artifact (standalone copy lives at artifact root)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# When copied into the artifact, repo modules are not on PYTHONPATH — bootstrap from env.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path and (REPO / "scripts" / "sql_contract").is_dir():
    sys.path.insert(0, str(REPO))

from scripts.sql_contract.consumer_lib import run_installed_verify  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(os.environ.get("OPENFDD_SI_ARTIFACT_ROOT", ".")),
    )
    p.add_argument("--database-url", default=os.environ.get("OPENFDD_DATABASE_URL"))
    p.add_argument("--expected-source-revision", default=os.environ.get("OPENFDD_SI_EXPECTED_SOURCE_REV"))
    p.add_argument("--skip-db", action="store_true")
    p.add_argument("--receipt-out", type=Path, default=Path("installed_consumer_receipt.json"))
    args = p.parse_args(argv)

    receipt = run_installed_verify(
        args.artifact_root,
        database_url=args.database_url,
        expected_source_revision=args.expected_source_revision,
        skip_db=args.skip_db,
    )
    args.receipt_out.write_text(json.dumps(receipt.to_json(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt.to_json()))
    return 0 if receipt.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
