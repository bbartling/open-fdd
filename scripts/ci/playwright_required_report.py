#!/usr/bin/env python3
"""Fail a required Playwright run that skipped, failed, or asserted nothing.

Reads a Playwright JSON report plus the expect-step sidecar. The JSON reporter
keeps only category "test.step", so expect counts come from the sidecar when
the JSON steps do not carry them. Exit 0 only when every required test passed
on the first attempt and at least one expect step passed. A skip, a failure,
or a retry that Playwright reports as flaky fails the run. The summary still
prints tests_flaky and assertion_count.
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
        spec_id = str(spec.get("id") or "")
        for test in spec.get("tests") or []:
            if isinstance(test, dict):
                found.append({"file": file_name, "title": spec_title, "id": spec_id, "test": test})
    for child in suite.get("suites") or []:
        if isinstance(child, dict):
            _walk(child, file_name, next_titles, found)


def _first_error(results: list[Any]) -> str:
    for result in results:
        if not isinstance(result, dict):
            continue
        if str(result.get("status") or "") == "passed":
            continue
        error = result.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and first.get("message"):
                return str(first["message"])
            if isinstance(first, str):
                return first
    return ""


def _coerce_expects(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        raise ValueError("expect sidecar must be an object")
    tests = payload.get("tests")
    if not isinstance(tests, list):
        raise ValueError("expect sidecar tests must be a list")
    counts: dict[str, int] = {}
    for item in tests:
        if not isinstance(item, dict):
            raise ValueError("expect sidecar test must be an object")
        test_id = str(item.get("id") or "")
        if not test_id:
            raise ValueError("expect sidecar test id is missing")
        if test_id in counts:
            raise ValueError(f"expect sidecar duplicate id {test_id}")
        raw = item.get("passed_expect_steps")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"expect sidecar count invalid for {test_id}")
        counts[test_id] = raw
    return counts


def evaluate(report: dict[str, Any], expects: dict[str, int] | None = None) -> tuple[int, list[str]]:
    found: list[dict[str, Any]] = []
    for suite in report.get("suites") or []:
        if isinstance(suite, dict):
            _walk(suite, "", [], found)

    passed = 0
    failed = 0
    skipped = 0
    flaky = 0
    finished_ok = 0
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
        skipped_test = status == "skipped" or expected == "skipped" or last_status == "skipped"
        json_count = 0
        for result in results:
            if not isinstance(result, dict) or str(result.get("status") or "") != "passed":
                continue
            steps = result.get("steps")
            json_count += _expect_steps(steps if isinstance(steps, list) else [])
        side_count = 0
        test_id = str(item.get("id") or "")
        if expects is not None and not skipped_test:
            if not test_id or test_id not in expects:
                failed += 1
                lines.append(f"FAIL {label} — expect sidecar has no count")
            else:
                side_count = expects[test_id]
        test_assertions = max(json_count, side_count)
        if not skipped_test:
            assertions += test_assertions

        if skipped_test:
            skipped += 1
            lines.append(f"SKIP {label}")
        elif status == "flaky":
            flaky += 1
            detail = _redact(_first_error(results)).strip().splitlines()
            suffix = f" — {detail[0][:240]}" if detail else ""
            lines.append(f"FLAKY {label} assertions={test_assertions}{suffix}")
            if last_status != "passed":
                failed += 1
                lines.append(f"FAIL {label} — flaky without a passing result")
        elif status in {"unexpected", "failed"} or last_status in {"failed", "timedOut", "interrupted"}:
            failed += 1
            message = ""
            if isinstance(last, dict):
                error = last.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or "")
            if not message:
                message = _first_error(results)
            detail = _redact(message).strip().splitlines()
            suffix = f" — {detail[0][:240]}" if detail else ""
            lines.append(f"FAIL {label} assertions={test_assertions}{suffix}")
        elif status in {"expected", "passed"} or last_status == "passed":
            passed += 1
            finished_ok += 1
            lines.append(f"PASS {label} assertions={test_assertions}")
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
    walked_flaky = flaky
    if "flaky" in stats:
        try:
            stats_flaky = int(stats["flaky"])
        except (TypeError, ValueError):
            failed += 1
            lines.append("FAIL stats.flaky is not an integer")
        else:
            if stats_flaky > walked_flaky:
                failed += 1
                lines.append(
                    f"FAIL stats.flaky={stats_flaky} exceeds classified flaky tests ({walked_flaky})"
                )
            flaky = max(flaky, stats_flaky)

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
    if finished_ok < 1:
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


def _sample(
    status: str,
    expects: int,
    *,
    stats_skipped: int = 0,
    stats_flaky: int = 0,
    test_id: str = "",
) -> dict[str, Any]:
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
                        "id": test_id,
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


def _stripped_playwright_report(status: str, test_id: str, *, stats_flaky: int = 0) -> dict[str, Any]:
    """JSON reporter shape: expect steps removed, only test.step / pw:api remain."""
    report = _sample(status, 0, stats_flaky=stats_flaky, test_id=test_id)
    results = report["suites"][0]["specs"][0]["tests"][0]["results"]
    if results:
        results[-1]["steps"] = [
            {
                "title": "Before Hooks",
                "category": "test.step",
                "steps": [{"title": "Launch browser", "category": "pw:api"}],
            }
        ]
    if status == "flaky" and results:
        results.insert(0, {"status": "timedOut", "error": {"message": "Timeout 15000ms exceeded"}, "steps": []})
    return report


def self_test() -> int:
    failures: list[str] = []

    code, lines = evaluate(_sample("expected", 3))
    text = "\n".join(lines)
    if code != 0 or "assertion_count=3" not in text or "tests_passed=1" not in text:
        failures.append(f"positive passed report did not count assertions ({text})")

    sidecar_report = _stripped_playwright_report("expected", "passed-1")
    code, lines = evaluate(sidecar_report, {"passed-1": 5})
    text = "\n".join(lines)
    if code != 0 or "assertion_count=5" not in text:
        failures.append(f"sidecar expect count was ignored ({text})")

    flaky_report = _stripped_playwright_report("flaky", "flaky-1", stats_flaky=1)
    code, lines = evaluate(flaky_report, {"flaky-1": 6})
    text = "\n".join(lines)
    if code == 0 or "tests_flaky=1" not in text or "assertion_count=6" not in text:
        failures.append(f"flaky test with a passing retry was accepted ({text})")

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

    code, lines = evaluate(_stripped_playwright_report("expected", "empty-1"), {"empty-1": 0})
    if code == 0:
        failures.append("sidecar zero assertions was accepted")

    code, lines = evaluate(_stripped_playwright_report("expected", "real-1"), {"other": 9})
    if code == 0 or not any("expect sidecar has no count" in line for line in lines):
        failures.append("unmatched expect sidecar was accepted")

    code, _lines = evaluate(_sample("unexpected", 1))
    if code == 0:
        failures.append("failed test was accepted")

    code, _lines = evaluate(_sample("expected", 1, stats_flaky=1))
    if code == 0:
        failures.append("hidden flaky stat was accepted")

    unresolved = _stripped_playwright_report("flaky", "flaky-bad", stats_flaky=1)
    unresolved["suites"][0]["specs"][0]["tests"][0]["results"][-1]["status"] = "failed"
    code, _lines = evaluate(unresolved, {"flaky-bad": 2})
    if code == 0:
        failures.append("flaky test without a passing result was accepted")

    empty_code, _lines = evaluate({"suites": [], "stats": {"skipped": 0, "flaky": 0}})
    if empty_code == 0:
        failures.append("empty report was accepted")

    try:
        _coerce_expects({"tests": [{"id": "a", "passed_expect_steps": True}]})
    except ValueError:
        pass
    else:
        failures.append("boolean expect count was accepted")

    if failures:
        print("playwright_required_report --self-test FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("playwright_required_report --self-test OK (positive=2 negative=11)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", nargs="?", type=Path)
    parser.add_argument("--expects", type=Path)
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
    expects: dict[str, int] | None = None
    if args.expects is not None:
        if not args.expects.is_file():
            print(f"FAIL: expect-count sidecar missing: {args.expects}", file=sys.stderr)
            return 1
        try:
            expects = _coerce_expects(json.loads(args.expects.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"FAIL: expect-count sidecar ({exc})", file=sys.stderr)
            return 1
    code, lines = evaluate(report, expects)
    for line in lines:
        print(line)
    _write_summary(lines)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
