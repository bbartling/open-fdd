"""Shared report schema helpers for Acme live validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from xml.sax.saxutils import escape

CheckStatus = Literal["pass", "fail", "warn", "skip"]


@dataclass
class ValidationCheck:
    id: str
    category: str
    status: CheckStatus
    duration_ms: int = 0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    target: dict[str, Any]
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0.0
    summary: dict[str, Any] = field(default_factory=dict)
    checks: list[ValidationCheck] = field(default_factory=list)

    def add(self, check: ValidationCheck) -> None:
        self.checks.append(check)

    def finalize(self) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        passed = sum(1 for c in self.checks if c.status == "pass")
        failed = sum(1 for c in self.checks if c.status == "fail")
        warnings = sum(1 for c in self.checks if c.status == "warn")
        skipped = sum(1 for c in self.checks if c.status == "skip")
        self.summary = {
            "ok": failed == 0,
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "skipped": skipped,
        }

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        data = {
            "target": dict(self.target),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "summary": dict(self.summary),
            "checks": [asdict(c) for c in self.checks],
        }
        if redact:
            data = redact_report(data)
        return data


_REDACT_PATTERNS = (
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r'"token"\s*:\s*"[^"]+"'), '"token": "[REDACTED]"'),
    (re.compile(r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d+"), "http://[REDACTED-HOST]"),
    (re.compile(r"100\.\d{1,3}\.\d{1,3}\.\d+"), "[REDACTED-TAILSCALE]"),
)


def redact_text(text: str) -> str:
    out = text
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_report(data: dict[str, Any]) -> dict[str, Any]:
    """Redact tokens and private hostnames in report JSON."""

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                if k in {"token", "password", "secret", "authorization"}:
                    out[k] = "[REDACTED]"
                elif k == "base_url":
                    out[k] = "redacted"
                else:
                    out[k] = _walk(v)
            return out
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        if isinstance(obj, str):
            return redact_text(obj)
        return obj

    return _walk(data)


def write_json_report(report: ValidationReport, path: str) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report.to_dict(redact=True), indent=2), encoding="utf-8")


def write_junit_report(report: ValidationReport, path: str) -> None:
    from pathlib import Path

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="acme-live-validate" tests="{len(report.checks)}" '
        f'failures="{report.summary.get("failed", 0)}" '
        f'time="{report.duration_seconds:.3f}">',
    ]
    for check in report.checks:
        cls = f"{check.category}.{check.id}"
        lines.append(f'  <testcase classname="{escape(cls)}" name="{escape(check.id)}" time="{check.duration_ms / 1000.0:.3f}">')
        if check.status == "fail":
            lines.append(f"    <failure message=\"{escape(check.message)}\"/>")
        elif check.status == "warn":
            lines.append(f"    <skipped message=\"{escape(check.message)}\"/>")
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_markdown_report(report: ValidationReport, path: str) -> None:
    from pathlib import Path

    ok = report.summary.get("ok")
    title = "PASS" if ok else "FAIL"
    lines = [
        f"# ACME LIVE VALIDATION — {title}",
        "",
        f"- **Site:** {report.target.get('site_id', '?')} / {report.target.get('building_id', '?')}",
        f"- **Expected image tag:** {report.target.get('expected_image_tag') or '(not set)'}",
        f"- **Duration:** {report.duration_seconds:.1f}s",
        f"- **Passed:** {report.summary.get('passed', 0)} | "
        f"**Failed:** {report.summary.get('failed', 0)} | "
        f"**Warnings:** {report.summary.get('warnings', 0)}",
        "",
        "## Checks",
        "",
    ]
    for check in report.checks:
        icon = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}.get(check.status, "?")
        lines.append(f"- **{icon}** `{check.category}/{check.id}` — {check.message}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_console_summary(report: ValidationReport) -> None:
    ok = report.summary.get("ok")
    title = "PASS" if ok else "FAIL"
    print(f"\nACME LIVE VALIDATION — {title}\n")
    tgt = report.target
    print(f"Target: {tgt.get('site_id')} / {tgt.get('building_id')}")
    if tgt.get("expected_image_tag"):
        print(f"Image tag expected: {tgt.get('expected_image_tag')}")
    print(f"Duration: {report.duration_seconds:.1f}s\n")
    for check in report.checks:
        if check.status == "fail":
            print(f"FAIL {check.category}/{check.id}: {check.message}")
        elif check.status == "warn":
            print(f"WARN {check.category}/{check.id}: {check.message}")
        else:
            print(f"PASS {check.category}/{check.id}")
    if not ok:
        print("\nSuggested next steps:")
        print("1. Re-run upgrade_edge_full.sh (UI static + GHCR), not image-only upgrade.")
        print("2. Check workspace/api/static/app bind mount on edge.")
        print("3. Run ./scripts/stack_health_check.sh against the edge base URL.")
