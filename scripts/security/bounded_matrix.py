#!/usr/bin/env python3
"""Bounded Python authz / IDOR / SSRF / MQTT matrix planner (Astra C-PY).

Offline-first. Prints the suite matrix and runs evaluator selftests for SSRF
policy + mqtt ACL fixture semantics. Does not contact Railway or OT.

Usage:
  python3 scripts/security/bounded_matrix.py --selftest
  python3 scripts/security/bounded_matrix.py --plan --profile isolated_full
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEC = Path(__file__).resolve().parent
sys.path.insert(0, str(SEC))

from openfdd_security.runner import list_suites  # noqa: E402
from openfdd_security.ssrf_policy import classify_url, forbidden_urls  # noqa: E402

MATRIX = {
    "authz": {
        "suite": "Y",
        "owns": "own-object success + foreign deny + role detectors",
        "aliases": ["IDOR"],
    },
    "idor": {
        "suite": "Y",
        "owns": "foreign building/tenant object denial (same Y suite)",
        "aliases": ["authz"],
    },
    "ssrf": {
        "suite": "ssrf",
        "owns": "URL fetch policy + isolated canary hit counts",
        "aliases": [],
    },
    "mqtt": {
        "suite": "mqtt_acl",
        "owns": "generated ACL semantics + optional observer (≠ continuity)",
        "aliases": [],
    },
    "authn": {
        "suite": "X",
        "owns": "preauth 401 + JWT integrity + login/me identity",
        "aliases": [],
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan(profile: str) -> dict:
    suites = list_suites()
    rows = []
    for name, meta in MATRIX.items():
        rows.append(
            {
                "control": name,
                "suite": meta["suite"],
                "suite_title": suites.get(meta["suite"], ""),
                "owns": meta["owns"],
                "aliases": meta["aliases"],
            }
        )
    return {
        "schema_version": "openfdd_bounded_security_matrix_v1",
        "profile": profile,
        "generated_at": _now(),
        "rows": rows,
        "notes": (
            "Bounded matrix for Astra C-PY. Execute via openfdd_security_probe.py "
            "with --suite flags. Soft-OPEN live canary/MQTT observer remain gated."
        ),
    }


def selftest() -> dict:
    checks = []
    # SSRF forbidden batch
    ok_forbid = all(classify_url(u).get("class") == "forbidden" for u in forbidden_urls())
    checks.append({"id": "ssrf_forbidden_batch", "ok": ok_forbid})
    ok_canary = classify_url("http://127.0.0.1:18081/canary").get("class") == "canary"
    checks.append({"id": "ssrf_canary_class", "ok": ok_canary})
    # Matrix covers required control names
    for need in ("authz", "idor", "ssrf", "mqtt"):
        checks.append({"id": f"matrix_has_{need}", "ok": need in MATRIX})
    # mqtt ACL fixture exists
    acl = SEC / "fixtures" / "mqtt_tenant_acl" / "acl"
    checks.append({"id": "mqtt_acl_fixture", "ok": acl.is_file()})
    # IDOR aliases into Y
    checks.append({"id": "idor_maps_to_Y", "ok": MATRIX["idor"]["suite"] == "Y"})
    ok = all(c["ok"] for c in checks)
    return {
        "schema_version": "openfdd_bounded_security_matrix_v1",
        "mode": "selftest",
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "checks": checks,
        "checked_at": _now(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--profile", default="isolated_full")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.selftest:
        report = selftest()
    elif args.plan:
        report = plan(args.profile)
    else:
        ap.error("pass --selftest or --plan")
        return 2
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.selftest:
        return 0 if report["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
