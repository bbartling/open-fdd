#!/usr/bin/env python3
"""Offline playground Vibe19 (pandas) WattLab oracle dump for Building 100 parity.

Oracle is *playground* Vibe19 + OpenFDD >=4.3.0 — not tools/wattlab_export.
Default runs cookbook rules (no --skip-rules).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIBE19 = Path("/home/ben/py-bacnet-stacks-playground/vibe_code_apps_19")
DEFAULT_PKG = Path("/home/ben/raw_BUILDING_100_openfdd.zip")
DEFAULT_SCHED = ROOT / "reports/wattlab-parity/fixtures/schedule_b100_7to5.json"
DEFAULT_OUT = ROOT / "reports/wattlab-parity/artifacts/vibe19_oracle"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_afdd(vibe19_root: Path):
    script = vibe19_root / "scripts" / "agent_afdd.py"
    if not script.is_file():
        raise SystemExit(f"vibe19 agent_afdd.py not found: {script}")
    sys.path.insert(0, str(vibe19_root))
    spec = importlib.util.spec_from_file_location("vibe19_agent_afdd", script)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {script}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def _maybe_reexec_vibe19_venv(vibe19_root: Path) -> None:
    venv_py = vibe19_root / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        return
    if Path(sys.executable).resolve() == venv_py.resolve():
        return
    os.execv(str(venv_py), [str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package", type=Path, default=DEFAULT_PKG)
    p.add_argument("--schedule", type=Path, default=DEFAULT_SCHED)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--vibe19-root",
        type=Path,
        default=DEFAULT_VIBE19,
        help="Playground vibe_code_apps_19 root (oracle consumer)",
    )
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

    vibe19 = args.vibe19_root.resolve()
    _maybe_reexec_vibe19_venv(vibe19)

    if not args.package.is_file():
        print(f"package not found: {args.package}", file=sys.stderr)
        return 2
    if not args.schedule.is_file():
        print(f"schedule not found: {args.schedule}", file=sys.stderr)
        return 2

    afdd_main = _load_afdd(vibe19)

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

    of_ver = None
    of_sha = None
    cat_hash = None
    try:
        import open_fdd

        of_ver = getattr(open_fdd, "__version__", None)
        man = {}
        if hasattr(open_fdd, "manifest"):
            man = open_fdd.manifest() or {}
        of_ver = man.get("open_fdd_python_version") or of_ver
        of_sha = man.get("open_fdd_python_git_sha")
        from open_fdd.catalog import rule_catalog_hash

        cat_hash = rule_catalog_hash()
    except Exception as exc:  # pragma: no cover
        print(f"warning: could not read open_fdd manifest: {exc}", file=sys.stderr)

    meta = {
        "side": "vibe19_oracle",
        "vibe19_root": str(vibe19),
        "package": str(args.package),
        "package_sha256": _sha256(args.package),
        "schedule": str(args.schedule),
        "profile": args.profile,
        "out": str(args.out),
        "skip_rules": bool(args.skip_rules),
        "open_fdd_python_version": of_ver,
        "open_fdd_python_git_sha": of_sha,
        "rule_catalog_hash": cat_hash,
        "python": sys.executable,
    }
    (args.out / "parity_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    zip_path = args.out.parent / "vibe19_oracle_summary.zip"
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", args.out)
    print(f"oracle dump -> {args.out}")
    print(f"oracle zip  -> {zip_path}")
    print(f"open_fdd    -> {of_ver} catalog={cat_hash}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
