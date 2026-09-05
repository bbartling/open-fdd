#!/usr/bin/env python3
"""Open-FDD qualification run manifest (schema v1).

Truthful verdicts: PASS | FAIL | ERROR | SKIPPED | BLOCKED | NOT_APPLICABLE.
A required gate that is SKIPPED/BLOCKED/ERROR cannot yield overall PASS / QUALIFIED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "openfdd_qualification_manifest_v1"
VALID = frozenset(
    {"PASS", "FAIL", "ERROR", "SKIPPED", "BLOCKED", "NOT_APPLICABLE"}
)
# Gates that must PASS (or NOT_APPLICABLE) for full field qualification.
DEFAULT_REQUIRED = (
    "00_hub_health_edges",
    "01_synth59",
    "02_gate17",
    "03_b100",
    "04_creekside",
    "05_gate19",
    "06_zap_baseline",
    "07_auth_role_matrix",
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def new_manifest(
    *,
    run_id: str,
    environment_class: str,
    hub_base: str,
    candidate_sha: str | None,
    harness_sha: str | None,
    required_gates: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "environment_class": environment_class,
        "hub_base": hub_base,
        "candidate": {
            "source_sha": candidate_sha,
            "image_tag": os.environ.get("OPENFDD_IMAGE_TAG"),
            "digests": {},
            "revisions_start": {},
            "revisions_end": {},
        },
        "harness_sha": harness_sha,
        "started_at": _now(),
        "ended_at": None,
        "required_gates": list(required_gates),
        "gates": {},
        "dimensions": {
            "data_correctness": None,
            "transport_durability": None,
            "browser_behavior": None,
            "api_mcp_contracts": None,
            "security": None,
            "performance": None,
        },
        "overall": {
            "status": "RUNNING",
            "fully_qualified": False,
            "reason": None,
        },
        "warnings_accepted": [],
        "artifacts": {},
        "notes": [],
    }


def record_gate(
    manifest: dict[str, Any],
    gate_id: str,
    status: str,
    *,
    title: str | None = None,
    measured: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    artifact_paths: list[str] | None = None,
    failure_reason: str | None = None,
    coverage: dict[str, Any] | None = None,
    duration_secs: float | None = None,
) -> None:
    status = status.upper()
    if status not in VALID:
        raise SystemExit(f"invalid gate status {status!r}; want one of {sorted(VALID)}")
    entry: dict[str, Any] = {
        "gate_id": gate_id,
        "title": title or gate_id,
        "status": status,
        "recorded_at": _now(),
        "duration_secs": duration_secs,
        "measured": measured or {},
        "thresholds": thresholds or {},
        "coverage": coverage or {},
        "artifact_paths": artifact_paths or [],
        "artifact_hashes": {},
        "failure_reason": failure_reason,
    }
    for p in entry["artifact_paths"]:
        digest = _sha256_file(Path(p))
        if digest:
            entry["artifact_hashes"][p] = digest
    manifest["gates"][gate_id] = entry


def finalize(manifest: dict[str, Any]) -> dict[str, Any]:
    required = list(manifest.get("required_gates") or [])
    missing = [g for g in required if g not in manifest.get("gates", {})]
    for g in missing:
        record_gate(
            manifest,
            g,
            "ERROR",
            title=g,
            failure_reason="required gate never recorded (missing/malformed evidence)",
        )

    blockers: list[str] = []
    fails: list[str] = []
    for gid in required:
        st = manifest["gates"][gid]["status"]
        if st in ("FAIL",):
            fails.append(f"{gid}={st}")
        elif st in ("ERROR", "BLOCKED", "SKIPPED"):
            blockers.append(f"{gid}={st}")
        elif st == "NOT_APPLICABLE":
            continue
        elif st != "PASS":
            blockers.append(f"{gid}={st}")

    fully = not fails and not blockers
    if fully:
        status = "PASS"
        reason = "all required gates PASS (or NOT_APPLICABLE)"
    elif fails and not blockers:
        status = "FAIL"
        reason = "required gate failure: " + ", ".join(fails)
    elif blockers and not fails:
        status = "BLOCKED"
        reason = "required gate not fully qualified: " + ", ".join(blockers)
    else:
        status = "FAIL"
        reason = "failures=" + ", ".join(fails) + "; blockers=" + ", ".join(blockers)

    # Dimension rollups (best-effort from gate ids)
    def any_status(*ids: str) -> str | None:
        vals = [manifest["gates"][i]["status"] for i in ids if i in manifest["gates"]]
        if not vals:
            return None
        for bad in ("FAIL", "ERROR", "BLOCKED", "SKIPPED"):
            if bad in vals:
                return bad
        return "PASS" if all(v in ("PASS", "NOT_APPLICABLE") for v in vals) else vals[0]

    manifest["dimensions"] = {
        "data_correctness": any_status(
            "01_synth59", "02_gate17", "03_b100", "04_creekside", "05_gate19"
        ),
        "transport_durability": any_status("00_hub_health_edges"),
        "browser_behavior": None,
        "api_mcp_contracts": any_status("07_auth_role_matrix", "08_mcp_accuracy"),
        "security": any_status("06_zap_baseline", "07_auth_role_matrix"),
        "performance": None,
    }
    manifest["ended_at"] = _now()
    manifest["overall"] = {
        "status": status,
        "fully_qualified": fully,
        "reason": reason,
    }
    return manifest


def render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        f"# Qualification report — {manifest.get('run_id')}",
        "",
        f"- Schema: `{manifest.get('schema_version')}`",
        f"- Environment: `{manifest.get('environment_class')}`",
        f"- Hub: `{manifest.get('hub_base')}`",
        f"- Candidate SHA: `{((manifest.get('candidate') or {}).get('source_sha'))}`",
        f"- Image tag: `{((manifest.get('candidate') or {}).get('image_tag'))}`",
        f"- Started: `{manifest.get('started_at')}`  Ended: `{manifest.get('ended_at')}`",
        "",
        "## Gates",
        "",
        "| Gate | Status | Reason / notes |",
        "|------|--------|----------------|",
    ]
    for gid in manifest.get("required_gates") or []:
        g = (manifest.get("gates") or {}).get(gid) or {}
        reason = g.get("failure_reason") or ""
        lines.append(
            f"| `{gid}` | **{g.get('status', 'MISSING')}** | {reason} |"
        )
    # Extra recorded gates
    for gid, g in sorted((manifest.get("gates") or {}).items()):
        if gid in (manifest.get("required_gates") or []):
            continue
        lines.append(
            f"| `{gid}` | **{g.get('status')}** | {g.get('failure_reason') or ''} |"
        )
    ov = manifest.get("overall") or {}
    lines += [
        "",
        "## Overall",
        "",
        f"- Status: **{ov.get('status')}**",
        f"- Fully qualified: `{ov.get('fully_qualified')}`",
        f"- Reason: {ov.get('reason')}",
        "",
        "## Dimensions",
        "",
    ]
    for k, v in (manifest.get("dimensions") or {}).items():
        lines.append(f"- `{k}`: {v}")
    if manifest.get("warnings_accepted"):
        lines += ["", "## Accepted warnings", ""]
        for w in manifest["warnings_accepted"]:
            lines.append(f"- {w}")
    lines.append("")
    return "\n".join(lines)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--out", required=True)
    c.add_argument("--run-id", required=True)
    c.add_argument("--environment-class", default="railway_field")
    c.add_argument("--hub-base", required=True)
    c.add_argument("--candidate-sha")
    c.add_argument("--harness-sha")
    c.add_argument(
        "--required",
        action="append",
        dest="required",
        help="required gate id (repeatable); default built-in set if omitted",
    )

    r = sub.add_parser("record")
    r.add_argument("--manifest", required=True)
    r.add_argument("--gate", required=True)
    r.add_argument("--status", required=True)
    r.add_argument("--title")
    r.add_argument("--reason")
    r.add_argument("--artifact", action="append", default=[])
    r.add_argument("--measured-json")
    r.add_argument("--duration-secs", type=float)

    f = sub.add_parser("finalize")
    f.add_argument("--manifest", required=True)
    f.add_argument("--summary-md")

    t = sub.add_parser("selftest")

    args = p.parse_args(argv)

    if args.cmd == "create":
        required = args.required or list(DEFAULT_REQUIRED)
        m = new_manifest(
            run_id=args.run_id,
            environment_class=args.environment_class,
            hub_base=args.hub_base,
            candidate_sha=args.candidate_sha,
            harness_sha=args.harness_sha,
            required_gates=required,
        )
        save(Path(args.out), m)
        print(args.out)
        return 0

    if args.cmd == "record":
        path = Path(args.manifest)
        m = load(path)
        measured = json.loads(args.measured_json) if args.measured_json else None
        record_gate(
            m,
            args.gate,
            args.status,
            title=args.title,
            failure_reason=args.reason,
            artifact_paths=args.artifact,
            measured=measured,
            duration_secs=args.duration_secs,
        )
        save(path, m)
        return 0

    if args.cmd == "finalize":
        path = Path(args.manifest)
        m = finalize(load(path))
        save(path, m)
        md = render_markdown(m)
        summary = Path(args.summary_md) if args.summary_md else path.with_suffix(".md")
        summary.write_text(md, encoding="utf-8")
        print(md)
        # Exit codes: 0 PASS fully_qualified; 2 BLOCKED; 1 FAIL/ERROR
        ov = m["overall"]
        if ov["fully_qualified"]:
            return 0
        if ov["status"] == "BLOCKED":
            return 2
        return 1

    if args.cmd == "selftest":
        # Harness-of-harness: skipped required ZAP must not fully qualify.
        m = new_manifest(
            run_id="selftest",
            environment_class="unit",
            hub_base="http://example.test",
            candidate_sha="deadbeef",
            harness_sha="cafe",
            required_gates=["00_hub_health_edges", "06_zap_baseline"],
        )
        record_gate(m, "00_hub_health_edges", "PASS")
        record_gate(
            m,
            "06_zap_baseline",
            "SKIPPED",
            failure_reason="SKIP_ZAP=1",
        )
        m = finalize(m)
        assert m["overall"]["fully_qualified"] is False, m
        assert m["overall"]["status"] == "BLOCKED", m
        # Missing gate → ERROR → not qualified
        m2 = new_manifest(
            run_id="selftest2",
            environment_class="unit",
            hub_base="http://example.test",
            candidate_sha=None,
            harness_sha=None,
            required_gates=["00_hub_health_edges", "06_zap_baseline"],
        )
        record_gate(m2, "00_hub_health_edges", "PASS")
        m2 = finalize(m2)
        assert m2["gates"]["06_zap_baseline"]["status"] == "ERROR"
        assert m2["overall"]["fully_qualified"] is False
        # All PASS → qualified
        m3 = new_manifest(
            run_id="selftest3",
            environment_class="unit",
            hub_base="http://example.test",
            candidate_sha=None,
            harness_sha=None,
            required_gates=["00_hub_health_edges", "06_zap_baseline"],
        )
        record_gate(m3, "00_hub_health_edges", "PASS")
        record_gate(m3, "06_zap_baseline", "PASS")
        m3 = finalize(m3)
        assert m3["overall"]["fully_qualified"] is True
        assert m3["overall"]["status"] == "PASS"
        print("selftest OK")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
