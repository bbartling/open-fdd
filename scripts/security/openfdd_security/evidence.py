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
        # Transport/parse ERROR is a child failure, not a missing-fixture BLOCKED.
        if counts["error"]:
            self.overall_status = "ERROR"
            self.fully_qualified = False
            self.reason = (
                f"{counts['error']} check(s) ERROR"
                + (f"; blocked={counts['blocked']}" if counts["blocked"] else "")
            )
            return
        if counts["blocked"]:
            self.overall_status = "BLOCKED"
            self.fully_qualified = False
            self.reason = f"incomplete: blocked={counts['blocked']}"
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


def _require_bool(data: dict[str, Any], key: str) -> str | None:
    if key not in data:
        return None
    if not isinstance(data[key], bool):
        return f"{key} must be boolean (got {type(data[key]).__name__})"
    return None


def reconcile_child_rc(
    *,
    report_ok: bool,
    report_status: str | None,
    child_rc: int | None,
) -> tuple[bool, str, str]:
    """Combine report validation with process exit.

    Contradictory ok/status/rc → ERROR (never silent green).
    Returns (ok, status, reason).
    """
    status = (report_status or "").upper()
    if child_rc is None:
        return False, "ERROR", "missing child process rc"
    if report_ok and child_rc == 0:
        return True, "PASS", "ok"
    if report_ok and child_rc != 0:
        return (
            False,
            "ERROR",
            f"report ok but child_rc={child_rc} (contradictory)",
        )
    if not report_ok and child_rc == 0:
        return (
            False,
            "ERROR" if status in ("", "PASS") else status or "FAIL",
            f"child_rc=0 but report not ok (status={status or 'unknown'})",
        )
    # Both failed — prefer report status when present.
    if status in ("FAIL", "ERROR", "BLOCKED"):
        return False, status, f"report not ok; child_rc={child_rc}"
    return False, "FAIL", f"report not ok; child_rc={child_rc}"


