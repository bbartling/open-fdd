#!/usr/bin/env python3
"""Profile-bound final-image digest / SBOM / provenance evaluator (Astra A09).

Offline-first: validates a machine-readable scan evidence record against the
deployment profile's required_images. Never claims signing from workflow file
presence alone. Does not pull images or run Trivy unless --invoke-trivy is set
(operator opt-in; still not an FQ claim).

Usage:
  python3 scripts/security/profile_image_scan.py --list-profiles
  python3 scripts/security/profile_image_scan.py --selftest
  python3 scripts/security/profile_image_scan.py \\
      --profile cloud_mqtt_hub --evidence reports/security/image_scan.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SYS_SEC = Path(__file__).resolve().parent
if str(SYS_SEC) not in sys.path:
    sys.path.insert(0, str(SYS_SEC))

from openfdd_security.deployment import load_profile_registry  # noqa: E402

SCHEMA = "openfdd_profile_image_scan_v1"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# Proxy/broker/edge images that must appear when profile requires them.
PROXY_ALIASES = {
    "caddy": ("caddy", "docker.io/library/caddy"),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def profile_required_scan_images(profile_id: str) -> list[str]:
    """Return ordered image short-names a profile must scan."""
    registry = load_profile_registry()
    profiles = registry.get("profiles") or {}
    if profile_id not in profiles:
        raise SystemExit(f"unknown profile: {profile_id}")
    prof = profiles[profile_id]
    names = list(prof.get("required_images") or [])
    # OT profiles always include Caddy (TLS edge) when listed in required_services.
    services = set(prof.get("required_services") or [])
    if "caddy" in services and "caddy" not in names:
        names.append("caddy")
    # Keep broker when required.
    if "openfdd-mqtt" in services and "openfdd-mqtt" not in names:
        names.append("openfdd-mqtt")
    return names


def _normalize_name(name: str) -> str:
    n = (name or "").strip()
    if n.startswith("openfdd-"):
        return n
    if n in ("central", "web", "mqtt", "fieldbus", "bacnet-modbus", "haystack", "mcp"):
        return f"openfdd-{n}"
    if n == "caddy" or n.startswith("docker.io/library/caddy"):
        return "caddy"
    return n


def evaluate_scan_evidence(
    profile_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Fail-closed evaluation of profile-bound image scan evidence."""
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def add(cid: str, ok: bool, detail: str) -> None:
        checks.append({"id": cid, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"{cid}: {detail}")

    if evidence.get("schema_version") != SCHEMA:
        add("schema", False, f"expected {SCHEMA}, got {evidence.get('schema_version')!r}")
        return _report(profile_id, "ERROR", checks, errors)

    if evidence.get("profile_id") != profile_id:
        add(
            "profile_bind",
            False,
            f"evidence profile_id={evidence.get('profile_id')!r} != {profile_id!r}",
        )

    required = profile_required_scan_images(profile_id)
    add("required_images_nonempty", bool(required), f"count={len(required)}")

    images = evidence.get("images")
    if not isinstance(images, list) or not images:
        add("images_present", False, "images[] missing or empty")
        return _report(profile_id, "FAIL", checks, errors)

    by_name: dict[str, dict[str, Any]] = {}
    for idx, img in enumerate(images):
        if not isinstance(img, dict):
            add(f"image[{idx}].shape", False, "must be object")
            continue
        name = _normalize_name(str(img.get("name") or ""))
        digest = str(img.get("digest") or "").strip()
        ref = str(img.get("ref") or "").strip()
        platform = str(img.get("platform") or "").strip()
        if not name:
            add(f"image[{idx}].name", False, "missing name")
            continue
        if name in by_name:
            add(f"image.{name}.duplicate", False, "duplicate image name")
        by_name[name] = img
        # Digest must be immutable; moving tags alone are insufficient.
        digest_ok = bool(DIGEST_RE.match(digest))
        add(f"image.{name}.digest", digest_ok, digest or "missing")
        # Tag-only refs without digest are FAIL for qualification.
        if ref and "@sha256:" not in ref and not digest_ok:
            add(f"image.{name}.immutable_ref", False, "tag-only ref without digest")
        elif ref or digest_ok:
            add(f"image.{name}.immutable_ref", True, ref or digest)
        if not platform:
            add(f"image.{name}.platform", False, "platform missing")
        else:
            add(f"image.{name}.platform", True, platform)

    for req in required:
        key = _normalize_name(req)
        present = key in by_name
        add(f"required.{key}", present, "present" if present else "missing from evidence")

    # Scanner metadata (pinned tool + DB when available).
    scanner = evidence.get("scanner") or {}
    if not isinstance(scanner, dict):
        add("scanner.meta", False, "scanner must be object")
        scanner = {}
    tool = str(scanner.get("tool") or "").strip()
    version = str(scanner.get("version") or "").strip()
    add("scanner.tool", bool(tool), tool or "missing")
    add("scanner.version", bool(version), version or "missing")
    # Moving "latest" without digest pin is not qualification.
    if "latest" in version.lower() and "sha256:" not in version:
        add("scanner.not_floating_latest", False, version)

    # Findings: Critical/High must be zero unless explicitly dispositioned.
    findings = evidence.get("findings") or {}
    if not isinstance(findings, dict):
        add("findings.shape", False, "findings must be object")
        findings = {}
    high = int(findings.get("high") or 0)
    critical = int(findings.get("critical") or 0)
    add("findings.critical_zero", critical == 0, f"critical={critical}")
    add("findings.high_zero", high == 0, f"high={high}")
    medium = int(findings.get("medium") or 0)
    dispositions = evidence.get("medium_dispositions") or []
    if medium > 0:
        if not isinstance(dispositions, list) or len(dispositions) < medium:
            add(
                "findings.medium_dispositioned",
                False,
                f"medium={medium} dispositions={len(dispositions) if isinstance(dispositions, list) else 0}",
            )
        else:
            add("findings.medium_dispositioned", True, f"medium={medium}")

    # SBOM + provenance: require explicit evidence fields; do not infer from
    # workflow YAML presence (A09).
    sbom = evidence.get("sbom") or {}
    provenance = evidence.get("provenance") or {}
    if not isinstance(sbom, dict):
        add("sbom.shape", False, "sbom must be object")
        sbom = {}
    if not isinstance(provenance, dict):
        add("provenance.shape", False, "provenance must be object")
        provenance = {}

    sbom_status = str(sbom.get("status") or "").upper()
    # BLOCKED is honest when SBOM tooling was not run; FAIL if claimed without artifacts.
    if sbom_status == "PRESENT":
        arts = sbom.get("artifact_digests") or []
        ok = isinstance(arts, list) and len(arts) > 0 and all(
            DIGEST_RE.match(str(a)) for a in arts
        )
        add("sbom.present", ok, f"artifacts={len(arts) if isinstance(arts, list) else 0}")
    elif sbom_status in {"ABSENT", "BLOCKED", "NOT_RUN"}:
        add("sbom.honest_absent", True, sbom_status)
        # Soft-OPEN for qualification: absent SBOM does not invent PASS.
        errors.append(f"sbom: {sbom_status} (Soft-OPEN — not a signing claim)")
    else:
        add("sbom.status", False, f"unknown status {sbom_status!r}")

    prov_status = str(provenance.get("status") or "").upper()
    if prov_status == "VERIFIED":
        # Require attestation digests or explicit verifier output hash — never
        # "workflow_file_present".
        method = str(provenance.get("method") or "")
        if method in {"workflow_file_present", "workflow_exists", "ci_yaml"}:
            add(
                "provenance.not_workflow_inference",
                False,
                "must not infer signing from workflow file presence",
            )
        else:
            att = provenance.get("attestation_digests") or []
            ok = isinstance(att, list) and len(att) > 0
            add("provenance.verified", ok, method or "missing method")
    elif prov_status in {"ABSENT", "BLOCKED", "NOT_RUN", "UNVERIFIED"}:
        add("provenance.honest_absent", True, prov_status)
        errors.append(f"provenance: {prov_status} (Soft-OPEN — not a signing claim)")
    else:
        add("provenance.status", False, f"unknown status {prov_status!r}")

    # Overall: hard FAILs from checks; Soft-OPEN absences → BLOCKED if no hard fail.
    hard_fail = any(
        (not c["ok"]) and not c["id"].startswith("sbom.honest") and not c["id"].startswith("provenance.honest")
        for c in checks
    )
    soft_open = any(
        e.startswith("sbom:") or e.startswith("provenance:") for e in errors
    )
    if hard_fail:
        # Drop soft-open notes from driving ERROR when hard fail exists.
        hard_errors = [
            e
            for e in errors
            if not (e.startswith("sbom:") or e.startswith("provenance:"))
        ]
        status = "FAIL"
        errors = hard_errors or errors
    elif soft_open:
        status = "BLOCKED"
    else:
        status = "PASS"

    return _report(profile_id, status, checks, errors)


def _report(
    profile_id: str,
    status: str,
    checks: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "profile_id": profile_id,
        "status": status,
        "ok": status == "PASS",
        "checked_at": _now(),
        "checks": checks,
        "errors": errors,
        "notes": (
            "Profile-bound image digest/SBOM/provenance evaluation. "
            "Not Nessus. Not FQ. Soft-OPEN when SBOM/provenance absent."
        ),
    }


def selftest() -> dict[str, Any]:
    """Healthy + sabotage fixtures for the evaluator."""
    results: list[dict[str, Any]] = []

    def digest(n: int = 1) -> str:
        return "sha256:" + (f"{n:x}" * 64)[:64]

    healthy_images = [
        {
            "name": "openfdd-web",
            "digest": digest(1),
            "ref": f"ghcr.io/bbartling/openfdd-web@{digest(1)}",
            "platform": "linux/amd64",
        },
        {
            "name": "openfdd-central",
            "digest": digest(2),
            "ref": f"ghcr.io/bbartling/openfdd-central@{digest(2)}",
            "platform": "linux/amd64",
        },
        {
            "name": "openfdd-mqtt",
            "digest": digest(3),
            "ref": f"ghcr.io/bbartling/openfdd-mqtt@{digest(3)}",
            "platform": "linux/amd64",
        },
    ]
    healthy = {
        "schema_version": SCHEMA,
        "profile_id": "cloud_mqtt_hub",
        "images": healthy_images,
        "scanner": {"tool": "trivy", "version": "0.56.0"},
        "findings": {"critical": 0, "high": 0, "medium": 0},
        "sbom": {"status": "PRESENT", "artifact_digests": [digest(9)]},
        "provenance": {
            "status": "VERIFIED",
            "method": "cosign_verify_attestation",
            "attestation_digests": [digest(8)],
        },
    }
    r = evaluate_scan_evidence("cloud_mqtt_hub", healthy)
    results.append({"case": "healthy_pass", "ok": r["status"] == "PASS", "status": r["status"]})

    # Sabotage: workflow-file inference
    bad_prov = json.loads(json.dumps(healthy))
    bad_prov["provenance"] = {
        "status": "VERIFIED",
        "method": "workflow_file_present",
        "attestation_digests": [digest(8)],
    }
    r = evaluate_scan_evidence("cloud_mqtt_hub", bad_prov)
    results.append(
        {
            "case": "workflow_inference_fail",
            "ok": r["status"] == "FAIL",
            "status": r["status"],
        }
    )

    # Sabotage: missing connector image for OT profile
    ot_ev = {
        "schema_version": SCHEMA,
        "profile_id": "ot_local_bacnet_modbus",
        "images": [
            {
                "name": "openfdd-web",
                "digest": digest(1),
                "ref": f"ghcr.io/bbartling/openfdd-web@{digest(1)}",
                "platform": "linux/amd64",
            },
            {
                "name": "openfdd-central",
                "digest": digest(2),
                "ref": f"ghcr.io/bbartling/openfdd-central@{digest(2)}",
                "platform": "linux/amd64",
            },
            {
                "name": "caddy",
                "digest": digest(4),
                "ref": f"docker.io/library/caddy@{digest(4)}",
                "platform": "linux/amd64",
            },
            # missing openfdd-bacnet-modbus
        ],
        "scanner": {"tool": "trivy", "version": "0.56.0"},
        "findings": {"critical": 0, "high": 0, "medium": 0},
        "sbom": {"status": "BLOCKED"},
        "provenance": {"status": "NOT_RUN"},
    }
    r = evaluate_scan_evidence("ot_local_bacnet_modbus", ot_ev)
    results.append(
        {
            "case": "missing_connector_fail",
            "ok": r["status"] == "FAIL",
            "status": r["status"],
        }
    )

    # Soft-OPEN: honest absent SBOM/provenance with complete digests → BLOCKED
    soft = json.loads(json.dumps(healthy))
    soft["sbom"] = {"status": "NOT_RUN"}
    soft["provenance"] = {"status": "ABSENT"}
    r = evaluate_scan_evidence("cloud_mqtt_hub", soft)
    results.append(
        {
            "case": "honest_absent_blocked",
            "ok": r["status"] == "BLOCKED",
            "status": r["status"],
        }
    )

    # Tag-only without digest
    tag_only = json.loads(json.dumps(healthy))
    tag_only["images"][0]["digest"] = ""
    tag_only["images"][0]["ref"] = "ghcr.io/bbartling/openfdd-web:nightly"
    r = evaluate_scan_evidence("cloud_mqtt_hub", tag_only)
    results.append(
        {
            "case": "tag_only_fail",
            "ok": r["status"] == "FAIL",
            "status": r["status"],
        }
    )

    ok = all(x["ok"] for x in results)
    return {
        "schema_version": SCHEMA,
        "mode": "selftest",
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "cases": results,
        "checked_at": _now(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--profile", default="")
    ap.add_argument("--evidence", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.list_profiles:
        registry = load_profile_registry()
        for pid in sorted((registry.get("profiles") or {})):
            imgs = profile_required_scan_images(pid)
            print(f"{pid}: {', '.join(imgs)}")
        return 0

    if args.selftest:
        report = selftest()
        text = json.dumps(report, indent=2) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0 if report["ok"] else 1

    if not args.profile or not args.evidence:
        ap.error("--profile and --evidence required (or --selftest / --list-profiles)")
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    report = evaluate_scan_evidence(args.profile, evidence)
    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["status"] == "PASS" else (2 if report["status"] == "BLOCKED" else 1)


if __name__ == "__main__":
    sys.exit(main())
