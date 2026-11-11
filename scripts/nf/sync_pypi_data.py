#!/usr/bin/env python3
"""Copy the role catalog data the PyPI package ships into ``open_fdd/data/``.

The package must not import from ``nf-app/`` (a wheel has no checkout), so the files it needs are
copied here from their single source of truth:

    nf-app/static/fdd-catalog.json  ->  open_fdd/data/fdd-catalog.json   (role -> NF classes/markers, rules)
    sql/fdd/role_scales.json        ->  open_fdd/data/role_scales.json   (role -> declared scale)
    sql/fdd/role_map.json           ->  open_fdd/data/role_map.json      (SQL role -> pandas Haystack column)

and builds one derived file for the parity harness (``open_fdd.parity``):

    nf-app/rules/pack-postgres.json (contract.history) + sql/fdd/tuning_catalog.json (confirm_min defaults)
                                    ->  open_fdd/data/parity_contract.json

    python scripts/nf/sync_pypi_data.py            # copy
    python scripts/nf/sync_pypi_data.py --check    # exit 1 when a copy is missing or stale (CI)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAIRS = [
    ("nf-app/static/fdd-catalog.json", "open_fdd/data/fdd-catalog.json"),
    ("sql/fdd/role_scales.json", "open_fdd/data/role_scales.json"),
    ("sql/fdd/role_map.json", "open_fdd/data/role_map.json"),
]


def parity_contract() -> bytes:
    """History columns of the SQL input contract and each rule's default confirm_min, for open_fdd.parity."""
    pack = json.loads((ROOT / "nf-app/rules/pack-postgres.json").read_text(encoding="utf-8"))
    tuning = json.loads((ROOT / "sql/fdd/tuning_catalog.json").read_text(encoding="utf-8"))
    cols = [{"name": c["name"], "type": c["type"]} for c in pack["contract"]["history"]
            if c["name"] not in ("equipment_id", "timestamp_utc")]
    confirm = {r["rule_id"]: float((r["parameters"].get("confirm_min") or {}).get("default", 0.0))
               for r in sorted(tuning["rules"], key=lambda r: r["rule_id"])}
    doc = {"_doc": "Derived by scripts/nf/sync_pypi_data.py. history_columns = SQL input contract (history table, "
                   "without equipment_id/timestamp_utc); confirm_min = default confirm delay in minutes per rule.",
           "history_columns": cols, "confirm_min": confirm}
    return (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


DERIVED = [("open_fdd/data/parity_contract.json", parity_contract)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if any copy is stale")
    args = ap.parse_args(argv)
    stale = []
    for src_rel, dst_rel in PAIRS:
        src, dst = ROOT / src_rel, ROOT / dst_rel
        # Compare with line endings normalized: git may check the source out as CRLF and the
        # copy as LF (or the other way round) depending on the platform; content is what matters.
        data = src.read_bytes().replace(b"\r\n", b"\n")
        if dst.is_file() and dst.read_bytes().replace(b"\r\n", b"\n") == data:
            continue
        stale.append(dst_rel)
        if not args.check:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            print(f"updated {dst_rel}")
    for dst_rel, build in DERIVED:
        data, dst = build(), ROOT / dst_rel
        if dst.is_file() and dst.read_bytes().replace(b"\r\n", b"\n") == data:
            continue
        stale.append(dst_rel)
        if not args.check:
            dst.write_bytes(data)
            print(f"updated {dst_rel}")
    if args.check and stale:
        print("stale package data (run: python scripts/nf/sync_pypi_data.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    if not stale:
        print("package data is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
