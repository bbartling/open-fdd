#!/usr/bin/env python3
"""Import / validate Nessus (.nessus XML) reports for Open-FDD readiness.

Never invent a PASS without a real report. Missing licensed scan → BLOCKED.
Synthetic fixtures under scripts/security/nessus/fixtures/ exercise the importer.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


MAX_BYTES = 64 * 1024 * 1024  # 64 MiB
MAX_HOSTS = 512
MAX_ITEMS = 10000
EXPECTATION_SCHEMA_VERSION = "openfdd_nessus_expectation_v1"
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


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
        raw_xml = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot read report: {exc}") from exc
    # ElementTree does not fetch external entities, but reject DTD/entity
    # declarations explicitly so this importer has a clear bounded policy even
    # when the parser implementation changes.
    upper_xml = raw_xml.upper()
    if b"<!DOCTYPE" in upper_xml or b"<!ENTITY" in upper_xml:
        raise SystemExit("ERROR: DTD/entity declarations are forbidden")
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        raise SystemExit(f"ERROR: malformed .nessus XML: {e}") from e
    if root.tag.rsplit("}", 1)[-1] != "NessusClientData_v2":
        raise SystemExit("ERROR: unexpected Nessus XML root")
    hosts: list[dict[str, Any]] = []
    crit = high = med = low = info = 0
    total_items = 0
    report_names = [str(item.get("name") or "") for item in root.iter("Report")]
    metadata: dict[str, str] = {}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        name = str(element.get("name") or "").strip().lower().replace("-", "_")
        value = (element.text or "").strip()
        if name and value and name in {
            "openfdd_candidate_sha",
            "candidate_sha256",
            "candidate_id",
            "openfdd_scan_complete",
            "scan_complete",
            "openfdd_policy",
            "policy_name",
            "openfdd_feed_version",
            "feed_version",
            "scan_start",
            "scan_started_at",
            "scan_end",
            "scan_ended_at",
        }:
            metadata[name] = value
        if tag in {"scan_start", "scan_started_at", "scan_end", "scan_ended_at"} and value:
            metadata[tag] = value
        if tag in {"policyname", "policy_name"} and value:
            metadata["policy_name"] = value
        if tag in {"feedversion", "feed_version"} and value:
            metadata["feed_version"] = value
    for report_host in root.iter("ReportHost"):
        if len(hosts) >= MAX_HOSTS:
            raise SystemExit(f"ERROR: host count exceeds bound {MAX_HOSTS}")
        name = report_host.get("name") or ""
        items = []
        credentialed_checks: bool | None = None
        aliases = {name} if name else set()
        host_properties = report_host.find("HostProperties")
        if host_properties is not None:
            for tag in host_properties.findall("tag"):
                tag_name = str(tag.get("name") or "").strip().lower()
                tag_value = (tag.text or "").strip()
                if tag_name and tag_value:
                    aliases.add(tag_value)
                    normalized = tag_name.replace("-", "_")
                    if normalized in {
                        "openfdd_candidate_sha",
                        "candidate_sha256",
                        "candidate_id",
                        "openfdd_scan_complete",
                        "scan_complete",
                        "openfdd_policy",
                        "policy_name",
                        "openfdd_feed_version",
                        "feed_version",
                        "scan_start",
                        "scan_started_at",
                        "scan_end",
                        "scan_ended_at",
                    }:
                        metadata[normalized] = tag_value
        for item in report_host.findall("ReportItem"):
            total_items += 1
            if total_items > MAX_ITEMS:
                raise SystemExit(f"ERROR: ReportItem count exceeds bound {MAX_ITEMS}")
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
                "aliases": sorted(aliases),
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
        "report_names": report_names,
        "target_aliases": sorted({alias for host in hosts for alias in host["aliases"]}),
        "candidate_sha256": metadata.get("openfdd_candidate_sha")
        or metadata.get("candidate_sha256")
        or metadata.get("candidate_id"),
        "policy_name": metadata.get("openfdd_policy") or metadata.get("policy_name"),
        "feed_version": metadata.get("openfdd_feed_version") or metadata.get("feed_version"),
        "started_at": metadata.get("scan_start") or metadata.get("scan_started_at"),
        "ended_at": metadata.get("scan_end") or metadata.get("scan_ended_at"),
        "completion": metadata.get("openfdd_scan_complete") or metadata.get("scan_complete"),
    }


def _parse_scan_time(value: str | None) -> dt.datetime | None:
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _scan_reference_time(measured: dict[str, Any]) -> dt.datetime | None:
    return _parse_scan_time(measured.get("ended_at")) or _parse_scan_time(
        measured.get("started_at")
    )


def _completion_ok(value: str | None) -> bool:
    if value is None:
        return False
    token = str(value).strip().lower()
    return token in {"yes", "true", "1", "complete", "completed", "done"}


def _normalize_sha256(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    if not SHA256_RE.fullmatch(text):
        return None
    return text


def _iter_medium_findings(
    measured: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    findings: list[tuple[str, dict[str, Any]]] = []
    for host in measured.get("hosts") or []:
        host_name = str(host.get("name") or "")
        for item in host.get("items") or []:
            if int(item.get("severity") or 0) == 2:
                findings.append((host_name, item))
    return findings


def _disposition_matches(
    host_name: str,
    item: dict[str, Any],
    disposition: dict[str, Any],
) -> bool:
    if str(disposition.get("plugin_id") or "") != str(item.get("plugin_id") or ""):
        return False
    disp_host = disposition.get("host")
    if disp_host is not None and str(disp_host) != host_name:
        return False
    disp_port = disposition.get("port")
    if disp_port is not None and str(disp_port) != str(item.get("port") or ""):
        return False
    return True


def _validate_medium_dispositions(
    measured: dict[str, Any],
    medium_dispositions: list[dict[str, Any]],
    *,
    now: dt.datetime | None = None,
) -> str | None:
    if not isinstance(medium_dispositions, list) or not medium_dispositions:
        return "blanket Medium acceptance is forbidden; supply exact dispositions"
    clock = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    findings = _iter_medium_findings(measured)
    used_indices: set[int] = set()
    for host_name, item in findings:
        match_index: int | None = None
        for index, disposition in enumerate(medium_dispositions):
            if index in used_indices:
                continue
            if not isinstance(disposition, dict):
                return "medium disposition entries must be objects"
            if _disposition_matches(host_name, item, disposition):
                match_index = index
                break
        if match_index is None:
            plugin_id = item.get("plugin_id") or "?"
            return (
                f"unmatched Medium finding plugin_id={plugin_id} "
                f"host={host_name or '<unnamed>'} port={item.get('port')}"
            )
        disposition = medium_dispositions[match_index]
        for field in ("owner", "rationale", "expires_at"):
            if not str(disposition.get(field) or "").strip():
                return f"medium disposition missing {field} for plugin_id={item.get('plugin_id')}"
        expires = _parse_scan_time(str(disposition.get("expires_at")))
        if expires is None:
            return f"medium disposition has invalid expires_at for plugin_id={item.get('plugin_id')}"
        if clock > expires:
            return f"expired medium disposition for plugin_id={item.get('plugin_id')}"
        used_indices.add(match_index)
    return None


def _evaluate_expectation(
    measured: dict[str, Any],
    expectation: dict[str, Any],
    *,
    now: dt.datetime | None = None,
) -> str | None:
    if not isinstance(expectation, dict):
        return "expectation manifest must be an object"
    if expectation.get("schema_version") != EXPECTATION_SCHEMA_VERSION:
        return f"unsupported expectation schema_version (want {EXPECTATION_SCHEMA_VERSION})"
    expected_targets = expectation.get("expected_targets")
    if not isinstance(expected_targets, list) or not expected_targets:
        return "expectation missing expected_targets"
    expected_set = {str(target).strip() for target in expected_targets if str(target).strip()}
    if not expected_set:
        return "expectation missing expected_targets"
    aliases = set(measured.get("target_aliases") or [])
    missing = sorted(expected_set - aliases)
    if missing:
        return "expected targets missing from scan: " + ", ".join(missing)
    if expectation.get("reject_foreign_targets", True):
        for host in measured.get("hosts") or []:
            host_name = str(host.get("name") or "").strip()
            if host_name and host_name not in expected_set:
                return f"foreign ReportHost not in expectation: {host_name}"
    expected_candidate = _normalize_sha256(expectation.get("candidate_sha256"))
    if expected_candidate is not None:
        measured_candidate = _normalize_sha256(measured.get("candidate_sha256"))
        if measured_candidate != expected_candidate:
            return "candidate_sha256 mismatch"
    expected_policy = str(expectation.get("policy_name") or "").strip()
    if expected_policy:
        measured_policy = str(measured.get("policy_name") or "").strip()
        if measured_policy != expected_policy:
            return "policy_name mismatch"
    expected_feed = str(expectation.get("feed_version") or "").strip()
    if expected_feed:
        measured_feed = str(measured.get("feed_version") or "").strip()
        if measured_feed != expected_feed:
            return "feed_version mismatch"
    expected_reports = expectation.get("report_names")
    if expected_reports is not None:
        if not isinstance(expected_reports, list) or not expected_reports:
            return "expectation report_names must be a non-empty list"
        measured_reports = {str(name) for name in measured.get("report_names") or []}
        for report_name in expected_reports:
            if str(report_name) not in measured_reports:
                return f"report name missing from scan: {report_name}"
    max_age = expectation.get("max_age_seconds", DEFAULT_MAX_AGE_SECONDS)
    try:
        max_age_seconds = int(max_age)
    except (TypeError, ValueError):
        return "expectation max_age_seconds must be an integer"
    if max_age_seconds <= 0:
        return "expectation max_age_seconds must be positive"
    if expectation.get("require_scan_complete", True):
        if not _completion_ok(measured.get("completion")):
            return "scan completion metadata missing or not affirmative"
    reference = _scan_reference_time(measured)
    if reference is None:
        return "scan timestamps missing for freshness validation"
    clock = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    age_seconds = (clock - reference).total_seconds()
    if age_seconds < 0:
        return "scan reference time is in the future"
    if age_seconds > max_age_seconds:
        return f"scan older than max_age_seconds ({max_age_seconds})"
    return None


def load_json_document(path: Path, *, label: str) -> Any:
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {label} {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: invalid {label} JSON: {exc}") from exc
    return payload


def evaluate(
    measured: dict[str, Any],
    *,
    require_credentialed: bool,
    allow_medium: bool,
    expectation: dict[str, Any] | None = None,
    medium_dispositions: list[dict[str, Any]] | None = None,
    now: dt.datetime | None = None,
) -> tuple[bool, str]:
    if not isinstance(measured, dict) or not isinstance(measured.get("counts"), dict):
        return False, "missing Nessus counts"
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
    if c["medium"]:
        if not allow_medium:
            return False, f"Medium={c['medium']} without dispositions"
        if not medium_dispositions:
            return False, "blanket Medium acceptance is forbidden; supply exact dispositions"
        disposition_error = _validate_medium_dispositions(measured, medium_dispositions, now=now)
        if disposition_error:
            return False, disposition_error
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
    if expectation is not None:
        binding_error = _evaluate_expectation(measured, expectation, now=now)
        if binding_error:
            return False, binding_error
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
        help="accept Medium only when exact dispositions JSON is supplied",
    )
    p.add_argument(
        "--expectation",
        help="JSON manifest binding targets, candidate, policy, freshness, completion",
    )
    p.add_argument(
        "--medium-dispositions",
        help="JSON list of scoped Medium dispositions (required with --allow-medium)",
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
        medium = parse_nessus(fixtures / "medium_synthetic.nessus")
        ok, reason = evaluate(medium, require_credentialed=False, allow_medium=True)
        assert not ok and "disposition" in reason
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
    expectation = None
    if args.expectation:
        expectation = load_json_document(Path(args.expectation), label="expectation")
    medium_dispositions = None
    if args.medium_dispositions:
        medium_dispositions = load_json_document(
            Path(args.medium_dispositions),
            label="medium dispositions",
        )
    if args.allow_medium and medium_dispositions is None:
        p.error("--allow-medium requires --medium-dispositions")
    measured = parse_nessus(Path(args.report))
    ok, reason = evaluate(
        measured,
        require_credentialed=args.require_credentialed,
        allow_medium=args.allow_medium,
        expectation=expectation,
        medium_dispositions=medium_dispositions,
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