def validate_report_for_qualification(
    report_path: Path,
    *,
    expected_profile: str,
    require_executed: bool = True,
    expected_sha256: str | None = None,
    require_full_profile: bool = True,
    postcheck: bool = False,
    required_check_ids: list[str] | None = None,
    expected_candidate_sha: str | None = None,
    child_rc: int | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). Used by gate 25/25b and sabotage tests.

    Never trust a report's self-declared ``fully_qualified`` or ``counts``
    alone — recompute from ``checks[]``. Empty checks cannot qualify.
    When ``required_check_ids`` is provided, every ID must be present with
    PASS (NOT_APPLICABLE allowed only when explicitly listed status).
    When ``child_rc`` is provided, contradictory process/report pairs ERROR.
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
    if not isinstance(data, dict):
        return False, "report root must be object"
    if data.get("schema_version") != SCHEMA_VERSION:
        return False, "unsupported schema_version"
    if data.get("profile") != expected_profile:
        return False, "profile mismatch"

    for key in ("executed", "dry_run", "full_profile", "fully_qualified"):
        err = _require_bool(data, key)
        if err:
            return False, err

    if require_executed and (data.get("dry_run") or not data.get("executed")):
        return False, "dry-run artifact cannot qualify"
    if require_full_profile and not postcheck and not data.get("full_profile", True):
        return False, "suite subset cannot claim full-profile qualification"

    if expected_candidate_sha:
        cand = data.get("candidate") or {}
        if not isinstance(cand, dict):
            return False, "candidate must be object"
        got = str(cand.get("sha") or cand.get("source_sha") or cand.get("digest") or "")
        if got != expected_candidate_sha:
            return False, "candidate sha mismatch or missing"

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
    by_id: dict[str, dict[str, Any]] = {}
    for c in checks:
        if not isinstance(c, dict):
            return False, "check entry is not an object"
        cid = c.get("check_id")
        if not cid or not isinstance(cid, str) or cid in ids:
            return False, f"missing or duplicate check_id {cid!r}"
        ids.add(cid)
        by_id[cid] = c
        st = c.get("status")
        if not isinstance(st, str):
            return False, f"check {cid} status must be string"
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

    declared = data.get("counts")
    if declared is not None:
        if not isinstance(declared, dict):
            return False, "counts must be object"
        for k, v in recomputed.items():
            if k in declared and declared[k] != v:
                return False, f"counts.{k} contradicts recomputed ({declared[k]}!={v})"

    if required_check_ids:
        missing = [cid for cid in required_check_ids if cid not in by_id]
        if missing:
            return False, f"missing required check_ids: {missing[:8]}"
        for cid in required_check_ids:
            st = by_id[cid].get("status")
            if st == "SKIPPED":
                return False, f"required check {cid} is SKIPPED"
            if st == "BLOCKED":
                return False, f"required check {cid} is BLOCKED"
            if st in ("FAIL", "ERROR"):
                return False, f"required check {cid} is {st}"
            if st not in ("PASS", "NOT_APPLICABLE"):
                return False, f"required check {cid} status {st!r}"

    if recomputed["fail"]:
        return False, f"{recomputed['fail']} check(s) FAIL"
    if recomputed["error"]:
        return False, f"{recomputed['error']} check(s) ERROR"
    if recomputed["pass"] == 0:
        return False, "zero PASS checks after recompute"

    # R02: mixed PASS+BLOCKED cannot qualify (precheck or postcheck).
    if recomputed["blocked"]:
        return False, "blocked checks remain"
    if recomputed["skipped"] and not postcheck:
        if recomputed["skipped"] == recomputed["planned"]:
            return False, "all checks SKIPPED"
        # Partial SKIPPED on non-required IDs still blocks full qualification.
        if require_full_profile and not postcheck:
            return False, "skipped checks remain under full-profile qualification"

    if data.get("overall_status") in ("FAIL", "ERROR"):
        return False, f"overall_status={data.get('overall_status')}"
    if not postcheck and not data.get("fully_qualified"):
        return False, data.get("reason") or "not fully_qualified"
    # Contradictory: overall PASS/fully_qualified while recomputed has failures already handled.
    if data.get("overall_status") == "PASS" and (
        recomputed["fail"] or recomputed["error"] or recomputed["blocked"]
    ):
        return False, "overall_status PASS contradicts recomputed failures"
    if data.get("fully_qualified") is True and (
        recomputed["fail"] or recomputed["error"] or recomputed["blocked"]
    ):
        return False, "fully_qualified true contradicts recomputed failures"

    meta_path = report_path.parent / "security_report.sha256"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("sha256") and meta["sha256"] != digest:
            return False, "sidecar hash disagrees with report bytes"

    if child_rc is not None:
        ok_rc, st_rc, reason_rc = reconcile_child_rc(
            report_ok=True,
            report_status=str(data.get("overall_status") or "PASS"),
            child_rc=child_rc,
        )
        if not ok_rc:
            return False, reason_rc
        _ = st_rc

    return True, "ok"


def _check_status_counts(checks: object) -> dict[str, int]:
    counts = {
        "planned": 0,
        "pass": 0,
        "fail": 0,
        "error": 0,
        "blocked": 0,
        "skipped": 0,
        "not_applicable": 0,
    }
    if not isinstance(checks, list):
        return counts
    for item in checks:
        if not isinstance(item, dict):
            continue
        counts["planned"] += 1
        key = {
            "PASS": "pass",
            "FAIL": "fail",
            "ERROR": "error",
            "BLOCKED": "blocked",
            "SKIPPED": "skipped",
            "NOT_APPLICABLE": "not_applicable",
        }.get(str(item.get("status") or ""))
        if key:
            counts[key] += 1
    return counts


def _gate_verdict(ok: bool, status: str, reason: str, child_rc: int) -> dict[str, Any]:
    """Exit-bearing gate verdict. ok is true only for status PASS."""
    passed = bool(ok) and status == "PASS"
    return {
        "ok": passed,
        "status": "PASS" if passed else status,
        "reason": reason,
        "child_rc": child_rc,
    }


