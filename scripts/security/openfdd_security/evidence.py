"""Evidence report model, hashing, and validation."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, STATUSES
from .config import redact


@dataclass
class CheckResult:
    check_id: str
    suite: str
    status: str
    title: str
    expected: str | None = None
    observed: str | None = None
    identity_alias: str | None = None
    method: str | None = None
    path_template: str | None = None
    detector_id: str | None = None
    detail: str | None = None
    duration_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("detail"):
            d["detail"] = redact(str(d["detail"]))[:500]
        return d


@dataclass
class SecurityReport:
    schema_version: str = SCHEMA_VERSION
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    profile: str = ""
    origin: str = ""
    executed: bool = False
    dry_run: bool = True
    suites: list[str] = field(default_factory=list)
    full_profile: bool = True
    candidate: dict[str, Any] = field(default_factory=dict)
    harness: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, Any] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    started_at: str = ""
    ended_at: str = ""
    overall_status: str = "RUNNING"
    fully_qualified: bool = False
    reason: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, check: CheckResult) -> None:
        if check.status not in STATUSES:
            raise ValueError(f"invalid status {check.status}")
        self.checks.append(check)

    def reconcile(self) -> None:
        counts = {
            "planned": len(self.checks),
            "pass": 0,
            "fail": 0,
            "error": 0,
            "blocked": 0,
            "skipped": 0,
            "not_applicable": 0,
        }
        ids: set[str] = set()
        for c in self.checks:
            if c.check_id in ids:
                self.overall_status = "ERROR"
                self.fully_qualified = False
                self.reason = f"duplicate check_id {c.check_id}"
                self.counts = counts
                return
            ids.add(c.check_id)
            key = {
                "PASS": "pass",
                "FAIL": "fail",
                "ERROR": "error",
                "BLOCKED": "blocked",
                "SKIPPED": "skipped",
                "NOT_APPLICABLE": "not_applicable",
            }[c.status]
            counts[key] += 1
        self.counts = counts

        if self.dry_run or not self.executed:
            self.overall_status = "BLOCKED"
            self.fully_qualified = False
            self.reason = "dry-run/plan only; not security evidence"
            return

        if counts["planned"] == 0:
            self.overall_status = "ERROR"
            self.fully_qualified = False
            self.reason = "zero checks executed"
            return

        if counts["fail"]:
            self.overall_status = "FAIL"
            self.fully_qualified = False
            self.reason = f"{counts['fail']} check(s) FAIL"
            return
        if counts["error"] or counts["blocked"]:
            self.overall_status = "BLOCKED"
            self.fully_qualified = False
            self.reason = (
                f"incomplete: error={counts['error']} blocked={counts['blocked']}"
            )
            return
        # All-SKIPPED (or SKIPPED+N/A with zero PASS) is not qualification evidence.
        if counts["pass"] == 0:
            self.overall_status = "BLOCKED"
            self.fully_qualified = False
            if counts["skipped"] == counts["planned"]:
                self.reason = "all checks SKIPPED; no passing evidence"
            elif (
                counts["skipped"] + counts["not_applicable"]
            ) == counts["planned"]:
                self.reason = (
                    "no PASS evidence (only SKIPPED/NOT_APPLICABLE)"
                )
            else:
                self.reason = "zero PASS checks; cannot qualify"
            return
        if not self.full_profile:
            self.overall_status = "PASS"
            self.fully_qualified = False
            self.reason = "subset suites PASS; not full-profile qualification"
            return
        self.overall_status = "PASS"
        self.fully_qualified = True
        self.reason = "all applicable executed checks PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "profile": self.profile,
            "origin": _alias_origin(self.origin),
            "executed": self.executed,
            "dry_run": self.dry_run,
            "suites": self.suites,
            "full_profile": self.full_profile,
            "candidate": self.candidate,
            "harness": self.harness,
            "budget": self.budget,
            "inventory": self.inventory,
            "checks": [c.to_dict() for c in self.checks],
            "counts": self.counts,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "overall_status": self.overall_status,
            "fully_qualified": self.fully_qualified,
            "reason": self.reason,
            "findings": self.findings,
            "notes": self.notes,
        }


def _alias_origin(origin: str) -> str:
    # Shareable summary: strip host details to private alias when non-loopback
    if "127.0.0.1" in origin or "localhost" in origin:
        return origin
    return "private-hub"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_report(report: SecurityReport, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(output_dir, 0o700)
    except OSError:
        pass
    report.reconcile()
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=False) + "\n"
    json_path = output_dir / "security_report.json"
    tmp = output_dir / "security_report.json.tmp"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(json_path)
    try:
        os.chmod(json_path, 0o600)
    except OSError:
        pass
    digest = sha256_file(json_path)
    meta = {
        "report_path": str(json_path),
        "sha256": digest,
        "overall_status": report.overall_status,
        "fully_qualified": str(report.fully_qualified).lower(),
        "executed": str(report.executed).lower(),
        "dry_run": str(report.dry_run).lower(),
        "profile": report.profile,
    }
    meta_path = output_dir / "security_report.sha256"
    meta_path.write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(meta_path, 0o600)
    except OSError:
        pass
    md = render_markdown(report)
    md_path = output_dir / "security_report.md"
    md_path.write_text(md, encoding="utf-8")
    try:
        os.chmod(md_path, 0o600)
    except OSError:
        pass
    return meta


def render_markdown(report: SecurityReport) -> str:
    lines = [
        f"# Security probe report — {report.run_id}",
        "",
        f"- Schema: `{report.schema_version}`",
        f"- Profile: `{report.profile}`",
        f"- Executed: `{report.executed}` dry_run=`{report.dry_run}`",
        f"- Full profile: `{report.full_profile}`",
        f"- Overall: **{report.overall_status}** fully_qualified=`{report.fully_qualified}`",
        f"- Reason: {report.reason}",
        f"- Counts: `{json.dumps(report.counts)}`",
        "",
        "## Checks",
        "",
        "| ID | Suite | Status | Detail |",
        "|----|-------|--------|--------|",
    ]
    for c in report.checks:
        detail = (c.detail or "").replace("|", "/")[:80]
        lines.append(
            f"| `{c.check_id}` | {c.suite} | **{c.status}** | {detail} |"
        )
    lines += [
        "",
        "## Scope note",
        "",
        "Passing checks are evidence for named controls on this candidate,",
        "configuration, and fixture set only. This is not a claim that the",
        "application is free of vulnerabilities.",
        "",
    ]
    return "\n".join(lines)


def validate_report_for_qualification(
    report_path: Path,
    *,
    expected_profile: str,
    require_executed: bool = True,
    expected_sha256: str | None = None,
    require_full_profile: bool = True,
    postcheck: bool = False,
) -> tuple[bool, str]:
    """Return (ok, reason). Used by gate 25b and sabotage tests.

    Never trust a report's self-declared ``fully_qualified`` or ``counts``
    alone — recompute from ``checks[]``. Empty checks cannot qualify.
    """
    if not report_path.is_file():
        return False, "missing security_report.json"
    raw = report_path.read_text(encoding="utf-8")
    digest = sha256_bytes(raw.encode("utf-8"))
    if expected_sha256 and digest != expected_sha256:
        return False, "report hash mismatch (tampered or stale)"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, "report is not valid JSON"
    if data.get("schema_version") != SCHEMA_VERSION:
        return False, "unsupported schema_version"
    if data.get("profile") != expected_profile:
        return False, "profile mismatch"
    if require_executed and (data.get("dry_run") or not data.get("executed")):
        return False, "dry-run artifact cannot qualify"
    if require_full_profile and not postcheck and not data.get("full_profile", True):
        return False, "suite subset cannot claim full-profile qualification"

    checks = data.get("checks")
    if not isinstance(checks, list) or len(checks) == 0:
        return False, "empty or missing checks[]"
    recomputed = {
        "planned": len(checks),
        "pass": 0,
        "fail": 0,
        "error": 0,
        "blocked": 0,
        "skipped": 0,
        "not_applicable": 0,
    }
    ids: set[str] = set()
    for c in checks:
        if not isinstance(c, dict):
            return False, "check entry is not an object"
        cid = c.get("check_id")
        if not cid or cid in ids:
            return False, f"missing or duplicate check_id {cid!r}"
        ids.add(str(cid))
        st = str(c.get("status") or "")
        key = {
            "PASS": "pass",
            "FAIL": "fail",
            "ERROR": "error",
            "BLOCKED": "blocked",
            "SKIPPED": "skipped",
            "NOT_APPLICABLE": "not_applicable",
        }.get(st)
        if key is None:
            return False, f"invalid check status {st!r}"
        recomputed[key] += 1

    if recomputed["fail"]:
        return False, f"{recomputed['fail']} check(s) FAIL"
    if recomputed["error"]:
        return False, f"{recomputed['error']} check(s) ERROR"
    if recomputed["pass"] == 0:
        return False, "zero PASS checks after recompute"

    if postcheck:
        if recomputed["blocked"] == recomputed["planned"]:
            return False, "all checks BLOCKED"
        if data.get("overall_status") in ("FAIL", "ERROR"):
            return False, f"overall_status={data.get('overall_status')}"
    else:
        if recomputed["blocked"]:
            return False, "blocked checks remain"
        if recomputed["skipped"] == recomputed["planned"]:
            return False, "all checks SKIPPED"
        if data.get("overall_status") in ("FAIL", "ERROR"):
            return False, f"overall_status={data.get('overall_status')}"
        if not data.get("fully_qualified"):
            return False, data.get("reason") or "not fully_qualified"

    meta_path = report_path.parent / "security_report.sha256"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("sha256") and meta["sha256"] != digest:
            return False, "sidecar hash disagrees with report bytes"
    return True, "ok"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
