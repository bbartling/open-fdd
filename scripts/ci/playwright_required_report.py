#!/usr/bin/env python3
"""Fail a required Playwright run that skipped, failed, or asserted nothing.

Reads a Playwright JSON report. Prints passed, failed, skipped, flaky, and
expect-step counts. Exit 0 only when every required test ran and at least one
expect step passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _redact(text: str) -> str:
    redacted = text
    for key in (
        "OPENFDD_ADMIN_PASSWORD",
        "OPENFDD_CI_BROWSER_ADMIN_PASSWORD",
        "OPENFDD_CI_BROWSER_JWT_SECRET",
        "OPENFDD_JWT_SECRET",
    ):
        secret = os.environ.get(key, "")
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _expect_steps(steps: list[Any]) -> int:
    count = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        category = step.get("category")
        title = str(step.get("title") or "")
        if category == "expect" or title.startswith("Expect"):
            count += 1
        nested = step.get("steps")
        if isinstance(nested, list):
            count += _expect_steps(nested)
    return count


def _walk(suite: dict[str, Any], inherited_file: str, titles: list[str], found: list[dict[str, Any]]) -> None:
    file_name = str(suite.get("file") or inherited_file)
    title = str(suite.get("title") or "")
    next_titles = titles
    if title and title != file_name:
        next_titles = titles + [title]
    for spec in suite.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        spec_title = " :: ".join([*next_titles, str(spec.get("title") or "")])
        for test in spec.get("tests") or []:
            if isinstance(test, dict):
                found.append({"file": file_name, "title": spec_title, "test": test})
    for child in suite.get("suites") or []:
        if isinstance(child, dict):
            _walk(child, file_name, next_titles, found)


def evaluate(report: dict[str, Any]) -> tuple[int, list[str]]:
    found: list[dict[str, Any]] = []
    for suite in report.get("suites") or []:
        if isinstance(suite, dict):
            _walk(suite, "", [], found)

    passed = 0
    failed = 0
    skipped = 0
    flaky = 0
    assertions = 0
    lines: list[str] = []

    for item in found:
        test = item["test"]
        status = str(test.get("status") or "")
        expected = str(test.get("expectedStatus") or "")
        results = test.get("results") if isinstance(test.get("results"), list) else []
        last = results[-1] if results else {}
        last_status = str(last.get("status") or "") if isinstance(last, dict) else ""
        label = item["title"] or item["file"] or "(unnamed)"
        steps = last.get("steps") if isinstance(last, dict) else None
        assertions += _expect_steps(steps if isinstance(steps, list) else [])

        if status == "skipped" or expected == "skipped" or last_status == "skipped":
            skipped += 1
            lines.append(f"SKIP {label}")
        elif status == "flaky":
            flaky += 1
            lines.append(f"FLAKY {label}")
        elif status in {"unexpected", "failed"} or last_status in {"failed", "timedOut", "interrupted"}:
            failed += 1
            message = ""
            if isinstance(last, dict):
                error = last.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or "")
            detail = _redact(message).strip().splitlines()
            suffix = f" — {detail[0][:240]}" if detail else ""
            lines.append(f"FAIL {label}{suffix}")
        elif status in {"expected", "passed"} or last_status == "passed":
            passed += 1
            lines.append(f"PASS {label}")
        else:
            failed += 1
            lines.append(f"FAIL {label} — unrecognised status {status or last_status or 'missing'}")

    stats = report.get("stats") if isinstance(report.get("stats"), dict) else {}
    if "skipped" in stats:
        try:
            skipped = max(skipped, int(stats["skipped"]))
        except (TypeError, ValueError):
            failed += 1
            lines.append("FAIL stats.skipped is not an integer")
    if "flaky" in stats:
        try:
            flaky = max(flaky, int(stats["flaky"]))
        except (TypeError, ValueError):
            failed += 1
            lines.append("FAIL stats.flaky is not an integer")

    lines.append(
        "playwright-required:"
        f" tests_passed={passed}"
        f" tests_failed={failed}"
        f" tests_skipped={skipped}"
        f" tests_flaky={flaky}"
        f" assertion_count={assertions}"
    )

    problems: list[str] = []
    if not found:
        problems.append("report has no tests")
    if skipped:
        problems.append(f"required tests skipped: {skipped}")
    if failed:
        problems.append(f"required tests failed: {failed}")
    if flaky:
        problems.append(f"required tests flaky: {flaky}")
    if passed < 1:
        problems.append("required tests passed: 0")
    if assertions < 1:
        problems.append("assertion_count is 0")
    if problems:
        lines.append("playwright-required: FAILED " + "; ".join(problems))
        return 1, lines
    lines.append("playwright-required: OK")
    return 0, lines


def _write_summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    counts = next((line for line in lines if line.startswith("playwright-required: tests_")), "")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("## Real-stack browser assertions\n\n")
        if counts:
            handle.write(f"`{counts}`\n")
        handle.write("\n")


def _sample(status: str, expects: int, *, stats_skipped: int = 0, stats_flaky: int = 0) -> dict[str, Any]:
    steps = [{"title": f"Expect toBeVisible {index}", "category": "expect"} for index in range(expects)]
    result_status = {"expected": "passed", "unexpected": "failed", "skipped": "skipped", "flaky": "passed"}.get(
        status, status
    )
    results: list[dict[str, Any]] = []
    if status != "skipped":
        result: dict[str, Any] = {"status": result_status, "steps": steps}
        if status == "unexpected":
            result["error"] = {"message": "expected visible"}
        results.append(result)
    return {
        "stats": {
            "expected": 1 if status == "expected" else 0,
            "unexpected": 1 if status == "unexpected" else 0,
            "skipped": stats_skipped,
            "flaky": stats_flaky,
        },
        "suites": [
            {
                "title": "e2e/smoke.spec.ts",
                "file": "e2e/smoke.spec.ts",
                "specs": [
                    {
                        "title": "shell",
                        "tests": [
                            {
                                "status": status,
                                "expectedStatus": "skipped" if status == "skipped" else "passed",
                                "results": results,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def self_test() -> int:
    failures: list[str] = []

    code, lines = evaluate(_sample("expected", 3))
    text = "\n".join(lines)
    if code != 0 or "assertion_count=3" not in text or "tests_passed=1" not in text:
        failures.append(f"positive passed report did not count assertions ({text})")

    code, lines = evaluate(_sample("skipped", 0, stats_skipped=1))
    if code == 0 or not any("skipped" in line for line in lines):
        failures.append("skipped report was accepted")

    hidden_skip = _sample("expected", 2, stats_skipped=2)
    code, _lines = evaluate(hidden_skip)
    if code == 0:
        failures.append("stats.skipped was ignored")

    code, _lines = evaluate(_sample("expected", 0))
    if code == 0:
        failures.append("zero assertions was accepted")

    code, _lines = evaluate(_sample("unexpected", 1))
    if code == 0:
        failures.append("failed test was accepted")

    code, _lines = evaluate(_sample("expected", 1, stats_flaky=1))
    if code == 0:
        failures.append("flaky stat was accepted")

    empty_code, _lines = evaluate({"suites": [], "stats": {"skipped": 0, "flaky": 0}})
    if empty_code == 0:
        failures.append("empty report was accepted")

    if failures:
        print("playwright_required_report --self-test FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("playwright_required_report --self-test OK (positive=1 negative=6)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.report is None:
        print("FAIL: Playwright JSON report path is required", file=sys.stderr)
        return 1
    if not args.report.is_file():
        print(f"FAIL: Playwright JSON report missing: {args.report}", file=sys.stderr)
        return 1
    raw = args.report.read_text(encoding="utf-8")
    start = raw.find("{")
    if start < 0:
        print("FAIL: Playwright JSON report has no object", file=sys.stderr)
        return 1
    try:
        report = json.loads(raw[start:])
    except json.JSONDecodeError as exc:
        print(f"FAIL: Playwright JSON report is not JSON ({exc})", file=sys.stderr)
        return 1
    if not isinstance(report, dict):
        print("FAIL: Playwright JSON report must be an object", file=sys.stderr)
        return 1
    code, lines = evaluate(report)
    for line in lines:
        print(line)
    _write_summary(lines)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
