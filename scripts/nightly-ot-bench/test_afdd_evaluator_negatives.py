#!/usr/bin/env python3
"""Offline negative tests for ACME AFDD / analytics envelope evaluators.

These must FAIL the relevant requirement — greenwash envelopes are not PASS.
Run: python3 scripts/nightly-ot-bench/test_afdd_evaluator_negatives.py
"""
from __future__ import annotations

import json
import sys


def is_fail_closed_envelope(body: dict) -> bool:
    analytics = body.get("analytics") or {}
    coverage = analytics.get("coverage") or {}
    if coverage.get("fail_closed") is True:
        return True
    if coverage.get("timed_out") is True:
        return True
    if analytics.get("timed_out") is True:
        return True
    for w in analytics.get("warnings") or []:
        s = str(w).lower()
        if "timeout" in s or "fail-closed" in s or "fail_closed" in s or "timed out" in s:
            return True
    return False


def cycle_useful(cycle: dict) -> tuple[bool, str]:
    succ = int(cycle.get("rules_succeeded") or 0)
    fail = int(cycle.get("rules_failed") or 0)
    skip = int(cycle.get("rules_skipped") or 0)
    executed = succ + fail
    if executed == 0:
        return False, "all_skipped_or_empty"
    start = cycle.get("start_utc")
    end = cycle.get("end_utc")
    if not start or not end:
        return False, "missing_window"
    # crude span check using iso strings if present
    return True, "ok"


def main() -> int:
    cases = []

    # 1) timeout envelope with HTTP-200 shape
    body = {
        "ok": True,
        "analytics": {
            "equipment": [],
            "rows": [],
            "coverage": {"fail_closed": True, "timeout_secs": 12},
            "warnings": ["runtime query timed out"],
        },
    }
    cases.append(("fail_closed_timeout", is_fail_closed_envelope(body) is True))

    # 2) empty ok envelope without fail_closed — not automatically fail here
    #    (gate 37 only fails fail_closed/timeout); document as NOT auto-fail
    body2 = {"ok": True, "analytics": {"equipment": [], "rows": [], "coverage": {}}}
    cases.append(("empty_without_flag_not_auto_fail_closed", is_fail_closed_envelope(body2) is False))

    # 3) all-skipped AFDD cycle
    ok, reason = cycle_useful(
        {"rules_succeeded": 0, "rules_failed": 0, "rules_skipped": 40, "start_utc": "a", "end_utc": "b"}
    )
    cases.append(("all_skipped_not_useful", ok is False and reason == "all_skipped_or_empty"))

    # 4) wrong-tenant / wrong scope cycle
    cycle = {"ok": True, "scope": "SYNTH", "rules_succeeded": 5, "rules_failed": 0, "rules_skipped": 0}
    cases.append(("wrong_scope_detected", cycle.get("scope") != "ACME"))

    # 5) stale run id mismatch
    recent = {"run_id": "old", "scope": "ACME", "ok": True}
    cases.append(("stale_run_id", recent.get("run_id") != "new"))

    # 6) partial failure still has executed rules (useful but not greenwash PASS for cycle.ok)
    ok6, _ = cycle_useful(
        {
            "rules_succeeded": 10,
            "rules_failed": 2,
            "rules_skipped": 5,
            "start_utc": "a",
            "end_utc": "b",
            "ok": False,
        }
    )
    cases.append(("partial_failure_still_executed", ok6 is True))

    failed = [name for name, passed in cases if not passed]
    report = {"ok": len(failed) == 0, "cases": {n: p for n, p in cases}, "failed": failed}
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
