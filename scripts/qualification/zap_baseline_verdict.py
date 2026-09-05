#!/usr/bin/env python3
"""Parse OWASP ZAP baseline JSON into a qualification gate verdict.

ZAP native risks: Informational / Low / Medium / High (no Critical bucket).
Baseline with -I can exit 0 while WARN/FAIL alerts exist — this script is the
truthful gate. Does not invent a Critical severity.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"ERROR: missing or empty ZAP report: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"ERROR: malformed ZAP JSON: {e}") from e
    if not isinstance(data, dict):
        raise SystemExit("ERROR: ZAP JSON root must be an object")
    return data


def summarize(data: dict[str, Any]) -> dict[str, Any]:
    site = data.get("site") or []
    alerts: list[dict[str, Any]] = []
    if isinstance(site, list):
        for s in site:
            if isinstance(s, dict):
                for a in s.get("alerts") or []:
                    if isinstance(a, dict):
                        alerts.append(a)

    by_risk: dict[str, int] = {
        "High": 0,
        "Medium": 0,
        "Low": 0,
        "Informational": 0,
        "other": 0,
    }
    high_names: list[str] = []
    medium_names: list[str] = []
    for a in alerts:
        risk = str(a.get("riskdesc") or a.get("risk") or "").split(" ", 1)[0]
        name = str(a.get("name") or a.get("alert") or "unknown")
        if risk not in by_risk:
            # riskcode: 3=High 2=Medium 1=Low 0=Info
            code = str(a.get("riskcode") or "")
            risk = {"3": "High", "2": "Medium", "1": "Low", "0": "Informational"}.get(
                code, "other"
            )
        by_risk[risk] = by_risk.get(risk, 0) + 1
        if risk == "High":
            high_names.append(name)
        elif risk == "Medium":
            medium_names.append(name)

    # Fail on any High. Medium disposition: FAIL unless --accept-medium.
    return {
        "alert_count": len(alerts),
        "by_risk": by_risk,
        "high_alerts": sorted(set(high_names)),
        "medium_alerts": sorted(set(medium_names)),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", help="zap_baseline.json path")
    p.add_argument("--out", help="write measured JSON here")
    p.add_argument(
        "--accept-medium",
        action="store_true",
        help="do not FAIL on Medium (still recorded; High always FAIL)",
    )
    p.add_argument(
        "--selftest",
        action="store_true",
        help="run fixture self-tests and exit",
    )
    args = p.parse_args(argv)

    if args.selftest:
        empty = summarize({"site": []})
        assert empty["alert_count"] == 0
        high = summarize(
            {
                "site": [
                    {
                        "alerts": [
                            {"riskdesc": "High (High)", "name": "SQL Injection"},
                            {"riskcode": "2", "name": "CSP"},
                        ]
                    }
                ]
            }
        )
        assert high["by_risk"]["High"] == 1
        assert "SQL Injection" in high["high_alerts"]
        print("selftest OK")
        return 0

    if not args.report:
        p.error("--report is required unless --selftest")
    data = load_report(Path(args.report))
    measured = summarize(data)
    if args.out:
        Path(args.out).write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")

    highs = measured["by_risk"].get("High", 0)
    meds = measured["by_risk"].get("Medium", 0)
    print(json.dumps(measured, indent=2))

    if highs:
        print(
            f"FAIL: {highs} High alert(s): {', '.join(measured['high_alerts'])}",
            file=sys.stderr,
        )
        return 1
    if meds and not args.accept_medium:
        print(
            f"FAIL: {meds} Medium alert(s) (pass --accept-medium to accept explicitly): "
            f"{', '.join(measured['medium_alerts'][:8])}",
            file=sys.stderr,
        )
        return 1
    if meds:
        print(
            f"PASS with accepted Medium residuals ({meds}): "
            f"{', '.join(measured['medium_alerts'][:8])}"
        )
    else:
        print("PASS: no High/Medium alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
