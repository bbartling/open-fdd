"""Deployment topology contract tests (offline and fail-closed)."""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "security"))

from openfdd_security import STATUSES  # noqa: E402
from openfdd_security.deployment import (  # noqa: E402
    ARCHIVED_WIRE_SERVICES,
    EVIDENCE_SCHEMA_VERSION,
    active_profile_ids,
    PROFILE_SCHEMA_VERSION,
    evaluate_deployment_evidence,
    load_profile_registry,
    validate_deployment_profile,
    validate_profile_registry,
)


NOW = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.timezone.utc)


def _healthy_evidence(profile_id: str) -> dict:
    registry = load_profile_registry()
    profile = registry["profiles"][profile_id]
    required_images = list(profile["required_images"])
    candidate = {
        "candidate_id": "candidate-post5d",
        "source_sha": "a" * 40,
        "config_sha256": "b" * 64,
        "fixture_sha256": "c" * 64,
        "images": [
            {
                "name": name,
                "digest": f"sha256:{(str(index + 1) * 64)[:64]}",
                "platform": "linux/amd64",
            }
            for index, name in enumerate(required_images)
        ],
    }
    image_digests = {image["name"]: image["digest"] for image in candidate["images"]}
    services = []
    for name in profile["required_services"]:
        services.append(
            {
                "name": name,
                "status": "PRESENT",
                "image": name,
                "digest": image_digests[name],
            }
        )
    services.extend(
        {"name": name, "status": "ABSENT"}
        for name in profile["forbidden_services"]
    )
    listeners = []
    for expected in profile["listeners"]:
        observed = dict(expected)
        observed["observed"] = True
        observed["denied_paths"] = list(expected["expected_denied_paths"])
        observed.pop("expected_denied_paths")
        listeners.append(observed)
    checks = [
        {"check_id": check_id, "status": "PASS", "detail": "offline contract"}
        for check_id in profile["required_checks"]
    ]
    binding = {
        "candidate_source_sha_start": candidate["source_sha"],
        "candidate_source_sha_end": candidate["source_sha"],
        "config_sha256_start": candidate["config_sha256"],
        "config_sha256_end": candidate["config_sha256"],
        "fixture_sha256_start": candidate["fixture_sha256"],
        "fixture_sha256_end": candidate["fixture_sha256"],
    }
    counts = {
        "planned": len(checks),
        "pass": len(checks),
        "fail": 0,
        "error": 0,
        "blocked": 0,
        "skipped": 0,
        "not_applicable": 0,
    }
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "run_id": "post5d-qualification",
        "profile_id": profile_id,
        "profile_version": profile["profile_version"],
        "source_sha": candidate["source_sha"],
        "started_at": "2026-10-03T11:59:00Z",
        "ended_at": "2026-10-03T12:00:00Z",
        "execution_mode": "offline",
        "candidate": candidate,
        "binding": binding,
        "origin": {
            "canonical": "https://example.test",
            "allowlist": ["https://example.test"],
            "resolved_exposure": profile["origin"]["resolved_exposure"],
        },
        "services": services,
        "listeners": listeners,
        "checks": checks,
        "counts": counts,
        "budget": {
            "max_requests": profile["budgets"]["max_requests"],
            "request_count": 4,
            "timeout_s": profile["budgets"]["timeout_s"],
            "deadline_s": profile["budgets"]["deadline_s"],
            "cleanup_reserved": profile["budgets"]["cleanup_reserved"],
            "cleanup_requests": 1,
            "max_body_bytes": profile["budgets"]["max_body_bytes"],
        },
        "cleanup": {"status": "PASS", "requests": 1},
        "artifacts": [],
        "notes": ["sanitized offline fixture"],
    }


