#!/usr/bin/env python3
"""Copy the role catalog data the PyPI package ships into ``open_fdd/data/``.

The package must not import from ``nf-app/`` (a wheel has no checkout), so the files it needs are
copied here from their single source of truth:

    nf-app/static/fdd-catalog.json  ->  open_fdd/data/fdd-catalog.json   (role -> NF classes/markers, rules)
    sql/fdd/role_scales.json        ->  open_fdd/data/role_scales.json   (role -> declared scale)
    sql/fdd/role_map.json           ->  open_fdd/data/role_map.json      (SQL role -> pandas Haystack column)

    python scripts/nf/sync_pypi_data.py            # copy
    python scripts/nf/sync_pypi_data.py --check    # exit 1 when a copy is missing or stale (CI)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAIRS = [
    ("nf-app/static/fdd-catalog.json", "open_fdd/data/fdd-catalog.json"),
    ("sql/fdd/role_scales.json", "open_fdd/data/role_scales.json"),
    ("sql/fdd/role_map.json", "open_fdd/data/role_map.json"),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if any copy is stale")
    args = ap.parse_args(argv)
    stale = []
    for src_rel, dst_rel in PAIRS:
        src, dst = ROOT / src_rel, ROOT / dst_rel
        data = src.read_bytes()
        if dst.is_file() and dst.read_bytes() == data:
            continue
        stale.append(dst_rel)
        if not args.check:
            dst.parent.mkdir(parents=True, exist_ok=True)
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
