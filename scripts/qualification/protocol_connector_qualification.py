#!/usr/bin/env python3
"""Bounded, fail-closed qualification evidence for the protocol connectors.

This is an evidence evaluator and a small offline qualification entry point. It
does not discover OT devices, accept credentials, or invent a successful live
run. The image/recipe gate and the operator bench commands produce evidence
files which this script can evaluate without copying their sensitive payloads
into the report.

Examples::

    # CI-safe synthetic contract and negative evaluator checks
    python3 scripts/qualification/protocol_connector_qualification.py \
        --stage synthetic --require-stage synthetic \
        --report-dir reports/protocol-connector-qualification

    # Evaluate a redacted operator evidence file (no secrets in the file)
    python3 scripts/qualification/protocol_connector_qualification.py \
        --stage bacnet_live --evidence /secure/bench/bacnet-evidence.json \
        --report-dir reports/protocol-connector-qualification

The command exits zero only when every requested stage is PASS. A complete
qualification still requires all four stages to be PASS; a BLOCKED stage is
never silently treated as a pass.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "openfdd.protocol_connector_qualification.v1"
STAGES = ("synthetic", "image_recipe", "bacnet_live", "haystack_live")
STATUSES = frozenset({"PASS", "FAIL", "BLOCKED", "SKIP"})
MAX_CHECKS = 256
MAX_DETAIL_CHARS = 600
MAX_ARTIFACT_FILES = 128
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60

REQUIRED_CHECKS: dict[str, tuple[str, ...]] = {
    "synthetic": (
        "schema_contract",
        "negative_evaluator",
        "bounded_artifacts",
    ),
    "image_recipe": (
        "immutable_source",
        "image_digests",
        "image_content_isolation",
        "image_runtime_metadata",
        "cloud_zero_ot",
        "edge_selected_connector",
        "compose_runtime",
    ),
    "bacnet_live": (
        "device_reachable",
        "read_only",
        "typed_point_tree",
        "present_value_refresh",
        "priority_array_read",
        "priority_history_visit",
        "restart_recovery",
        "no_write_release",
        "bounded_workload",
    ),
    "haystack_live": (
        "trusted_catalog",
        "authenticated_basic_or_scram",
        "about_read",
        "nav_read",
        "current_read",
        "history_read",
        "typed_timestamps_units",
        "central_receipt_committed",
        "historian_readback",
        "replay_no_duplicate",
        "restart_resume",
        "no_udp_or_bacnet_routes",
    ),
}

# A PASS status is only meaningful when the check carries the proof that its
# name describes. These fields are evidence-contract vocabulary, not product
# defaults. Bench identifiers belong in the operator evidence and are never
# used to select a device in the Rust connector.
REQUIRED_EVIDENCE_FIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("image_recipe", "immutable_source"): ("source_sha",),
    ("image_recipe", "image_digests"): ("image_ids", "digest_kind"),
    ("image_recipe", "image_content_isolation"): ("targets",),
    ("image_recipe", "image_runtime_metadata"): (
        "healthchecks",
        "non_root_runtime_checked",
    ),
    ("image_recipe", "cloud_zero_ot"): ("recipes",),
    ("image_recipe", "edge_selected_connector"): ("recipe",),
    ("image_recipe", "compose_runtime"): ("default_profile", "haystack_profile"),
    ("bacnet_live", "device_reachable"): ("device_instance", "reachable"),
    ("bacnet_live", "read_only"): (
        "operation_mode",
        "write_property_count",
        "release_count",
    ),
    ("bacnet_live", "typed_point_tree"): ("point_count", "typed"),
    ("bacnet_live", "present_value_refresh"): ("refreshed_points", "typed_values"),
    ("bacnet_live", "priority_array_read"): ("priority_array_reads",),
    ("bacnet_live", "priority_history_visit"): (
        "priority_history_visits",
        "non_overlapping",
    ),
    ("bacnet_live", "restart_recovery"): (
        "restarted",
        "recovered",
        "history_persisted",
    ),
    ("bacnet_live", "no_write_release"): ("write_property_count", "release_count"),
    ("bacnet_live", "bounded_workload"): (
        "request_count",
        "duration_seconds",
        "max_duration_seconds",
        "max_request_count",
    ),
    ("haystack_live", "trusted_catalog"): (
        "catalog_fingerprint",
        "trusted_source",
        "catalog_records",
    ),
    ("haystack_live", "authenticated_basic_or_scram"): (
        "auth_mode",
        "auth_ok",
        "credentials_source",
    ),
    ("haystack_live", "about_read"): ("request_count", "status_code", "read_ok"),
    ("haystack_live", "nav_read"): ("request_count", "status_code", "read_ok"),
    ("haystack_live", "current_read"): ("request_count", "status_code", "read_ok"),
    ("haystack_live", "history_read"): (
        "request_count",
        "status_code",
        "read_ok",
        "sample_count",
    ),
    ("haystack_live", "typed_timestamps_units"): (
        "typed_timestamps",
        "units_present",
    ),
    ("haystack_live", "central_receipt_committed"): (
        "receipt",
        "expected_receipt",
    ),
    ("haystack_live", "historian_readback"): (
        "sample_count",
        "expected_sample_count",
        "historian_readback_ok",
    ),
    ("haystack_live", "replay_no_duplicate"): (
        "replay_count",
        "duplicate_rows",
        "conflict_rejected",
    ),
    ("haystack_live", "restart_resume"): (
        "restarted",
        "resumed",
        "pending_recovered",
    ),
    ("haystack_live", "no_udp_or_bacnet_routes"): (
        "udp_socket_count",
        "bacnet_route_count",
    ),
}

SECRET_RE = re.compile(
    r"(?i)(bearer\s+|basic\s+|password\s*[=:]\s*|pass\s*[=:]\s*|"
    r"token\s*[=:]\s*|secret\s*[=:]\s*|jwt\s*[=:]\s*)[^\s,;]+"
)
URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@")
LONG_SECRET_RE = re.compile(r"\b(?:eyJ[a-zA-Z0-9_-]{20,}|[A-Fa-f0-9]{64,})\b")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def sanitize_text(value: Any) -> str:
    """Return bounded operator text with common credential forms redacted."""

    text = str(value).replace("\x00", " ").strip()
    text = URL_CREDENTIAL_RE.sub(r"\1[redacted]@", text)
    text = SECRET_RE.sub(r"\1[redacted]", text)
    text = LONG_SECRET_RE.sub("[redacted]", text)
    if len(text) > MAX_DETAIL_CHARS:
        text = text[: MAX_DETAIL_CHARS - 1] + "…"
    return text


def source_sha(root: Path) -> str:
    configured = os.environ.get("GITHUB_SHA", "").strip()
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _status(status: Any) -> str:
    return status if isinstance(status, str) and status in STATUSES else "BLOCKED"


def _required_for(stage: str) -> tuple[str, ...]:
    return REQUIRED_CHECKS.get(stage, ())


def _compare_mapping(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    return all(actual.get(key) == value for key, value in expected.items())


def _evidence_contract_error(stage: str, check_id: str, evidence: dict[str, Any]) -> str | None:
    """Require check-specific proof before accepting a PASS claim."""

    required = REQUIRED_EVIDENCE_FIELDS.get((stage, check_id), ())
    missing = [field for field in required if field not in evidence]
    if missing:
        return f"{check_id}: missing evidence fields: {', '.join(missing)}"

    if stage == "image_recipe":
        if check_id == "immutable_source" and not re.fullmatch(
            r"[0-9a-fA-F]{7,64}", str(evidence.get("source_sha", ""))
        ):
            return f"{check_id}: invalid source SHA"
        if check_id == "image_digests":
            image_ids = evidence.get("image_ids")
            if not isinstance(image_ids, list) or not image_ids:
                return f"{check_id}: no image IDs/digests recorded"
            if not isinstance(evidence.get("digest_kind"), str) or not evidence.get(
                "digest_kind"
            ):
                return f"{check_id}: digest kind is missing"
        if check_id == "image_content_isolation" and not isinstance(
            evidence.get("targets"), list
        ):
            return f"{check_id}: image target list is malformed"
        if check_id == "image_runtime_metadata" and (
            evidence.get("healthchecks") is not True
            or evidence.get("non_root_runtime_checked") is not True
        ):
            return f"{check_id}: runtime metadata proof is incomplete"
        if check_id == "cloud_zero_ot" and not isinstance(evidence.get("recipes"), list):
            return f"{check_id}: cloud recipe list is malformed"
        if check_id == "edge_selected_connector" and not str(evidence.get("recipe", "")):
            return f"{check_id}: selected edge recipe is missing"
        if check_id == "compose_runtime" and (
            evidence.get("default_profile") is not True
            or evidence.get("haystack_profile") is not True
        ):
            return f"{check_id}: Compose profile evidence is incomplete"

    if stage == "bacnet_live":
        if check_id == "device_reachable" and (
            evidence.get("device_instance") != 5007 or evidence.get("reachable") is not True
        ):
            return f"{check_id}: configured read-only device 5007 was not proven reachable"
        if check_id == "read_only" and (
            evidence.get("operation_mode") != "read_only"
            or evidence.get("write_property_count") != 0
            or evidence.get("release_count") != 0
        ):
            return f"{check_id}: read-only mode or zero-write counters not proven"
        if check_id == "typed_point_tree" and (
            not isinstance(evidence.get("point_count"), (int, float))
            or evidence.get("point_count") <= 0
            or evidence.get("typed") is not True
        ):
            return f"{check_id}: typed point tree is missing"
        if check_id == "present_value_refresh" and (
            not isinstance(evidence.get("refreshed_points"), (int, float))
            or evidence.get("refreshed_points") <= 0
            or evidence.get("typed_values") is not True
        ):
            return f"{check_id}: typed present-value refresh is missing"
        if check_id == "priority_array_read" and (
            not isinstance(evidence.get("priority_array_reads"), (int, float))
            or evidence.get("priority_array_reads") <= 0
        ):
            return f"{check_id}: priority-array read is missing"
        if check_id == "priority_history_visit" and (
            not isinstance(evidence.get("priority_history_visits"), (int, float))
            or evidence.get("priority_history_visits") <= 0
            or evidence.get("non_overlapping") is not True
        ):
            return f"{check_id}: bounded non-overlapping priority visit is missing"
        if check_id == "restart_recovery" and any(
            evidence.get(field) is not True
            for field in ("restarted", "recovered", "history_persisted")
        ):
            return f"{check_id}: restart recovery and persisted history are not proven"
        if check_id == "no_write_release" and (
            evidence.get("write_property_count") != 0
            or evidence.get("release_count") != 0
        ):
            return f"{check_id}: write/release counters are not zero"
        if check_id == "bounded_workload" and (
            not isinstance(evidence.get("request_count"), (int, float))
            or evidence.get("request_count") <= 0
            or not isinstance(evidence.get("duration_seconds"), (int, float))
            or evidence.get("duration_seconds") < 0
            or not isinstance(evidence.get("max_duration_seconds"), (int, float))
            or evidence.get("duration_seconds") > evidence.get("max_duration_seconds")
            or not isinstance(evidence.get("max_request_count"), (int, float))
            or evidence.get("request_count") > evidence.get("max_request_count")
        ):
            return f"{check_id}: workload is unbounded or has no positive request count"

    if stage == "haystack_live":
        if check_id == "trusted_catalog" and (
            not str(evidence.get("catalog_fingerprint", ""))
            or evidence.get("trusted_source") is not True
            or not isinstance(evidence.get("catalog_records"), (int, float))
            or evidence.get("catalog_records") <= 0
        ):
            return f"{check_id}: trusted catalog proof is incomplete"
        if check_id == "authenticated_basic_or_scram" and (
            evidence.get("auth_mode") not in {"basic", "scram"}
            or evidence.get("auth_ok") is not True
            or evidence.get("credentials_source") != "secure_local_config"
        ):
            return f"{check_id}: authenticated Basic/SCRAM secure-config proof is incomplete"
        if check_id in {"about_read", "nav_read", "current_read", "history_read"} and (
            not isinstance(evidence.get("request_count"), (int, float))
            or evidence.get("request_count") <= 0
            or evidence.get("status_code") != 200
            or evidence.get("read_ok") is not True
        ):
            return f"{check_id}: bounded successful Haystack read is missing"
        if check_id == "history_read" and (
            not isinstance(evidence.get("sample_count"), (int, float))
            or evidence.get("sample_count") <= 0
        ):
            return f"{check_id}: history samples are missing"
        if check_id == "typed_timestamps_units" and (
            evidence.get("typed_timestamps") is not True
            or evidence.get("units_present") is not True
        ):
            return f"{check_id}: typed timestamps and units are not proven"
        if check_id == "central_receipt_committed":
            receipt = evidence.get("receipt")
            expected = evidence.get("expected_receipt")
            if (
                not isinstance(receipt, dict)
                or not receipt.get("message_id")
                or receipt.get("status") != "committed"
                or not isinstance(expected, dict)
                or not expected.get("message_id")
            ):
                return f"{check_id}: committed receipt is incomplete"
        if check_id == "historian_readback" and (
            not isinstance(evidence.get("sample_count"), (int, float))
            or evidence.get("sample_count") <= 0
            or not isinstance(evidence.get("expected_sample_count"), (int, float))
            or evidence.get("expected_sample_count") <= 0
            or evidence.get("historian_readback_ok") is not True
        ):
            return f"{check_id}: canonical historian readback is incomplete"
        if check_id == "replay_no_duplicate" and (
            not isinstance(evidence.get("replay_count"), (int, float))
            or evidence.get("replay_count") <= 0
            or evidence.get("duplicate_rows") != 0
            or evidence.get("conflict_rejected") is not True
        ):
            return f"{check_id}: replay/no-duplicate proof is incomplete"
        if check_id == "restart_resume" and any(
            evidence.get(field) is not True
            for field in ("restarted", "resumed", "pending_recovered")
        ):
            return f"{check_id}: restart/resume proof is incomplete"
        if check_id == "no_udp_or_bacnet_routes" and (
            evidence.get("udp_socket_count") != 0
            or evidence.get("bacnet_route_count") != 0
        ):
            return f"{check_id}: prohibited Haystack surface is present"
    return None


def _check_consistency(stage: str, check: dict[str, Any]) -> tuple[str, str]:
    """Apply evidence checks that cannot be satisfied by a forged status."""

    check_id = check.get("check_id")
    status = _status(check.get("status"))
    evidence = check.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    if status == "PASS" and not evidence:
        return "BLOCKED", f"{check_id}: PASS has no evidence"

    # Harnesses must report missing prerequisites explicitly. A command or
    # authentication failure is a blocked/failed stage, never an empty PASS.
    if evidence.get("missing_commands") not in (None, [], {}):
        return "BLOCKED", f"{check_id}: required command unavailable"
    if evidence.get("auth_ok") is False or evidence.get("authentication") == "failed":
        return "FAIL", f"{check_id}: authentication failed"
    if evidence.get("process_owner_ok") is False or evidence.get("listener_owner_ok") is False:
        return "FAIL", f"{check_id}: process/listener ownership could not be verified"
    if evidence.get("historian_readback_ok") is False:
        return "FAIL", f"{check_id}: historian readback failed"
    if evidence.get("fresh") is False or evidence.get("stale") is True:
        return "BLOCKED", f"{check_id}: stale evidence was supplied"

    # A live check must prove the negative surface, rather than merely claim it.
    for key in ("prohibited_listeners", "prohibited_routes"):
        if key in evidence and evidence[key] not in ([], {}, None, False):
            return "FAIL", f"{check_id}: prohibited {key} present"
    if "process_ownership" in evidence:
        ownership = evidence["process_ownership"]
        if not isinstance(ownership, dict) or ownership.get("expected") != ownership.get(
            "observed"
        ):
            return "FAIL", f"{check_id}: process ownership mismatch"

    # Receipt and historian readback claims must correlate to their expected
    # values. This keeps a HTTP 200 or a forged committed flag from qualifying.
    if "receipt" in evidence or "expected_receipt" in evidence:
        if not _compare_mapping(evidence.get("receipt"), evidence.get("expected_receipt")):
            return "FAIL", f"{check_id}: receipt correlation mismatch"
    if "historian" in evidence or "expected_historian" in evidence:
        if not _compare_mapping(evidence.get("historian"), evidence.get("expected_historian")):
            return "FAIL", f"{check_id}: historian readback mismatch"
    if "sample_count" in evidence and "expected_sample_count" in evidence:
        if evidence.get("sample_count") != evidence.get("expected_sample_count"):
            return "FAIL", f"{check_id}: sample count mismatch"

    # A live record must include a recent, timezone-aware observation timestamp.
    if stage in {"bacnet_live", "haystack_live"} and status == "PASS":
        observed = evidence.get("observed_at") or evidence.get("evidence_at")
        if parse_time(observed) is None:
            return "BLOCKED", f"{check_id}: missing timezone-aware evidence timestamp"
        max_age = evidence.get("max_age_seconds", DEFAULT_MAX_AGE_SECONDS)
        if not isinstance(max_age, (int, float)) or max_age <= 0:
            return "BLOCKED", f"{check_id}: invalid evidence age bound"
        age = (dt.datetime.now(dt.timezone.utc) - parse_time(observed)).total_seconds()  # type: ignore[arg-type]
        if age > max_age:
            return "BLOCKED", f"{check_id}: evidence is stale ({int(age)}s)"
        if age < -300:
            return "BLOCKED", f"{check_id}: evidence timestamp is in the future"

    # The live BACnet contract is explicitly read-only. A successful record
    # must carry the operator's no-write assertion, not infer it from a route.
    if stage == "bacnet_live" and check_id == "no_write_release" and status == "PASS":
        if evidence.get("write_property_count") != 0 or evidence.get("release_count") != 0:
            return "FAIL", f"{check_id}: write/release traffic observed"

    # The Haystack process must not qualify if it opened a BACnet UDP socket or
    # exposed a BACnet/Modbus route.
    if stage == "haystack_live" and check_id == "no_udp_or_bacnet_routes" and status == "PASS":
        if evidence.get("udp_socket_count") != 0 or evidence.get("bacnet_route_count") != 0:
            return "FAIL", f"{check_id}: prohibited Haystack process surface observed"
    if stage == "haystack_live" and status == "PASS":
        if check_id in {"about_read", "nav_read", "current_read", "history_read"} and (
            evidence.get("read_ok") is False or evidence.get("status_code") not in (None, 200)
        ):
            return "FAIL", f"{check_id}: upstream read failed"
        if check_id == "replay_no_duplicate" and (
            evidence.get("duplicate_rows") not in (None, 0)
            or evidence.get("conflict_rejected") is False
        ):
            return "FAIL", f"{check_id}: duplicate or changed-parameter replay was accepted"

    # Apply the field-level evidence contract after explicit negative
    # assertions above. A measured violation remains FAIL; merely missing
    # proof is BLOCKED.
    if status == "PASS":
        contract_error = _evidence_contract_error(stage, str(check_id), evidence)
        if contract_error:
            return "BLOCKED", contract_error

    return status, sanitize_text(check.get("detail", "evidence accepted"))


def validate_stage(stage: str, value: Any) -> dict[str, Any]:
    """Validate one stage and recompute its status from bounded evidence."""

    if stage not in STAGES:
        return {
            "stage": stage,
            "status": "BLOCKED",
            "checks": [],
            "failure": "unknown stage",
        }
    if not isinstance(value, dict):
        return {
            "stage": stage,
            "status": "BLOCKED",
            "checks": [],
            "failure": "stage evidence is not an object",
        }
    raw_checks = value.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        return {
            "stage": stage,
            "status": "BLOCKED",
            "checks": [],
            "failure": "empty checks",
        }
    if len(raw_checks) > MAX_CHECKS:
        return {
            "stage": stage,
            "status": "BLOCKED",
            "checks": [],
            "failure": "check count exceeds bound",
        }

    required = set(_required_for(stage))
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    failures: list[str] = []
    for raw in raw_checks:
        if not isinstance(raw, dict) or not isinstance(raw.get("check_id"), str):
            failures.append("malformed check")
            continue
        check_id = raw["check_id"]
        if check_id in seen:
            failures.append(f"duplicate check {check_id}")
            continue
        seen.add(check_id)
        if check_id not in required:
            failures.append(f"unexpected check {check_id}")
        status, detail = _check_consistency(stage, raw)
        normalized.append(
            {
                "check_id": check_id,
                "status": status,
                "detail": sanitize_text(detail),
            }
        )
        if status != "PASS":
            failures.append(f"{check_id}: {status}")

    missing = sorted(required - seen)
    if missing:
        failures.append("missing checks: " + ", ".join(missing))

    observed_at = value.get("observed_at") or value.get("evidence_at")
    if stage in {"bacnet_live", "haystack_live"} and parse_time(observed_at) is None:
        failures.append("missing stage evidence timestamp")
    # If any stage supplies an evidence timestamp, enforce its freshness. This
    # also keeps a stale synthetic artifact from being reused as a live claim.
    if observed_at is not None:
        parsed_observed = parse_time(observed_at)
        if parsed_observed is None:
            failures.append("invalid stage evidence timestamp")
        else:
            max_age = value.get("max_age_seconds", DEFAULT_MAX_AGE_SECONDS)
            if not isinstance(max_age, (int, float)) or max_age <= 0:
                failures.append("invalid stage age bound")
            else:
                age = (dt.datetime.now(dt.timezone.utc) - parsed_observed).total_seconds()
                if age > max_age:
                    failures.append("stage evidence is stale")
                if age < -300:
                    failures.append("stage evidence timestamp is in the future")

    # Recompute status. A caller-supplied PASS or fully_qualified field never
    # overrides a missing, blocked, contradictory, or stale check.
    if failures:
        status = "FAIL" if any(": FAIL" in f or "mismatch" in f or "prohibited" in f for f in failures) else "BLOCKED"
    else:
        status = "PASS"
    return {
        "stage": stage,
        "status": status,
        "checks": normalized,
        "check_count": len(normalized),
        "failure": "; ".join(sanitize_text(item) for item in failures) if failures else None,
        "observed_at": sanitize_text(observed_at) if observed_at else None,
    }


def evaluate_report(report: Any, required_stages: Iterable[str] = STAGES) -> tuple[bool, str]:
    """Return whether the requested stages are genuinely qualified.

    This function intentionally ignores caller-supplied ``overall_status`` and
    ``fully_qualified`` fields and recomputes the verdict from normalized
    stages. It is the API used by the negative evaluator tests.
    """

    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA_VERSION:
        return False, "schema mismatch"
    stages = report.get("stages")
    if not isinstance(stages, dict):
        return False, "missing stages"
    wanted = tuple(required_stages)
    if not wanted or any(stage not in STAGES for stage in wanted):
        return False, "invalid required stage set"
    for stage in wanted:
        value = stages.get(stage)
        if not isinstance(value, dict) or value.get("status") != "PASS":
            return False, f"stage {stage} is not PASS"
        checks = value.get("checks")
        required = set(_required_for(stage))
        if not isinstance(checks, list):
            return False, f"stage {stage} has no checks"
        by_id = {c.get("check_id"): c for c in checks if isinstance(c, dict)}
        if set(by_id) != required or any(c.get("status") != "PASS" for c in checks):
            return False, f"stage {stage} has incomplete or non-PASS checks"
    return True, "requested stages PASS"


def _check(check_id: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "PASS",
        "detail": detail,
        "evidence": evidence or {"source": "offline synthetic contract"},
    }


def synthetic_stage() -> dict[str, Any]:
    """Create a bounded synthetic stage with no network or credential access."""

    checks = [
        _check("schema_contract", "required stage/check vocabulary is present", {"schema": SCHEMA_VERSION}),
        _check(
            "negative_evaluator",
            "missing, stale, contradictory, partial, and empty evidence are rejected",
            {"cases": ["missing", "stale", "contradictory", "partial", "empty"]},
        ),
        _check(
            "bounded_artifacts",
            "report output is bounded and credential redaction is enabled",
            {"max_checks": MAX_CHECKS, "max_detail_chars": MAX_DETAIL_CHARS},
        ),
    ]
    return {"checks": checks, "observed_at": utc_now(), "max_age_seconds": DEFAULT_MAX_AGE_SECONDS}


def blocked_stage(stage: str, reason: str) -> dict[str, Any]:
    checks = [
        {
            "check_id": check_id,
            "status": "BLOCKED",
            "detail": sanitize_text(reason),
            "evidence": {"source": "no live evidence supplied"},
        }
        for check_id in _required_for(stage)
    ]
    return {"checks": checks, "evidence_at": None}


def load_stage_evidence(stage: str, path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return blocked_stage(stage, f"cannot load evidence: {exc.__class__.__name__}")
    if isinstance(raw, dict) and raw.get("stage") not in (None, stage):
        return blocked_stage(stage, "evidence stage does not match requested stage")
    if isinstance(raw, dict) and isinstance(raw.get("evidence"), dict):
        raw = raw["evidence"]
    return raw if isinstance(raw, dict) else blocked_stage(stage, "evidence is not an object")


def build_report(root: Path, stage: str, evidence: Path | None) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}
    for name in STAGES:
        if name == "synthetic" and stage in {"synthetic", "all"}:
            raw = synthetic_stage()
        elif name == stage and evidence is not None:
            raw = load_stage_evidence(name, evidence)
        elif stage == "all":
            raw = blocked_stage(name, "no evidence supplied; live/image stage must be run explicitly")
        else:
            raw = blocked_stage(name, "stage not requested")
        stages[name] = validate_stage(name, raw)

    overall = "PASS"
    if any(result["status"] == "FAIL" for result in stages.values()):
        overall = "FAIL"
    elif any(result["status"] != "PASS" for result in stages.values()):
        overall = "BLOCKED"
    fully_qualified, _ = evaluate_report(
        {"schema_version": SCHEMA_VERSION, "stages": stages}, STAGES
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source_sha": source_sha(root),
        "profile": stage,
        "stages": stages,
        "overall_status": overall,
        "fully_qualified": fully_qualified,
        "limits": {
            "max_checks": MAX_CHECKS,
            "max_detail_chars": MAX_DETAIL_CHARS,
            "max_artifact_files": MAX_ARTIFACT_FILES,
            "max_artifact_bytes": MAX_ARTIFACT_BYTES,
        },
    }


def render_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Protocol connector qualification",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Source SHA: `{sanitize_text(report.get('source_sha', 'unknown'))}`",
        f"- Generated: `{report.get('generated_at', 'unknown')}`",
        f"- Overall: **{report.get('overall_status', 'BLOCKED')}**",
        f"- Fully qualified: **{bool(report.get('fully_qualified'))}**",
        "",
        "A BLOCKED or SKIP stage is not a pass. Live stages require redacted operator evidence.",
        "",
        "| Stage | Status | Checks | Failure |",
        "|---|---:|---:|---|",
    ]
    for stage in STAGES:
        value = report["stages"].get(stage, {})
        lines.append(
            f"| `{stage}` | **{value.get('status', 'BLOCKED')}** | "
            f"{value.get('check_count', 0)} | {sanitize_text(value.get('failure') or '—')} |"
        )
    lines.extend(
        [
            "",
            "No credentials, tokens, cookies, raw response bodies, or private endpoint details are copied into this summary.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_artifacts(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("qualification report exceeds artifact size bound")
    (report_dir / "protocol_connector_qualification.json").write_text(payload, encoding="utf-8")
    (report_dir / "SUMMARY.md").write_text(render_summary(report), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=(*STAGES, "all"), default="synthetic")
    parser.add_argument("--evidence", type=Path, help="redacted JSON evidence for the requested non-synthetic stage")
    parser.add_argument("--report-dir", type=Path, default=Path("reports/protocol-connector-qualification"))
    parser.add_argument(
        "--require-stage",
        action="append",
        dest="required_stages",
        help="stage that must be PASS for exit 0; repeat for a bounded subset",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--selftest", action="store_true", help="run evaluator negatives without writing artifacts")
    return parser.parse_args(argv)


def _selftest_report(stage: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stages": {stage: validate_stage(stage, raw)},
    }


def run_selftest() -> int:
    now = utc_now()
    good = synthetic_stage()
    cases: list[tuple[str, bool]] = []
    cases.append(("empty", not evaluate_report(_selftest_report("synthetic", {}), ("synthetic",))[0]))
    partial = {"checks": good["checks"][:1], "observed_at": now}
    cases.append(("partial", not evaluate_report(_selftest_report("synthetic", partial), ("synthetic",))[0]))
    stale = dict(good)
    stale["observed_at"] = "2020-01-01T00:00:00Z"
    cases.append(("stale", not evaluate_report(_selftest_report("synthetic", stale), ("synthetic",))[0]))
    contradictory = dict(good)
    contradictory["checks"] = [dict(item) for item in good["checks"]]
    contradictory["checks"][0]["status"] = "FAIL"
    cases.append(("contradictory", not evaluate_report(_selftest_report("synthetic", contradictory), ("synthetic",))[0]))
    forged = {"schema_version": SCHEMA_VERSION, "fully_qualified": True, "overall_status": "PASS", "stages": {}}
    cases.append(("forged-top-level", not evaluate_report(forged, ("synthetic",))[0]))
    # Receipt mismatch, stale data, and prohibited-surface claims are tested on
    # a minimal live record to ensure the status cannot be forged independently.
    live = {
        "checks": [
            {
                "check_id": check_id,
                "status": "PASS",
                "detail": "test",
                "evidence": {"observed_at": now},
            }
            for check_id in REQUIRED_CHECKS["haystack_live"]
        ],
        "observed_at": now,
    }
    by_id = {item["check_id"]: item for item in live["checks"]}
    by_id["central_receipt_committed"]["evidence"] = {
        "observed_at": now,
        "receipt": {"message_id": "a"},
        "expected_receipt": {"message_id": "b"},
    }
    cases.append(("receipt-mismatch", not evaluate_report(_selftest_report("haystack_live", live), ("haystack_live",))[0]))
    by_id["central_receipt_committed"]["evidence"] = {"observed_at": now}
    by_id["no_udp_or_bacnet_routes"]["evidence"] = {"observed_at": now, "udp_socket_count": 1, "bacnet_route_count": 0}
    cases.append(("prohibited-surface", not evaluate_report(_selftest_report("haystack_live", live), ("haystack_live",))[0]))
    failed = [name for name, passed in cases if not passed]
    print(json.dumps({"ok": not failed, "cases": dict(cases), "failed": failed}, indent=2))
    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.selftest:
        return run_selftest()
    if args.evidence is not None and args.stage in {"synthetic", "all"}:
        print("FAIL: --evidence must target one non-synthetic stage", file=sys.stderr)
        return 2
    report = build_report(args.root.resolve(), args.stage, args.evidence)
    try:
        write_artifacts(report, args.report_dir)
    except (OSError, ValueError) as exc:
        print(f"FAIL: cannot write bounded qualification artifacts: {exc}", file=sys.stderr)
        return 2
    required = tuple(args.required_stages or (("synthetic",) if args.stage == "synthetic" else STAGES if args.stage == "all" else (args.stage,)))
    accepted, reason = evaluate_report(report, required)
    print(f"qualification={report['overall_status']} fully_qualified={report['fully_qualified']} reason={sanitize_text(reason)}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
