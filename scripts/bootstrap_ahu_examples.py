#!/usr/bin/env python3
"""
Bootstrap workshop CSVs using a declarative ``site_profiles*.yaml`` under ``examples/AHU/``.

Usage (from repo root)::

    python scripts/bootstrap_ahu_examples.py --reset

RTU 11 with sensor bounds + flatline on AHU supply/mixed/outside/return temps only::

    python scripts/bootstrap_ahu_examples.py --reset --profiles examples/AHU/site_profiles_rtu11_temp.yaml

See ``examples/AHU/README.md`` for purge notes and Plots + FDD.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    repo = _repo_root()
    default_demo = repo / "examples" / "AHU" / ".openfdd_demo"
    default_profiles = repo / "examples" / "AHU" / "site_profiles.yaml"
    ap = argparse.ArgumentParser(description="Apply an AHU examples site_profiles YAML to a desktop data directory.")
    ap.add_argument(
        "--profiles",
        type=Path,
        default=None,
        help="Path to site_profiles YAML (default: examples/AHU/site_profiles.yaml)",
    )
    ap.add_argument(
        "--desktop-dir",
        type=Path,
        default=default_demo,
        help="Directory for OFDD_DESKTOP_DATA_DIR (isolated demo store)",
    )
    ap.add_argument("--reset", action="store_true", help="Purge Feather + empty model before applying the pack")
    args = ap.parse_args()
    demo_dir = args.desktop_dir.resolve()
    demo_dir.mkdir(parents=True, exist_ok=True)
    os.environ["OFDD_DESKTOP_DATA_DIR"] = str(demo_dir)

    profiles_arg = args.profiles if args.profiles is not None else default_profiles
    profiles = (profiles_arg if profiles_arg.is_absolute() else (repo / profiles_arg)).resolve()
    if not profiles.is_file():
        print(f"Missing profile pack: {profiles}", file=sys.stderr)
        return 2

    from open_fdd.assistant.site_profiles_runner import apply_site_profiles_file
    from open_fdd.desktop.services.ingest_service import IngestService
    from open_fdd.desktop.services.model_service import ModelService
    from open_fdd.desktop.services.ttl_service import TtlService

    model = ModelService()
    ingest = IngestService(model_service=model)
    ttl = TtlService(model_store=model.store)
    out = apply_site_profiles_file(
        profiles_yaml=profiles.resolve(),
        model=model,
        ingest=ingest,
        ttl=ttl,
        reset=bool(args.reset),
    )

    print("--- Site profile pack applied ---")
    print(f"OFDD_DESKTOP_DATA_DIR={demo_dir}")
    print(f"Profiles: {out.get('profiles_file')}")
    for s in out.get("sites") or []:
        print(f"  Site {s.get('display_name')!r} id={s.get('site_id')!r} rows={s.get('ingest_rows')} metrics={s.get('metrics')}")
    print(f"Rules copied: {', '.join(out.get('rules_copied') or []) or '(none)'}")
    print()
    print("Next: start the bridge with this same OFDD_DESKTOP_DATA_DIR, open the UI, **Plots** → **Load + FDD overlay**.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