def finalize_executed_gate(
    report_path: Path,
    *,
    expected_profile: str,
    child_rc: int,
    postcheck: bool = False,
    require_full_profile: bool = True,
    required_check_ids: list[str] | None = None,
    expected_sha256: str | None = None,
    probe_started_mtime: float | None = None,
) -> dict[str, Any]:
    """Verdict for gates 25 and 25b.

    A report that already existed before this probe is stale. Check-level
    ERROR stays ERROR. A PASS report with a nonzero child exit is ERROR.
    """
    if (
        probe_started_mtime is not None
        and report_path.is_file()
        and report_path.stat().st_mtime < probe_started_mtime
    ):
        return _gate_verdict(
            False,
            "ERROR",
            "stale security_report.json predates this probe",
            child_rc,
        )
    if not report_path.is_file():
        return _gate_verdict(False, "ERROR", "missing security_report.json", child_rc)

    data: dict[str, Any] = {}
    try:
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except json.JSONDecodeError:
        data = {}
    counts = _check_status_counts(data.get("checks"))
    ok, reason = validate_report_for_qualification(
        report_path,
        expected_profile=expected_profile,
        require_full_profile=require_full_profile,
        postcheck=postcheck,
        required_check_ids=required_check_ids,
        expected_sha256=expected_sha256,
        child_rc=child_rc,
    )
    if counts["error"]:
        detail = reason or f"{counts['error']} check(s) ERROR"
        return _gate_verdict(False, "ERROR", detail, child_rc)
    overall = str(data.get("overall_status") or "")
    if overall == "PASS" and child_rc != 0:
        return _gate_verdict(
            False,
            "ERROR",
            f"report PASS but child_rc={child_rc} (contradictory)",
            child_rc,
        )
    if counts["fail"]:
        return _gate_verdict(
            False, "FAIL", reason or f"{counts['fail']} check(s) FAIL", child_rc
        )
    if not ok:
        if counts["blocked"] or overall == "BLOCKED":
            return _gate_verdict(False, "BLOCKED", reason, child_rc)
        if overall == "FAIL":
            return _gate_verdict(False, "FAIL", reason, child_rc)
        return _gate_verdict(False, "ERROR", reason, child_rc)
    if child_rc != 0:
        return _gate_verdict(
            False,
            "ERROR",
            f"report ok but child_rc={child_rc} (contradictory)",
            child_rc,
        )
    return _gate_verdict(True, "PASS", reason or "ok", child_rc)


def finalize_observer_gate(
    observer_path: Path,
    *,
    child_rc: int,
    unittest_rc: int = 0,
    probe_started_mtime: float | None = None,
) -> dict[str, Any]:
    """Verdict for gate 26. Never treat ok=false or a stale PASS as success."""
    if not observer_path.is_file():
        return _gate_verdict(
            False,
            "FAIL",
            "observer did not write mqtt_acl_observer.json",
            child_rc,
        )
    if (
        probe_started_mtime is not None
        and observer_path.stat().st_mtime < probe_started_mtime
    ):
        return _gate_verdict(
            False,
            "ERROR",
            "stale mqtt_acl_observer.json predates this run",
            child_rc,
        )
    try:
        loaded = json.loads(observer_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _gate_verdict(False, "ERROR", "observer JSON is not valid", child_rc)
    if not isinstance(loaded, dict):
        return _gate_verdict(False, "ERROR", "observer JSON root must be object", child_rc)
    if unittest_rc != 0:
        return _gate_verdict(False, "FAIL", f"unittest_rc={unittest_rc}", child_rc)
    ok_flag = loaded.get("ok")
    status = str(loaded.get("status") or "")
    reason = str(loaded.get("reason") or loaded.get("detail") or "")
    if ok_flag is False and status == "PASS":
        return _gate_verdict(
            False,
            "ERROR",
            "observer ok=false contradicts status PASS",
            child_rc,
        )
    if ok_flag is True and status == "PASS" and child_rc != 0:
        return _gate_verdict(
            False,
            "ERROR",
            f"observer PASS but child_rc={child_rc} (contradictory)",
            child_rc,
        )
    if ok_flag is True and status == "PASS" and child_rc == 0:
        return _gate_verdict(True, "PASS", reason or "ok", child_rc)
    if status == "FAIL" or ok_flag is False:
        return _gate_verdict(False, "FAIL", reason or "observer not ok", child_rc)
    if status == "BLOCKED":
        return _gate_verdict(False, "BLOCKED", reason or "observer blocked", child_rc)
    return _gate_verdict(
        False,
        "ERROR",
        f"unusable observer status={status!r}",
        child_rc,
    )


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
