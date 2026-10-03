"""Deployment profile and exposure evidence contract.

The execution profiles in :mod:`openfdd_security.profiles` describe which
security suites may run.  This module describes the candidate topology those
suites qualify.  Keeping the two axes separate is deliberate: a Railway
topology does not grant permission to run an active scan.

The validator is intentionally stdlib-only and fail-closed.  It consumes a
redacted, machine-readable observation produced by a deployment/bootstrap
gate; it never starts containers, opens sockets, or reads credentials.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from . import STATUSES


ROOT = Path(__file__).resolve().parents[1]
PROFILE_REGISTRY_PATH = ROOT / "schemas" / "deployment_profiles_v1.json"
PROFILE_SCHEMA_VERSION = "openfdd_deployment_profiles_v1"
EVIDENCE_SCHEMA_VERSION = "openfdd_deployment_exposure_evidence_v1"

PROFILE_ALLOWED_KEYS = frozenset(
    {
        "profile_version",
        "deployment",
        "selected_capabilities",
        "selected_connector",
        "required_services",
        "optional_services",
        "forbidden_services",
        "required_images",
        "required_execution_suites",
        "required_checks",
        "origin",
        "certificate",
        "test_mode",
        "budgets",
        "prohibited_side_effects",
        "listeners",
        "evidence_max_age_seconds",
        "source_recipes",
        "notes",
    }
)

EVIDENCE_ALLOWED_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "profile_id",
        "profile_version",
        "source_sha",
        "started_at",
        "ended_at",
        "execution_mode",
        "candidate",
        "binding",
        "origin",
        "services",
        "listeners",
        "checks",
        "counts",
        "budget",
        "cleanup",
        "artifacts",
        "notes",
    }
)

CANDIDATE_ALLOWED_KEYS = frozenset(
    {"candidate_id", "source_sha", "config_sha256", "fixture_sha256", "images"}
)
BINDING_ALLOWED_KEYS = frozenset(
    {
        "candidate_source_sha_start",
        "candidate_source_sha_end",
        "config_sha256_start",
        "config_sha256_end",
        "fixture_sha256_start",
        "fixture_sha256_end",
    }
)
IMAGE_ALLOWED_KEYS = frozenset({"name", "digest", "platform"})
SERVICE_ALLOWED_KEYS = frozenset({"name", "status", "image", "digest", "detail"})
LISTENER_EVIDENCE_ALLOWED_KEYS = frozenset(
    {
        "service",
        "network_namespace",
        "host_ipv4",
        "host_ipv6",
        "port",
        "protocol",
        "authenticated_transport",
        "source_network_aliases",
        "egress_aliases",
        "observed",
        "denied_paths",
    }
)
CHECK_ALLOWED_KEYS = frozenset({"check_id", "status", "detail", "evidence"})
COUNT_KEYS = frozenset(
    {"planned", "pass", "fail", "error", "blocked", "skipped", "not_applicable"}
)
BUDGET_KEYS = frozenset(
    {
        "max_requests",
        "request_count",
        "timeout_s",
        "deadline_s",
        "cleanup_reserved",
        "cleanup_requests",
        "max_body_bytes",
    }
)
ORIGIN_KEYS = frozenset({"canonical", "allowlist", "resolved_exposure"})
CLEANUP_KEYS = frozenset({"status", "requests", "detail"})
ARTIFACT_KEYS = frozenset({"path", "sha256"})

SERVICE_STATUSES = frozenset({"PRESENT", "ABSENT"})
EXECUTION_MODES = frozenset({"offline", "local_isolated", "railway_readonly"})
MAX_REQUESTS = 200
MAX_TIMEOUT_SECONDS = 10.0
MAX_DEADLINE_SECONDS = 300.0
MAX_BODY_BYTES = 1 * 1024 * 1024
MAX_ARTIFACTS = 128
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


def _unknown(data: Any, allowed: Iterable[str], label: str) -> list[str]:
    if not isinstance(data, dict):
        return [f"{label} must be an object"]
    return [f"{label} has unknown field(s): {', '.join(sorted(set(data) - set(allowed)))}"] if set(data) - set(allowed) else []


def _is_string_list(value: Any, *, nonempty: bool = False) -> bool:
    return isinstance(value, list) and (not nonempty or bool(value)) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _is_sha(value: Any, *, git: bool = False) -> bool:
    pattern = r"[0-9a-fA-F]{7,64}" if git else r"[0-9a-fA-F]{64}"
    return isinstance(value, str) and bool(re.fullmatch(pattern, value))


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"sha256:[0-9a-fA-F]{64}", value))


def _parse_time(value: Any) -> dt.datetime | None:
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


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _origin_is_safe(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
    )


def load_profile_registry(path: Path | None = None) -> dict[str, Any]:
    """Load the checked-in deployment profile registry.

    Invalid registry content is an authoring error and raises ``ValueError``;
    an evidence evaluator never silently falls back to a different topology.
    """

    registry_path = path or PROFILE_REGISTRY_PATH
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load deployment profile registry: {exc}") from exc
    errors = validate_profile_registry(data)
    if errors:
        raise ValueError("invalid deployment profile registry: " + "; ".join(errors))
    return data


def validate_profile_registry(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["registry root must be an object"]
    if data.get("schema_version") != PROFILE_SCHEMA_VERSION:
        errors.append("bad deployment profile schema_version")
    if set(data) - {"schema_version", "profiles", "notes"}:
        errors.append("registry has unknown top-level fields")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return errors + ["registry profiles must be a nonempty object"]
    for profile_id, profile in profiles.items():
        errors.extend(validate_deployment_profile(profile_id, profile))
    return errors


def profile_map(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    return (registry or load_profile_registry()).get("profiles", {})


def validate_deployment_profile(profile_id: str, profile: Any) -> list[str]:
    """Validate one policy profile, including cloud/OT topology invariants."""

    errors: list[str] = []
    if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]+", profile_id):
        errors.append(f"invalid profile id {profile_id!r}")
    errors.extend(_unknown(profile, PROFILE_ALLOWED_KEYS, f"profile {profile_id}"))
    if not isinstance(profile, dict):
        return errors

    if not isinstance(profile.get("profile_version"), int) or profile["profile_version"] < 1:
        errors.append(f"{profile_id}: profile_version must be a positive integer")
    for field in (
        "deployment",
        "selected_connector",
        "test_mode",
    ):
        if not isinstance(profile.get(field), str) or not profile[field].strip():
            errors.append(f"{profile_id}: {field} is required")
    for field in (
        "selected_capabilities",
        "required_services",
        "optional_services",
        "forbidden_services",
        "required_images",
        "required_execution_suites",
        "required_checks",
        "prohibited_side_effects",
        "source_recipes",
    ):
        if not _is_string_list(profile.get(field), nonempty=field not in {"optional_services"}):
            errors.append(f"{profile_id}: {field} must be a list of strings")

    required_services = set(profile.get("required_services") or [])
    optional_services = set(profile.get("optional_services") or [])
    forbidden_services = set(profile.get("forbidden_services") or [])
    if required_services & forbidden_services:
        errors.append(f"{profile_id}: service is both required and forbidden")
    if required_services & optional_services:
        errors.append(f"{profile_id}: service is both required and optional")
    if not profile.get("required_checks"):
        errors.append(f"{profile_id}: required_checks cannot be empty")
    if len(profile.get("required_checks") or []) != len(set(profile.get("required_checks") or [])):
        errors.append(f"{profile_id}: duplicate required_checks")
    suites = set(profile.get("required_execution_suites") or [])
    if not suites <= {"X", "Y", "Z", "mqtt_acl"}:
        errors.append(f"{profile_id}: unknown execution suite")
    if len(suites) != len(profile.get("required_execution_suites") or []):
        errors.append(f"{profile_id}: duplicate execution suite")

    if profile_id == "cloud_mqtt_hub":
        if required_services != {"openfdd-web", "openfdd-central", "openfdd-mqtt"}:
            errors.append("cloud_mqtt_hub: must require web + central + mqtt exactly")
        if profile.get("selected_connector") != "none":
            errors.append("cloud_mqtt_hub: selected_connector must be none")
        if not {"openfdd-fieldbus", "openfdd-bacnet-modbus", "openfdd-haystack"} <= forbidden_services:
            errors.append("cloud_mqtt_hub: every OT image/service must be forbidden")
        if "mqtt_acl" not in suites:
            errors.append("cloud_mqtt_hub: mqtt_acl suite is required")
    elif profile_id in {"ot_local_bacnet_modbus", "ot_local_haystack"}:
        connector = "openfdd-bacnet-modbus" if profile_id.endswith("bacnet_modbus") else "openfdd-haystack"
        selected = "bacnet_modbus" if profile_id.endswith("bacnet_modbus") else "haystack"
        if required_services != {"caddy", "openfdd-web", "openfdd-central", connector}:
            errors.append(f"{profile_id}: must require Caddy + web + central + selected connector exactly")
        if profile.get("selected_connector") != selected:
            errors.append(f"{profile_id}: selected_connector does not match profile")
        other = "openfdd-haystack" if connector == "openfdd-bacnet-modbus" else "openfdd-bacnet-modbus"
        if other not in forbidden_services or "openfdd-mqtt" not in forbidden_services:
            errors.append(f"{profile_id}: unselected OT connector and broker must be forbidden")
        if "mqtt_acl" in suites:
            errors.append(f"{profile_id}: MQTT ACL cannot be mandatory for local OT")

    required_images = set(profile.get("required_images") or [])
    if required_services - required_images:
        errors.append(f"{profile_id}: required service image coverage is incomplete")
    listeners = profile.get("listeners")
    if not isinstance(listeners, list) or not listeners:
        errors.append(f"{profile_id}: listeners must be a nonempty list")
    else:
        seen_listener: set[tuple[str, str, int, str]] = set()
        required_listener_services = set(required_services)
        for index, listener in enumerate(listeners):
            errors.extend(_validate_profile_listener(profile_id, index, listener))
            if isinstance(listener, dict):
                key = (
                    str(listener.get("service")),
                    str(listener.get("network_namespace")),
                    int(listener.get("port", -1)) if isinstance(listener.get("port"), int) else -1,
                    str(listener.get("protocol")),
                )
                if key in seen_listener:
                    errors.append(f"{profile_id}: duplicate listener {key}")
                seen_listener.add(key)
                required_listener_services.discard(str(listener.get("service")))
        if required_listener_services:
            errors.append(
                f"{profile_id}: missing listener evidence contract for service(s) "
                + ", ".join(sorted(required_listener_services))
            )

    origin = profile.get("origin")
    if not isinstance(origin, dict):
        errors.append(f"{profile_id}: origin must be an object")
    elif set(origin) - {"required_scheme", "resolved_exposure"}:
        errors.append(f"{profile_id}: origin has unknown fields")
    elif origin.get("required_scheme") not in {"http", "https"}:
        errors.append(f"{profile_id}: origin.required_scheme is invalid")

    certificate = profile.get("certificate")
    if not isinstance(certificate, dict):
        errors.append(f"{profile_id}: certificate must be an object")
    else:
        if set(certificate) - {"modes", "trusted_issuer_policy", "secret_references_only"}:
            errors.append(f"{profile_id}: certificate has unknown fields")
        if not _is_string_list(certificate.get("modes"), nonempty=True):
            errors.append(f"{profile_id}: certificate modes must be nonempty")
        if certificate.get("secret_references_only") is not True:
            errors.append(f"{profile_id}: certificate secrets must be references only")

    budgets = profile.get("budgets")
    errors.extend(_validate_policy_budgets(profile_id, budgets))
    max_age = profile.get("evidence_max_age_seconds")
    if not _finite_number(max_age) or max_age <= 0:
        errors.append(f"{profile_id}: evidence_max_age_seconds must be positive finite")
    return errors


def _validate_profile_listener(profile_id: str, index: int, listener: Any) -> list[str]:
    errors: list[str] = []
    label = f"{profile_id}.listeners[{index}]"
    allowed = {
        "service",
        "network_namespace",
        "host_ipv4",
        "host_ipv6",
        "port",
        "protocol",
        "authenticated_transport",
        "source_network_aliases",
        "egress_aliases",
        "expected_denied_paths",
    }
    errors.extend(_unknown(listener, allowed, label))
    if not isinstance(listener, dict):
        return errors
    for field in ("service", "network_namespace", "host_ipv4", "host_ipv6", "protocol", "authenticated_transport"):
        if not isinstance(listener.get(field), str) or not listener[field].strip():
            errors.append(f"{label}: {field} is required")
    if not isinstance(listener.get("port"), int) or not 1 <= listener["port"] <= 65535:
        errors.append(f"{label}: port must be 1..65535")
    for field in ("source_network_aliases", "egress_aliases", "expected_denied_paths"):
        if not _is_string_list(listener.get(field)):
            errors.append(f"{label}: {field} must be a list of strings")
    return errors


def _validate_policy_budgets(profile_id: str, budgets: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(budgets, dict):
        return [f"{profile_id}: budgets must be an object"]
    errors.extend(_unknown(budgets, {"max_requests", "timeout_s", "deadline_s", "cleanup_reserved", "max_body_bytes"}, f"{profile_id}.budgets"))
    for field in ("max_requests", "timeout_s", "deadline_s", "cleanup_reserved", "max_body_bytes"):
        if not _finite_number(budgets.get(field)) or budgets[field] <= 0:
            errors.append(f"{profile_id}: budget {field} must be positive finite")
    if _finite_number(budgets.get("max_requests")) and budgets["max_requests"] > MAX_REQUESTS:
        errors.append(f"{profile_id}: max_requests exceeds hard maximum")
    if _finite_number(budgets.get("timeout_s")) and budgets["timeout_s"] > MAX_TIMEOUT_SECONDS:
        errors.append(f"{profile_id}: timeout_s exceeds hard maximum")
    if _finite_number(budgets.get("deadline_s")) and budgets["deadline_s"] > MAX_DEADLINE_SECONDS:
        errors.append(f"{profile_id}: deadline_s exceeds hard maximum")
    if _finite_number(budgets.get("max_body_bytes")) and budgets["max_body_bytes"] > MAX_BODY_BYTES:
        errors.append(f"{profile_id}: max_body_bytes exceeds hard maximum")
    return errors


def validate_deployment_evidence(
    evidence: Any,
    *,
    expected_profile: str | None = None,
    registry: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
    artifact_root: Path | None = None,
) -> list[str]:
    """Return all evidence contract violations.

    The function only accepts sanitized evidence.  It deliberately requires
    both required and forbidden service observations so a missing OT service
    cannot be mistaken for proof that cloud is OT-free.
    """

    errors: list[str] = []
    if not isinstance(evidence, dict):
        return ["evidence root must be an object"]
    errors.extend(_unknown(evidence, EVIDENCE_ALLOWED_KEYS, "evidence"))
    required_root = {
        "schema_version",
        "run_id",
        "profile_id",
        "profile_version",
        "source_sha",
        "started_at",
        "ended_at",
        "execution_mode",
        "candidate",
        "binding",
        "origin",
        "services",
        "listeners",
        "checks",
        "counts",
        "budget",
        "cleanup",
    }
    errors.extend(f"evidence missing field: {field}" for field in sorted(required_root - set(evidence)))
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        errors.append("bad evidence schema_version")
    profile_id = evidence.get("profile_id")
    if expected_profile is not None and profile_id != expected_profile:
        errors.append("evidence profile mismatch")
    registry = registry or load_profile_registry()
    profiles = profile_map(registry)
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict):
        errors.append(f"unknown deployment profile {profile_id!r}")
        return errors
    errors.extend(validate_deployment_profile(str(profile_id), profile))
    if evidence.get("profile_version") != profile.get("profile_version"):
        errors.append("evidence profile_version mismatch")
    if not isinstance(evidence.get("run_id"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{8,80}", evidence.get("run_id", "")):
        errors.append("run_id is missing or malformed")
    if not _is_sha(evidence.get("source_sha"), git=True):
        errors.append("source_sha must be a git SHA")
    mode = evidence.get("execution_mode")
    if mode not in EXECUTION_MODES:
        errors.append(f"invalid execution_mode {mode!r}")

    now = now or dt.datetime.now(dt.timezone.utc)
    started = _parse_time(evidence.get("started_at"))
    ended = _parse_time(evidence.get("ended_at"))
    if started is None or ended is None:
        errors.append("started_at and ended_at must be timezone-aware timestamps")
    elif ended < started:
        errors.append("ended_at precedes started_at")
    elif ended > now + dt.timedelta(seconds=300):
        errors.append("ended_at is in the future")
    elif now - ended > dt.timedelta(seconds=float(profile.get("evidence_max_age_seconds", 0))):
        errors.append("evidence is stale")

    candidate = evidence.get("candidate")
    errors.extend(_unknown(candidate, CANDIDATE_ALLOWED_KEYS, "candidate"))
    if not isinstance(candidate, dict):
        candidate = {}
    if not _is_sha(candidate.get("source_sha"), git=True):
        errors.append("candidate.source_sha must be a git SHA")
    for key in ("config_sha256", "fixture_sha256"):
        if not _is_sha(candidate.get(key)):
            errors.append(f"candidate.{key} must be a SHA-256")
    errors.extend(_validate_images(candidate.get("images"), profile))
    errors.extend(_validate_binding(evidence.get("binding"), candidate))

    errors.extend(_validate_origin(evidence.get("origin"), profile))
    errors.extend(_validate_services(evidence.get("services"), profile, candidate))
    errors.extend(_validate_listeners(evidence.get("listeners"), profile))
    errors.extend(_validate_checks(evidence.get("checks"), evidence.get("counts"), profile))
    errors.extend(_validate_budget(evidence.get("budget"), profile))
    errors.extend(_validate_cleanup(evidence.get("cleanup")))
    errors.extend(_validate_artifacts(evidence.get("artifacts", []), artifact_root))
    return errors


def _validate_images(images: Any, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(images, list) or not images:
        return ["candidate.images must be a nonempty list"]
    seen: set[str] = set()
    required = set(profile.get("required_images") or [])
    for index, image in enumerate(images):
        errors.extend(_unknown(image, IMAGE_ALLOWED_KEYS, f"candidate.images[{index}]"))
        if not isinstance(image, dict):
            continue
        name = image.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"candidate.images[{index}].name is required")
        elif name in seen:
            errors.append(f"duplicate candidate image {name}")
        else:
            seen.add(name)
        if not _is_digest(image.get("digest")):
            errors.append(f"candidate.images[{index}].digest must be immutable sha256")
        if not isinstance(image.get("platform"), str) or not re.fullmatch(r"linux/[A-Za-z0-9_.-]+", image.get("platform", "")):
            errors.append(f"candidate.images[{index}].platform is malformed")
    if required - seen:
        errors.append("candidate image evidence missing: " + ", ".join(sorted(required - seen)))
    return errors


def _validate_binding(binding: Any, candidate: dict[str, Any]) -> list[str]:
    errors = _unknown(binding, BINDING_ALLOWED_KEYS, "binding")
    if not isinstance(binding, dict):
        return errors + ["binding must be an object"]
    expected = {
        "candidate_source_sha_start": candidate.get("source_sha"),
        "candidate_source_sha_end": candidate.get("source_sha"),
        "config_sha256_start": candidate.get("config_sha256"),
        "config_sha256_end": candidate.get("config_sha256"),
        "fixture_sha256_start": candidate.get("fixture_sha256"),
        "fixture_sha256_end": candidate.get("fixture_sha256"),
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            errors.append(f"binding mismatch: {key}")
    return errors


def _validate_origin(origin: Any, profile: dict[str, Any]) -> list[str]:
    errors = _unknown(origin, ORIGIN_KEYS, "origin")
    if not isinstance(origin, dict):
        return errors + ["origin must be an object"]
    canonical = origin.get("canonical")
    if not _origin_is_safe(canonical):
        errors.append("origin.canonical is not a safe origin")
    allowlist = origin.get("allowlist")
    if not isinstance(allowlist, list) or not allowlist or any(not _origin_is_safe(item) for item in allowlist):
        errors.append("origin.allowlist must contain safe origins")
    elif canonical not in allowlist:
        errors.append("origin.canonical is not in origin.allowlist")
    expected_scheme = (profile.get("origin") or {}).get("required_scheme")
    if isinstance(canonical, str) and not canonical.lower().startswith(expected_scheme + ":"):
        errors.append("origin scheme does not match deployment profile")
    if origin.get("resolved_exposure") != (profile.get("origin") or {}).get("resolved_exposure"):
        errors.append("origin resolved_exposure does not match deployment profile")
    return errors


def _validate_services(services: Any, profile: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(services, list) or not services:
        return ["services must be a nonempty list"]
    expected = set(profile.get("required_services") or []) | set(profile.get("forbidden_services") or [])
    optional = set(profile.get("optional_services") or [])
    seen: set[str] = set()
    image_names = {item.get("name") for item in candidate.get("images", []) if isinstance(item, dict)}
    image_digests = {item.get("name"): item.get("digest") for item in candidate.get("images", []) if isinstance(item, dict)}
    for index, service in enumerate(services):
        errors.extend(_unknown(service, SERVICE_ALLOWED_KEYS, f"services[{index}]"))
        if not isinstance(service, dict):
            continue
        name = service.get("name")
        status = service.get("status")
        if not isinstance(name, str) or not name:
            errors.append(f"services[{index}].name is required")
            continue
        if name in seen:
            errors.append(f"duplicate service evidence {name}")
        seen.add(name)
        if name not in expected and name not in optional:
            errors.append(f"unexpected service evidence {name}")
        if status not in SERVICE_STATUSES:
            errors.append(f"{name}: invalid service status")
        if status == "PRESENT":
            image = service.get("image")
            if image not in image_names:
                errors.append(f"{name}: present service image is not bound to candidate")
            if service.get("digest") != image_digests.get(image):
                errors.append(f"{name}: service digest is not bound to candidate image")
        elif service.get("image") is not None or service.get("digest") is not None:
            errors.append(f"{name}: absent service must not carry image evidence")
    missing = expected - seen
    if missing:
        errors.append("missing service evidence: " + ", ".join(sorted(missing)))
    for name in profile.get("required_services") or []:
        row = next((item for item in services if isinstance(item, dict) and item.get("name") == name), None)
        if not row or row.get("status") != "PRESENT":
            errors.append(f"required service {name} is not PRESENT")
    for name in profile.get("forbidden_services") or []:
        row = next((item for item in services if isinstance(item, dict) and item.get("name") == name), None)
        if not row or row.get("status") != "ABSENT":
            errors.append(f"forbidden service {name} is not proven ABSENT")
    return errors


def _validate_listeners(listeners: Any, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(listeners, list):
        return ["listeners must be a list"]
    expected = profile.get("listeners") or []
    if len(listeners) != len(expected):
        errors.append("listener evidence count does not match profile")
    seen: set[tuple[str, int, str]] = set()
    for index, listener in enumerate(listeners):
        errors.extend(_unknown(listener, LISTENER_EVIDENCE_ALLOWED_KEYS, f"listeners[{index}]"))
        if not isinstance(listener, dict):
            continue
        key = (str(listener.get("service")), int(listener.get("port", -1)) if isinstance(listener.get("port"), int) else -1, str(listener.get("protocol")))
        if key in seen:
            errors.append(f"duplicate listener evidence {key}")
        seen.add(key)
        match = next(
            (
                item
                for item in expected
                if isinstance(item, dict)
                and item.get("service") == listener.get("service")
                and item.get("port") == listener.get("port")
                and item.get("protocol") == listener.get("protocol")
            ),
            None,
        )
        if match is None:
            errors.append(f"unexpected listener evidence {key}")
            continue
        for field in (
            "network_namespace",
            "host_ipv4",
            "host_ipv6",
            "authenticated_transport",
            "source_network_aliases",
            "egress_aliases",
        ):
            if listener.get(field) != match.get(field):
                errors.append(f"listener {key}: {field} mismatch")
        if listener.get("observed") is not True:
            errors.append(f"listener {key}: observed must be true")
        denied = set(listener.get("denied_paths") or [])
        required_denied = set(match.get("expected_denied_paths") or [])
        if not required_denied <= denied:
            errors.append(f"listener {key}: expected denied paths are missing")
    return errors


def _validate_checks(checks: Any, counts: Any, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(checks, list) or not checks:
        return ["checks must be a nonempty list"]
    required = set(profile.get("required_checks") or [])
    seen: set[str] = set()
    computed = {key: 0 for key in COUNT_KEYS}
    computed["planned"] = len(checks)
    for index, check in enumerate(checks):
        errors.extend(_unknown(check, CHECK_ALLOWED_KEYS, f"checks[{index}]"))
        if not isinstance(check, dict):
            continue
        check_id = check.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            errors.append(f"checks[{index}].check_id is required")
            continue
        if check_id in seen:
            errors.append(f"duplicate check_id {check_id}")
        seen.add(check_id)
        if check_id not in required:
            errors.append(f"unexpected check_id {check_id}")
        status = check.get("status")
        if status not in STATUSES:
            errors.append(f"{check_id}: invalid status {status!r}")
            continue
        computed[
            {
                "PASS": "pass",
                "FAIL": "fail",
                "ERROR": "error",
                "BLOCKED": "blocked",
                "SKIPPED": "skipped",
                "NOT_APPLICABLE": "not_applicable",
            }[status]
        ] += 1
    missing = required - seen
    if missing:
        errors.append("missing required checks: " + ", ".join(sorted(missing)))
    if not isinstance(counts, dict) or set(counts) - COUNT_KEYS:
        errors.append("counts has unknown fields or is not an object")
    elif any(counts.get(key) != value for key, value in computed.items()):
        errors.append("counts contradict checks")
    if not any(isinstance(check, dict) and check.get("status") == "PASS" for check in checks):
        errors.append("zero meaningful PASS checks")
    if any(isinstance(check, dict) and check.get("status") != "PASS" for check in checks):
        errors.append("deployment checks must all PASS")
    return errors


def _validate_budget(budget: Any, profile: dict[str, Any]) -> list[str]:
    errors = _unknown(budget, BUDGET_KEYS, "budget")
    if not isinstance(budget, dict):
        return errors + ["budget must be an object"]
    required = profile.get("budgets") or {}
    for key in ("max_requests", "timeout_s", "deadline_s", "cleanup_reserved", "max_body_bytes"):
        if not _finite_number(budget.get(key)) or budget[key] <= 0:
            errors.append(f"budget.{key} must be positive finite")
        elif _finite_number(required.get(key)) and budget[key] > required[key]:
            errors.append(f"budget.{key} exceeds profile bound")
    for key in ("request_count", "cleanup_requests"):
        if not isinstance(budget.get(key), int) or budget[key] < 0:
            errors.append(f"budget.{key} must be a nonnegative integer")
    if isinstance(budget.get("max_requests"), (int, float)) and isinstance(budget.get("request_count"), int) and budget["request_count"] > budget["max_requests"]:
        errors.append("budget.request_count exceeds max_requests")
    return errors


def _validate_cleanup(cleanup: Any) -> list[str]:
    errors = _unknown(cleanup, CLEANUP_KEYS, "cleanup")
    if not isinstance(cleanup, dict):
        return errors + ["cleanup must be an object"]
    if cleanup.get("status") != "PASS":
        errors.append("cleanup must be PASS")
    if not isinstance(cleanup.get("requests"), int) or cleanup["requests"] < 0:
        errors.append("cleanup.requests must be a nonnegative integer")
    return errors


def _validate_artifacts(artifacts: Any, artifact_root: Path | None) -> list[str]:
    if not isinstance(artifacts, list):
        return ["artifacts must be a list"]
    if len(artifacts) > MAX_ARTIFACTS:
        return ["artifact count exceeds bound"]
    errors: list[str] = []
    total = 0
    for index, artifact in enumerate(artifacts):
        errors.extend(_unknown(artifact, ARTIFACT_KEYS, f"artifacts[{index}]"))
        if not isinstance(artifact, dict):
            continue
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path or Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            errors.append(f"artifacts[{index}].path must stay under artifact root")
            continue
        if not _is_sha(artifact.get("sha256")):
            errors.append(f"artifacts[{index}].sha256 must be a SHA-256")
            continue
        if artifact_root is not None:
            path = (artifact_root / raw_path).resolve()
            try:
                path.relative_to(artifact_root.resolve())
            except ValueError:
                errors.append(f"artifacts[{index}].path escapes artifact root")
                continue
            if not path.is_file():
                errors.append(f"artifact missing: {raw_path}")
                continue
            total += path.stat().st_size
            if total > MAX_ARTIFACT_BYTES:
                errors.append("artifact bytes exceed bound")
                break
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != artifact.get("sha256"):
                errors.append(f"artifact hash mismatch: {raw_path}")
    return errors


def evaluate_deployment_evidence(
    evidence: Any,
    *,
    expected_profile: str | None = None,
    registry: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
    artifact_root: Path | None = None,
) -> tuple[bool, str]:
    errors = validate_deployment_evidence(
        evidence,
        expected_profile=expected_profile,
        registry=registry,
        now=now,
        artifact_root=artifact_root,
    )
    return (not errors, "; ".join(errors) if errors else "ok")


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "PROFILE_REGISTRY_PATH",
    "PROFILE_SCHEMA_VERSION",
    "evaluate_deployment_evidence",
    "load_profile_registry",
    "profile_map",
    "validate_deployment_evidence",
    "validate_deployment_profile",
    "validate_profile_registry",
]
