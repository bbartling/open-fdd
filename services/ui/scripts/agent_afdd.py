#!/usr/bin/env python3
"""CLI wrapper for the importable Agent AFDD API (no Streamlit / no HTTP server).

Examples
--------
python scripts/agent_afdd.py --package path\\to\\building.zip --out out_dir --run-all
python scripts/agent_afdd.py --building-folder path\\to\\BUILDING_100 --out out_dir --run-rules
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root or scripts/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_api import (  # noqa: E402
    export_agent_bundle,
    load_building_folder,
    load_package_path,
    run_analytics,
    run_rcx_coverage,
    run_rules,
)


def _load_params(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"--params file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("--params must be a JSON object of rule_id → {param: value}")
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent AFDD / RCx runner (pandas cookbook)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--package", type=str, help="openfdd_package_v1 zip or extracted dir")
    src.add_argument("--building-folder", type=str, help="Historian building folder")
    parser.add_argument("--out", type=str, required=True, help="Output directory for artifacts")
    parser.add_argument("--params", type=str, default=None, help="fault_settings.json path")
    parser.add_argument("--run-rules", action="store_true")
    parser.add_argument("--run-analytics", action="store_true")
    parser.add_argument("--run-rcx", action="store_true")
    parser.add_argument("--run-all", action="store_true", help="Rules + analytics + RCx")
    parser.add_argument(
        "--no-gates",
        action="store_true",
        help="Disable operational gates (fan/pump proof)",
    )
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="Do not write Streamlit .last_agent_session.json bootstrap",
    )
    parser.add_argument(
        "--export-profile",
        choices=("summary", "diagnostic", "forensic"),
        default="summary",
        help="WattLab dump evidence profile (default: summary)",
    )
    args = parser.parse_args(argv)

    if args.run_all:
        args.run_rules = args.run_analytics = args.run_rcx = True
    if not (args.run_rules or args.run_analytics or args.run_rcx):
        args.run_rules = args.run_analytics = args.run_rcx = True

    if args.package:
        dataset = load_package_path(args.package)
        src_package, src_folder = args.package, None
    else:
        dataset = load_building_folder(args.building_folder)
        src_package, src_folder = None, args.building_folder

    params = _load_params(args.params)
    run = None
    if args.run_rules:
        run = run_rules(
            dataset,
            params=params or None,
            require_operational_gates=not args.no_gates,
        )
        print(
            f"Rules: {run.meta.get('result_count')} results · "
            + ", ".join(f"{k}={v}" for k, v in sorted(run.status_counts.items()))
        )
    else:
        from app.agent_api import AgentRun

        run = AgentRun(params={**dataset.params, **params})

    if args.run_analytics:
        run.analytics = run_analytics(dataset)
        print(
            "Analytics: "
            + ", ".join(f"{k}={len(v)}" for k, v in run.analytics.items())
        )
    if args.run_rcx:
        run.rcx_coverage = run_rcx_coverage(dataset)
        nonempty = int((run.rcx_coverage["row_count"] > 0).sum()) if not run.rcx_coverage.empty else 0
        print(f"RCx coverage: {nonempty}/{len(run.rcx_coverage)} presets with data")

    written = export_agent_bundle(dataset, run, args.out, profile=args.export_profile)
    if args.no_bootstrap:
        # Remove default bootstrap if export wrote it
        from app.bootstrap import default_bootstrap_path

        bp = default_bootstrap_path()
        if bp.is_file():
            bp.unlink(missing_ok=True)
        written = {k: v for k, v in written.items() if not str(k).startswith("bootstrap")}
    else:
        # Ensure bootstrap points at the original CLI source path (zip preferred)
        from app.bootstrap import build_bootstrap_payload, write_bootstrap
        from app.agent_api import make_session_config

        session = make_session_config(
            dataset.role_map,
            run.params or dataset.params,
            unit_system=dataset.unit_system,
            prefer_web_oat=dataset.prefer_web_oat,
        )
        boot = build_bootstrap_payload(
            package_path=src_package,
            building_folder=src_folder,
            session_config=session,
            fault_settings_path=written.get("fault_settings"),
            column_map_path=written.get("column_map"),
            out_dir=args.out,
            auto_run_rules=True,
            notes=f"CLI bootstrap for {dataset.building_id}",
        )
        for bp in write_bootstrap(boot, path=Path(args.out) / "streamlit_bootstrap.json", also_default=True):
            written[f"bootstrap:{bp.name}"] = bp
            print(f"Streamlit bootstrap -> {bp}")

    print(f"Wrote {len(written)} artifacts -> {Path(args.out).resolve()}")
    for key, path in sorted(written.items()):
        print(f"  {key}: {getattr(path, 'name', path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
