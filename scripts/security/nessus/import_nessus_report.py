#!/usr/bin/env python3
"""Import / validate Nessus (.nessus XML) reports for Open-FDD readiness.

Never invent a PASS without a real report. Missing licensed scan → BLOCKED.
Synthetic fixtures under scripts/security/nessus/fixtures/ exercise the importer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


MAX_BYTES = 64 * 1024 * 1024  # 64 MiB


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_nessus(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"ERROR: missing report {path}")
    size = path.stat().st_size
    if size == 0 or size > MAX_BYTES:
        raise SystemExit(f"ERROR: report size {size} out of bounds")
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise SystemExit(f"ERROR: malformed .nessus XML: {e}") from e
    root = tree.getroot()
    hosts: list[dict[str, Any]] = []
    crit = high = med = low = info = 0
    for report_host in root.iter("ReportHost"):
        name = report_host.get("name") or ""
        items = []
        credentialed_checks: bool | None = None
        for item in report_host.findall("ReportItem"):
            severity = int(item.get("severity") or 0)
            plugin_id = item.get("pluginID") or ""
            plugin_name = item.get("pluginName") or item.get("plugin_name") or ""
            if plugin_id == "19506":
                output = item.findtext("plugin_output") or ""
                match = re.search(
                    r"Credentialed\s+checks\s*:\s*(yes|no)\b",
                    output,
                    re.IGNORECASE,
                )
                if match:
                    credentialed_checks = match.group(1).lower() == "yes"
            if severity >= 4:
                crit += 1
            elif severity == 3:
                high += 1
            elif severity == 2:
                med += 1
            elif severity == 1:
                low += 1
            else:
                info += 1
            items.append(
                {
                    "plugin_id": plugin_id,
                    "plugin_name": plugin_name,
                    "severity": severity,
                    "port": item.get("port"),
                    "protocol": item.get("protocol"),
                }
            )
        hosts.append(
            {
                "name": name,
                "items": items,
                "credentialed_checks": credentialed_checks,
            }
        )
    if not hosts:
        raise SystemExit("ERROR: no ReportHost entries — incomplete scan")
    return {
        "hosts": hosts,
        "counts": {
            "critical": crit,
            "high": high,
            "medium": med,
            "low": low,
            "info": info,
        },
        "credentialed_linux_evidence": bool(hosts)
        and all(host.get("credentialed_checks") is True for host in hosts),
        "source_sha256": _sha256(path),
    }


def evaluate(
    measured: dict[str, Any],
    *,
    require_credentialed: bool,
    allow_medium: bool,
) -> tuple[bool, str]:
    c = measured["counts"]
    empty_hosts = [
        str(host.get("name") or "<unnamed>")
        for host in measured.get("hosts") or []
        if not host.get("items")
    ]
    if empty_hosts:
        return False, "empty ReportHost entries: " + ", ".join(empty_hosts)
    if c["critical"] or c["high"]:
        return False, f"unresolved Critical={c['critical']} High={c['high']}"
    if c["medium"] and not allow_medium:
        return False, f"Medium={c['medium']} without dispositions"
    hosts = measured.get("hosts") or []
    if not hosts:
        return False, "no ReportHost entries — incomplete scan"
    empty_hosts = [
        str(host.get("name") or "<unnamed>")
        for host in hosts
        if not (host.get("items") or []) and host.get("credentialed_checks") is not True
    ]
    if empty_hosts:
        return False, "empty/unassessed ReportHost(s): " + ", ".join(empty_hosts)
    if require_credentialed:
        unassessed = [
            str(host.get("name") or "<unnamed>")
            for host in hosts
            if not str(host.get("name") or "").strip()
            or host.get("credentialed_checks") is not True
        ]
        if unassessed:
            return (
                False,
                "hosts missing positive plugin 19506 'Credentialed checks : yes': "
                + ", ".join(unassessed),
            )
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", help="path to .nessus XML")
    p.add_argument("--out", help="write measured JSON")
    p.add_argument(
        "--require-credentialed",
        action="store_true",
        help="require plugin 19506 evidence",
    )
    p.add_argument(
        "--allow-medium",
        action="store_true",
        help="accept Medium only when dispositions are managed outside this tool",
    )
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    fixtures = Path(__file__).resolve().parent / "fixtures"
    if args.selftest:
        clean = parse_nessus(fixtures / "clean_synthetic.nessus")
        assert clean["counts"]["critical"] == 0
        bad = parse_nessus(fixtures / "high_finding_synthetic.nessus")
        ok, _ = evaluate(bad, require_credentialed=False, allow_medium=True)
        assert not ok
        empty = fixtures / "empty_hosts_synthetic.nessus"
        try:
            parse_nessus(empty)
            raise AssertionError("empty hosts must fail")
        except SystemExit:
            pass
        print("selftest OK")
        return 0

    if not args.report:
        p.error("--report required unless --selftest")
    measured = parse_nessus(Path(args.report))
    ok, reason = evaluate(
        measured,
        require_credentialed=args.require_credentialed,
        allow_medium=args.allow_medium,
    )
    measured["ok"] = ok
    measured["reason"] = reason
    measured["note"] = (
        "This is importer validation only. Trivy is not Nessus. "
        "Missing licensed scan remains BLOCKED."
    )
    text = json.dumps(measured, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
