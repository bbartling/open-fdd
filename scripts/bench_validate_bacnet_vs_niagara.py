#!/usr/bin/env python3
"""Cross-source bench validator CLI — BACnet direct vs Niagara baskStream.

  python3 scripts/bench_validate_bacnet_vs_niagara.py
  python3 scripts/bench_validate_bacnet_vs_niagara.py --write-report
  python3 scripts/bench_validate_bacnet_vs_niagara.py --api http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "workspace" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

os.environ.setdefault("OPENFDD_REPO_ROOT", str(REPO))
os.environ.setdefault("OFDD_DESKTOP_DATA_DIR", str(REPO / "workspace" / "data"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--api", default="", help="Use bridge API instead of direct module")
    parser.add_argument("--config", default="")
    args = parser.parse_args()

    if args.api:
        base = args.api.rstrip("/")
        body = {"write_report": args.write_report, "report_label": "cli"}
        if args.config:
            body["config_path"] = args.config
        req = urllib.request.Request(
            f"{base}/api/bench/validate/bacnet-vs-niagara",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                report = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
            return 1
    else:
        from openfdd_bridge.bench_validator import (  # noqa: E402
            validate_bacnet_vs_niagara,
            write_checkpoint_report,
        )

        cfg = Path(args.config) if args.config else None
        report = validate_bacnet_vs_niagara(config_path=cfg)
        if args.write_report:
            report["report_paths"] = write_checkpoint_report(report, label="cli")

    print(json.dumps(report, indent=2))
    summary = report.get("summary") or {}
    print(
        f"\n{'PASS' if report.get('ok') else 'FAIL'}: "
        f"{summary.get('passed', 0)}/{summary.get('total', 0)} points "
        f"({summary.get('score_pct', 0)}%)",
        file=sys.stderr,
    )
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
