#!/usr/bin/env python3
"""Copy Vibe19 analytics golden CSVs into Open-FDD fixtures (dev only)."""
from __future__ import annotations
import argparse, shutil
from pathlib import Path

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vibe19-root", type=Path, required=True)
    ap.add_argument(
        "--dest",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "tests/fixtures/vibe19_analytics_golden",
    )
    args = ap.parse_args()
    src = args.vibe19_root / "tests/golden/analytics"
    if not src.is_dir():
        raise SystemExit(f"missing {src}")
    args.dest.mkdir(parents=True, exist_ok=True)
    for p in list(src.glob("*.csv")) + [src / "fingerprints.json"]:
        if p.is_file():
            shutil.copy2(p, args.dest / p.name)
            print("copied", p.name)

if __name__ == "__main__":
    main()