class DeploymentProfileContractTest(unittest.TestCase):
    def test_registry_is_valid_and_portal_is_the_active_cloud_profile(self) -> None:
        registry = load_profile_registry()
        self.assertEqual(registry["schema_version"], PROFILE_SCHEMA_VERSION)
        self.assertEqual(validate_profile_registry(registry), [])
        self.assertEqual(
            set(registry["profiles"]),
            {
                "cloud_portal",
                "cloud_mqtt_hub",
                "ot_local_bacnet_modbus",
                "ot_local_haystack",
                "local_development",
            },
        )
        self.assertEqual(active_profile_ids(registry), ["cloud_portal", "local_development"])
        portal = registry["profiles"]["cloud_portal"]
        self.assertEqual(
            portal["required_services"],
            ["openfdd-web", "openfdd-central", "openfdd-timescale"],
        )
        self.assertEqual(portal["optional_services"], ["openfdd-mcp"])
        self.assertTrue(ARCHIVED_WIRE_SERVICES <= set(portal["forbidden_services"]))
        self.assertNotIn("mqtt_acl", portal["required_execution_suites"])
        self.assertIs(portal["auth"]["multi_tenant"], True)
        self.assertIs(portal["auth"]["jwt_required"], True)
        self.assertGreaterEqual(portal["auth"]["min_jwt_secret_chars"], 32)
        nf = portal["egress"]["nf_portal"]
        self.assertEqual(nf["qualification_mode"], "emulator_only")
        self.assertEqual(nf["real_portal_connections"], "forbidden")
        self.assertIn("POST /api/v1/point/data", nf["forbidden_methods"])

    def test_every_profile_declares_lifecycle_and_ot_profiles_are_archived(self) -> None:
        registry = load_profile_registry()
        for pid in ("cloud_mqtt_hub", "ot_local_bacnet_modbus", "ot_local_haystack"):
            prof = registry["profiles"][pid]
            self.assertEqual(prof["lifecycle"], "archived", pid)
            self.assertTrue(prof["archive_reason"].strip(), pid)
        for pid in active_profile_ids(registry):
            prof = registry["profiles"][pid]
            wire = set(prof["required_services"]) | set(prof["optional_services"])
            self.assertFalse(wire & ARCHIVED_WIRE_SERVICES, pid)

    def test_portal_profile_source_recipes_exist(self) -> None:
        portal = load_profile_registry()["profiles"]["cloud_portal"]
        for recipe in portal["source_recipes"]:
            self.assertTrue((ROOT / recipe).is_file(), recipe)

    def test_portal_rejects_mqtt_or_ot_services(self) -> None:
        portal = copy.deepcopy(load_profile_registry()["profiles"]["cloud_portal"])
        portal["required_services"].append("openfdd-mqtt")
        portal["required_images"].append("openfdd-mqtt")
        errors = validate_deployment_profile("cloud_portal", portal)
        self.assertTrue(any("web + central + timescale" in e for e in errors), errors)
        self.assertTrue(any("archived wire service" in e for e in errors), errors)

        portal = copy.deepcopy(load_profile_registry()["profiles"]["cloud_portal"])
        portal["optional_services"].append("openfdd-fieldbus")
        portal["forbidden_services"].remove("openfdd-fieldbus")
        errors = validate_deployment_profile("cloud_portal", portal)
        self.assertTrue(any("only openfdd-mcp may be optional" in e for e in errors), errors)
        self.assertTrue(any("must be forbidden" in e for e in errors), errors)

    def test_portal_rejects_mqtt_acl_suite(self) -> None:
        portal = copy.deepcopy(load_profile_registry()["profiles"]["cloud_portal"])
        portal["required_execution_suites"].append("mqtt_acl")
        errors = validate_deployment_profile("cloud_portal", portal)
        self.assertTrue(any("mqtt_acl" in e for e in errors), errors)

    def test_portal_auth_must_be_multi_tenant_with_long_secret(self) -> None:
        for field, value, needle in (
            ("multi_tenant", False, "multi_tenant"),
            ("jwt_required", False, "jwt_required"),
            ("min_jwt_secret_chars", 16, "min_jwt_secret_chars"),
            ("open_bind_escape_hatch", "allowed", "open_bind_escape_hatch"),
        ):
            portal = copy.deepcopy(load_profile_registry()["profiles"]["cloud_portal"])
            portal["auth"][field] = value
            errors = validate_deployment_profile("cloud_portal", portal)
            self.assertTrue(any(needle in e for e in errors), (field, errors))

    def test_portal_nf_egress_is_loopback_emulator_only(self) -> None:
        for origin in ("https://tenant.normal-online.net", "http://10.0.0.5:8080", "http://nf-emulator:18089"):
            portal = copy.deepcopy(load_profile_registry()["profiles"]["cloud_portal"])
            portal["egress"]["nf_portal"]["qualification_origins"] = [origin]
            errors = validate_deployment_profile("cloud_portal", portal)
            self.assertTrue(any("not a loopback emulator" in e for e in errors), (origin, errors))
        portal = copy.deepcopy(load_profile_registry()["profiles"]["cloud_portal"])
        portal["egress"]["nf_portal"]["real_portal_connections"] = "allowed"
        portal["egress"]["nf_portal"]["forbidden_methods"] = []
        errors = validate_deployment_profile("cloud_portal", portal)
        self.assertTrue(any("real NF portal" in e for e in errors), errors)
        self.assertTrue(any("point writes" in e for e in errors), errors)

    def test_registry_without_portal_profile_is_invalid(self) -> None:
        registry = copy.deepcopy(load_profile_registry())
        registry["profiles"].pop("cloud_portal")
        self.assertTrue(any("cloud_portal" in e for e in validate_profile_registry(registry)))

    def test_archived_profile_needs_reason_and_active_cannot_carry_one(self) -> None:
        registry = load_profile_registry()
        hub = copy.deepcopy(registry["profiles"]["cloud_mqtt_hub"])
        hub.pop("archive_reason")
        self.assertTrue(any("archive_reason" in e for e in validate_deployment_profile("cloud_mqtt_hub", hub)))
        portal = copy.deepcopy(registry["profiles"]["cloud_portal"])
        portal["archive_reason"] = "x"
        self.assertTrue(any("archive_reason" in e for e in validate_deployment_profile("cloud_portal", portal)))
        portal = copy.deepcopy(registry["profiles"]["cloud_portal"])
        portal["lifecycle"] = "deprecated"
        self.assertTrue(any("lifecycle" in e for e in validate_deployment_profile("cloud_portal", portal)))

    def test_archived_cloud_profile_still_requires_mqtt_and_forbids_every_ot_image(self) -> None:
        registry = load_profile_registry()
        cloud = copy.deepcopy(registry["profiles"]["cloud_mqtt_hub"])
        cloud["required_services"].remove("openfdd-mqtt")
        cloud["required_services"].append("openfdd-bacnet-modbus")
        errors = validate_deployment_profile("cloud_mqtt_hub", cloud)
        self.assertTrue(any("web + central + mqtt" in error for error in errors))
        self.assertTrue(any("required and forbidden" in error for error in errors))

    def test_ot_requires_exactly_one_connector_and_no_broker(self) -> None:
        registry = load_profile_registry()
        ot = copy.deepcopy(registry["profiles"]["ot_local_haystack"])
        ot["required_services"].append("openfdd-bacnet-modbus")
        ot["required_images"].append("openfdd-bacnet-modbus")
        errors = validate_deployment_profile("ot_local_haystack", ot)
        self.assertTrue(any("selected connector exactly" in error for error in errors))
        self.assertTrue(any("required and forbidden" in error for error in errors))

    def test_healthy_portal_evidence_passes(self) -> None:
        evidence = _healthy_evidence("cloud_portal")
        ok, reason = evaluate_deployment_evidence(
            evidence, expected_profile="cloud_portal", now=NOW
        )
        self.assertTrue(ok, reason)

    def test_archived_profile_evidence_cannot_qualify(self) -> None:
        for pid in ("cloud_mqtt_hub", "ot_local_bacnet_modbus", "ot_local_haystack"):
            evidence = _healthy_evidence(pid)
            ok, reason = evaluate_deployment_evidence(evidence, expected_profile=pid, now=NOW)
            self.assertFalse(ok, pid)
            self.assertIn("archived", reason)
            ok, reason = evaluate_deployment_evidence(
                evidence, expected_profile=pid, now=NOW, allow_archived=True
            )
            self.assertTrue(ok, (pid, reason))

    def test_present_mqtt_service_blocks_portal_evidence(self) -> None:
        evidence = _healthy_evidence("cloud_portal")
        for row in evidence["services"]:
            if row["name"] == "openfdd-mqtt":
                row["status"] = "PRESENT"
                row["image"] = "openfdd-web"
                row["digest"] = evidence["candidate"]["images"][0]["digest"]
        ok, reason = evaluate_deployment_evidence(evidence, expected_profile="cloud_portal", now=NOW)
        self.assertFalse(ok)
        self.assertIn("openfdd-mqtt is not proven ABSENT", reason)

    def test_missing_forbidden_service_evidence_blocks_zero_ot_claim(self) -> None:
        evidence = _healthy_evidence("cloud_portal")
        evidence["services"] = [
            row
            for row in evidence["services"]
            if row["name"] != "openfdd-bacnet-modbus"
        ]
        ok, reason = evaluate_deployment_evidence(
            evidence, expected_profile="cloud_portal", now=NOW
        )
        self.assertFalse(ok)
        self.assertIn("missing service evidence", reason)

    def test_changed_candidate_binding_blocks_evidence(self) -> None:
        evidence = _healthy_evidence("cloud_portal")
        evidence["binding"]["config_sha256_end"] = "d" * 64
        ok, reason = evaluate_deployment_evidence(
            evidence, expected_profile="cloud_portal", now=NOW
        )
        self.assertFalse(ok)
        self.assertIn("binding mismatch", reason)

    def test_contradictory_counts_and_duplicate_checks_fail_closed(self) -> None:
        evidence = _healthy_evidence("cloud_portal")
        evidence["checks"].append(dict(evidence["checks"][0]))
        evidence["counts"]["planned"] += 1
        evidence["counts"]["pass"] += 1
        ok, reason = evaluate_deployment_evidence(
            evidence, expected_profile="cloud_portal", now=NOW
        )
        self.assertFalse(ok)
        self.assertTrue("duplicate check_id" in reason or "counts contradict" in reason)

    def test_unknown_status_and_stale_evidence_fail_closed(self) -> None:
        evidence = _healthy_evidence("cloud_portal")
        evidence["checks"][0]["status"] = "WARN"
        evidence["ended_at"] = "2026-10-01T12:00:00Z"
        ok, reason = evaluate_deployment_evidence(
            evidence, expected_profile="cloud_portal", now=NOW
        )
        self.assertFalse(ok)
        self.assertTrue("invalid status" in reason or "stale" in reason)

    def test_artifact_path_escape_and_hash_are_checked(self) -> None:
        evidence = _healthy_evidence("cloud_portal")
        evidence["artifacts"] = [{"path": "../secret.json", "sha256": "d" * 64}]
        ok, reason = evaluate_deployment_evidence(
            evidence, expected_profile="cloud_portal", now=NOW
        )
        self.assertFalse(ok)
        self.assertIn("artifact", reason)


if __name__ == "__main__":
    unittest.main()
