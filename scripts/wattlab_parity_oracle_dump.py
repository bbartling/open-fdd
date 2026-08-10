#!/usr/bin/env python3
"""Offline vibe19 (pandas) WattLab oracle dump for Building 100 parity.

Open-FDD product path is Rust-only — this script is the *oracle* side only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "tools" / "wattlab_export"
DEFAULT_PKG = Path("/home/ben/raw_BUILDING_100_openfdd.zip")
DEFAULT_SCHED = ROOT / "reports/wattlab-parity/fixtures/schedule_b100_7to5.json"
DEFAULT_OUT = ROOT / "reports/wattlab-parity/artifacts/vibe19_oracle"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, default=DEFAULT_PKG)
    p.add_argument("--schedule", type=Path, default=DEFAULT_SCHED)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--profile",
        choices=("summary", "diagnostic", "forensic"),
        default="summary",
    )
    p.add_argument(
        "--skip-rules",
        action="store_true",
        help="Skip cookbook FDD rules (faster; still writes setpoints/analytics)",
    )
    args = p.parse_args()

    if not args.package.is_file():
        print(f"package not found: {args.package}", file=sys.stderr)
        return 2
    if not args.schedule.is_file():
        print(f"schedule not found: {args.schedule}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(EXPORT))
    from agent_afdd import main as afdd_main  # noqa: E402

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)

    argv = [
        "--package",
        str(args.package),
        "--out",
        str(args.out),
        "--export-profile",
        args.profile,
        "--schedule",
        str(args.schedule),
        "--no-bootstrap",
    ]
    if args.skip_rules:
        argv += ["--run-analytics", "--run-rcx"]
    else:
        argv += ["--run-all"]

    rc = afdd_main(argv)
    meta = {
        "side": "vibe19_oracle",
        "package": str(args.package),
        "package_sha256": _sha256(args.package),
        "schedule": str(args.schedule),
        "profile": args.profile,
        "out": str(args.out),
        "skip_rules": args.skip_rules,
    }
    (args.out / "parity_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    # Zip for archive compare
    zip_path = args.out.parent / "vibe19_oracle_summary.zip"
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", args.out)
    print(f"oracle dump -> {args.out}")
    print(f"oracle zip  -> {zip_path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
