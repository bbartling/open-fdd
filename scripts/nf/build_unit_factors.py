#!/usr/bin/env python3
"""Write the unit-conversion factors of ``open_fdd/data/unit_factors.json`` into ``nf-app/static/units.js``.

``unit_factors.json`` is the one canonical source of the multiplicative declared-unit -> SI factors (the NF ingest
values). Python reads the JSON directly (``open_fdd.nf.units``, ``open_fdd.units.convert``, ``open_fdd.parity.imperial``);
the static app cannot fetch JSON, so this script generates the block between the ``BEGIN/END GENERATED unit factors``
markers of ``units.js``. ``--check`` also verifies that the ingest aliases in ``open_fdd/data/units.json`` carry the same
numbers.

    python scripts/nf/build_unit_factors.py            # write
    python scripts/nf/build_unit_factors.py --check    # exit 1 when stale or inconsistent (CI)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTORS = ROOT / "open_fdd" / "data" / "unit_factors.json"
UNITS_JSON = ROOT / "open_fdd" / "data" / "units.json"
TARGET = ROOT / "nf-app" / "static" / "units.js"
BLOCK = re.compile(r"(  // BEGIN GENERATED unit factors[^\n]*\n)(.*?)(  // END GENERATED unit factors)", re.S)


def render_block(factors: dict) -> str:
    body = ",\n".join(f"    {k}: {json.dumps(v['value'])}" for k, v in factors.items())
    return f"  const F = {{\n{body},\n  }};\n"


def alias_problems(factors: dict) -> list[str]:
    aliases = json.loads(UNITS_JSON.read_text(encoding="utf-8"))["aliases"]
    bad = []
    for key, f in factors.items():
        hit = [a for a in aliases if f["alias"] in a["names"]]
        if not hit:
            bad.append(f"{key}: no alias {f['alias']!r} in units.json")
        elif hit[0]["to_si"] != {"mul": f["value"], "add": 0}:
            bad.append(f"{key}: units.json alias {f['alias']!r} has {hit[0]['to_si']}, unit_factors.json has {f['value']}")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if units.js is stale or units.json disagrees")
    args = ap.parse_args(argv)
    factors = json.loads(FACTORS.read_text(encoding="utf-8"))["factors"]
    raw = TARGET.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if not BLOCK.search(text):
        print(f"{TARGET} has no GENERATED unit factors block", file=sys.stderr)
        return 1
    want = BLOCK.sub(lambda m: m.group(1) + render_block(factors) + m.group(3), text)
    problems = alias_problems(factors)
    for p in problems:
        print(p, file=sys.stderr)
    if want == text and not problems:
        print("unit factors are up to date")
        return 0
    if args.check:
        if want != text:
            print("stale nf-app/static/units.js (run: python scripts/nf/build_unit_factors.py)", file=sys.stderr)
        return 1
    if want != text:
        TARGET.write_bytes((want.replace("\n", "\r\n") if crlf else want).encode("utf-8"))
        print("updated nf-app/static/units.js")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
